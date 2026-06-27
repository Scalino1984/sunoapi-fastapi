from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.portable_path_service import to_portable_path
from app.database import SessionLocal
from app.models import ActivityLog, AudioAsset, AudioProject, Song, StatusNotification, SunoTask
from app.utils.time_utils import utc_now_naive

MODELS: dict[str, dict[str, str]] = {
    "pro": {"id": "black-forest-labs/flux-2-pro", "family": "flux2"},
    "max": {"id": "black-forest-labs/flux-2-max", "family": "flux2"},
    "flex": {"id": "black-forest-labs/flux-2-flex", "family": "flux2"},
    "klein": {"id": "black-forest-labs/flux-2-klein-4b", "family": "flux2"},
    "schnell": {"id": "black-forest-labs/flux-schnell", "family": "flux1"},
}

BASE_QUALITY = (
    "Professional record-label album cover artwork, gallery-grade illustration, single strong central focal point, "
    "balanced composition with deliberate negative space, crisp focus, rich micro-detail, cinematic depth, premium print quality."
)
NO_TEXT_CLAUSE = (
    "The artwork is purely pictorial with smooth, clean, unmarked surfaces and empty space reserved for later typography — "
    "the entire frame is imagery only, free of any lettering, logos or watermarks."
)
TITLE_CLAUSE_SMALL = (
    'A small album title "{title}" in clean uppercase lettering sits discreetly in a lower corner of the cover, modest in size so '
    "the artwork clearly dominates; the text is crisp, perfectly spelled, readable and undistorted. It is the only text in the frame, "
    "with no other words, logos or watermarks."
)
STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "deutschrap": {
        "aliases": ["rap", "story", "boombap", "boom bap", "hip hop", "hip-hop", "trap"],
        "style": "gritty cinematic urban hip-hop cover in the spirit of classic 90s boom-bap vinyl artwork, analog film-grain texture, dusty halftone print feel, slightly desaturated noir realism",
        "palette": "warm sodium-vapour amber, deep teal shadows, charcoal black, dirty concrete grey",
        "lighting": "low-key street lighting at golden dusk or under streetlamps, long dramatic shadows, atmospheric haze",
        "texture": "concrete, weathered brick, faded graffiti, scratched vinyl grain",
        "mood": "storytelling, brooding, raw and authentic, German street-tale atmosphere",
    },
    "deephouse": {
        "aliases": ["house", "deep", "club", "tech house", "techno", "edm"],
        "style": "refined minimalist electronic-music cover, clean geometric abstraction, smooth gradients, sophisticated modern design-studio aesthetic, subtle 3D render quality",
        "palette": "warm sunset oranges into deep indigo and magenta, soft pastel glow, occasional neon accent",
        "lighting": "soft diffused dusk light, gentle volumetric glow, smooth bokeh, dreamy haze",
        "texture": "frosted glass, liquid chrome, soft sand, flowing silk-like forms",
        "mood": "hypnotic, warm, sophisticated, late-evening Ibiza terrace serenity",
    },
    "dancehall": {
        "aliases": ["patois", "reggae", "jamaica", "soundsystem", "sound system", "ragga"],
        "style": "vibrant Caribbean sound-system poster art, bold saturated colours, energetic street-culture illustration, sun-soaked tropical realism with a hand-painted dancehall flyer edge",
        "palette": "lush green, hot yellow-gold, vivid red, ocean turquoise, rich brown skin tones",
        "lighting": "bright tropical sunlight, warm golden hour, glossy highlights, lively contrast",
        "texture": "palm leaves, weathered wood, vinyl speaker stacks, painted concrete walls",
        "mood": "joyful, sun-drenched, high-energy street-dance vibe, irie and alive",
    },
    "dnb": {
        "aliases": ["drum and bass", "drum & bass", "dnb", "jungle", "liquid", "breakbeat"],
        "style": "high-energy futuristic drum-and-bass cover, sleek cyber-rave aesthetic, sharp neon linework, sense of speed and motion, dark underground club atmosphere with sci-fi polish",
        "palette": "electric cyan, ultraviolet purple, acid green, hot pink on near-black",
        "lighting": "neon rim light, laser beams, light trails, glowing fog, deep contrast",
        "texture": "wet asphalt reflections, holographic surfaces, jungle foliage, circuit-board detail",
        "mood": "fast, intense, hypnotic, nocturnal rave energy",
    },
    "alternate": {
        "aliases": ["alt", "remix", "version", "experimental"],
        "style": "conceptual experimental cover artwork, surreal and artful reinterpretation, double-exposure and mixed-media collage feel, bold graphic abstraction",
        "palette": "muted duotone with one striking accent colour, high-contrast tonal play",
        "lighting": "dramatic directional light, deep shadow shapes, abstract glow",
        "texture": "torn paper, glitch artifacts, layered transparency, ink and risograph grain",
        "mood": "mysterious, artistic, unconventional, a fresh take on a familiar theme",
    },
    "default": {
        "aliases": [],
        "style": "striking modern album cover illustration with a clear artistic concept",
        "palette": "harmonious, intentional colour palette with strong contrast",
        "lighting": "cinematic lighting with clear direction and depth",
        "texture": "rich, tactile surface detail",
        "mood": "memorable, emotive, professional",
    },
}
ART_DIRECTOR_SYSTEM = (
    "You are an award-winning art director for music album covers. Given information about a song, invent ONE striking, concrete visual concept. "
    "Reply with a single vivid description in English, 1-2 sentences. Describe only what is literally seen: subject, setting, key objects, mood, atmosphere, lighting. "
    "Never mention music, lyrics, song structure, section labels, text, letters, captions or typography. Never name real brands, trademarks, logos, living people or celebrities. Output only the description."
)


def slugify(text: str, maxlen: int = 48) -> str:
    value = re.sub(r"[^a-z0-9 _-]", "", str(text or "").lower())
    return re.sub(r"\s+", "_", value).strip("_")[:maxlen] or "cover"


def auto_genre_from_style(music_style: str | None) -> str:
    style = str(music_style or "").lower()
    if not style:
        return "default"
    for key, preset in STYLE_PRESETS.items():
        if key != "default" and any(alias in style for alias in preset.get("aliases", [])):
            return key
    return "default"


def build_prompt(user_prompt: str, genre_key: str, *, title: str | None, has_reference: bool, note: str | None) -> str:
    preset = STYLE_PRESETS.get(genre_key) or STYLE_PRESETS["default"]
    ref_clause = (
        " The key subject should faithfully preserve identity, outfit, silhouette and defining visual traits from the provided reference image, integrated naturally into the generated cover scene."
        if has_reference else ""
    )
    note_clause = f" Important additional direction: {note.strip()}." if note else ""
    text_clause = TITLE_CLAUSE_SMALL.format(title=title.strip()) if title else NO_TEXT_CLAUSE
    return (
        f"{BASE_QUALITY} Subject: {user_prompt.strip().rstrip('.')}.{ref_clause} "
        f"Art direction: {preset['style']}. Colour palette: {preset['palette']}. Lighting: {preset['lighting']}. "
        f"Surface and texture: {preset['texture']}. Overall mood: {preset['mood']}.{note_clause} {text_clause}"
    )


def _first_http_url_from_output(item: Any) -> str | None:
    if isinstance(item, str) and item.startswith(("http://", "https://")):
        return item
    for attr in ("url", "uri", "source_url"):
        value = getattr(item, attr, None)
        if value and str(value).startswith(("http://", "https://")):
            return str(value)
    return None


def save_output(output: Any, path: Path) -> str | None:
    items = list(output) if isinstance(output, (list, tuple)) else [output]
    if not items:
        raise ValueError("Replicate hat keine Bilddaten geliefert.")
    item = items[0]
    source_url = _first_http_url_from_output(item)
    if hasattr(item, "read"):
        path.write_bytes(item.read())
        return source_url
    if source_url:
        import urllib.request
        urllib.request.urlretrieve(source_url, path)
        return source_url
    raise ValueError("Replicate-Ausgabe enthält keine verwertbaren Bilddaten.")


def _safe_text(value: str | None, fallback: str = "") -> str:
    return str(value or fallback).strip()


def _asset_title(asset: AudioAsset, song: Song | None = None) -> str:
    return _safe_text(asset.display_title or asset.title or (song.title if song else None) or asset.filename, f"AudioAsset {asset.id}")


def _fallback_concept(title: str, style: str, prompt: str, lyrics: str, note: str | None = None) -> str:
    body = next((str(part).strip() for part in (prompt, lyrics) if str(part or "").strip()), title)
    if len(body) > 280:
        body = body[:280] + "..."
    note_text = f" Focus on {note.strip()}." if note else ""
    style_text = f"The atmosphere reflects {style}. " if style else ""
    return f"A striking visual scene inspired by '{title}', centered on {body}. {style_text}{note_text}".strip()


def _is_replicate_safety_error(exc: Exception) -> bool:
    text = str(exc or '').lower()
    return any(marker in text for marker in ('sensitive', 'flagged', 'safety', 'e005', 'moderation'))


def _safe_cover_concept(title: str, style: str, note: str | None = None) -> str:
    style_hint = f" with the mood of {style}" if style else ""
    note_hint = f" Extra direction: {note.strip()}" if note else ""
    return (
        "A safe abstract cinematic album-cover scene for an urban music release"
        f"{style_hint}: dramatic lights, atmospheric haze, deep shadows, refined composition, no people, no weapons, no explicit content, no written text."
        f"{note_hint}"
    ).strip()


class ReplicateCoverService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def create_status_task(self, asset: AudioAsset, *, model: str, note: str | None = None, has_reference: bool = False) -> SunoTask:
        song = self.db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
        title = _asset_title(asset, song)
        now = utc_now_naive()
        task = SunoTask(
            task_id=None,
            task_type="generate_cover_art",
            status="RUNNING",
            progress=0,
            started_at=now,
            heartbeat_at=now,
            request_payload={"audio_asset_id": asset.id, "song_id": song.id if song else None, "title": title, "model": model, "note": note or None, "has_reference": bool(has_reference), "backend": "replicate", "local_task": True},
            response_payload={"background": True, "local_task": True, "status": "RUNNING", "progress": {"percent": 0, "phase": "started", "updated_at": now.isoformat()}},
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        self.db.add(StatusNotification(
            event_type="cover_generation_started",
            title=f"Cover-Erstellung läuft: {title}",
            message="Replicate erzeugt ein professionelles Titel-Cover für diesen Song.",
            severity="info",
            status="unread",
            task_local_id=task.id,
            content_type="audio",
            content_id=asset.id,
            target_tab="status",
            target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": "generate_cover_art", "status": "RUNNING"},
        ))
        self.db.commit()
        return task

    @staticmethod
    def run_generation_task(task_id: int, asset_id: int, model: str, note: str | None = None, reference_path: str | None = None) -> None:
        db = SessionLocal()
        try:
            ReplicateCoverService(db)._run_generation(task_id, asset_id, model, note=note, reference_path=reference_path)
        finally:
            if reference_path:
                try:
                    Path(reference_path).unlink(missing_ok=True)
                except Exception:
                    pass
            db.close()

    def _finish_started_notification(self, task_id: int, status: str) -> None:
        try:
            started = (
                self.db.query(StatusNotification)
                .filter(
                    StatusNotification.task_local_id == task_id,
                    StatusNotification.event_type == "cover_generation_started",
                    StatusNotification.status != "done",
                    StatusNotification.is_deleted.is_(False),
                )
                .all()
            )
            for item in started:
                item.status = "done"
                item.completed_at = utc_now_naive()
                payload = dict(item.target_payload or {})
                payload["status"] = status
                item.target_payload = payload
                self.db.add(item)
        except Exception:
            pass

    def _run_generation(self, task_id: int, asset_id: int, model: str, *, note: str | None, reference_path: str | None) -> None:
        task = self.db.query(SunoTask).filter(SunoTask.id == task_id).first()
        asset = self.db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
        if not task or not asset:
            return
        song = self.db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
        title = _asset_title(asset, song)
        try:
            if model not in MODELS:
                raise ValueError(f"Unbekanntes Cover-Modell: {model}")
            token = self.settings.replicate_api_token.strip()
            if not token:
                raise ValueError("REPLICATE_API_TOKEN ist nicht gesetzt.")
            prompt_text = _safe_text(asset.prompt or (song.prompt if song else None))
            lyrics = _safe_text(asset.lyrics or (song.lyrics if song else None))
            style = _safe_text(asset.style)
            genre = auto_genre_from_style(style)
            concept = self._build_concept(title, style, prompt_text, lyrics, note, token)
            final_prompt = build_prompt(concept, genre, title=title.upper(), has_reference=bool(reference_path), note=note)
            safety_retry = False
            try:
                target_path, public_url, remote_url = self._generate_cover_image(asset.id, title, model, final_prompt, token, reference_path)
            except Exception as image_exc:
                if not _is_replicate_safety_error(image_exc):
                    raise
                safety_retry = True
                concept = _safe_cover_concept(title, style, note)
                final_prompt = build_prompt(concept, genre, title=None, has_reference=bool(reference_path), note=None)
                target_path, public_url, remote_url = self._generate_cover_image(asset.id, f"{title}_safe", model, final_prompt, token, reference_path)
            metadata = self._cover_metadata(target_path, public_url, remote_url, model, title, genre, note, concept, final_prompt)
            if safety_retry:
                metadata["generated_cover"]["safety_retry"] = True
                metadata["generated_cover"]["title_text_removed"] = True
                metadata["cover_cache"]["safety_retry"] = True
            self._apply_cover_metadata(asset, song, public_url, metadata)
            task.status = "SUCCESS"
            task.progress = 100
            task.heartbeat_at = utc_now_naive()
            task.completed_at = task.heartbeat_at
            task.error_message = None
            task.result_payload = {"audio_asset_id": asset.id, "song_id": song.id if song else None, "cover_url": public_url, "replicate_source_url": remote_url, "model": model, "title": title, "note": note or None, "genre": genre, "safety_retry": safety_retry}
            self._finish_started_notification(task.id, "SUCCESS")
            self.db.add(task)
            self.db.add(ActivityLog(action="generate_ai_cover", content_type="audio", content_id=asset.id, new_value={"cover_url": public_url, "replicate_source_url": remote_url, "model": model, "title": title, "safety_retry": safety_retry}, metadata_json={"task_local_id": task.id, "song_id": song.id if song else None, "prompt_length": len(final_prompt), "note": note or None}))
            success_message = "Das neue Titel-Cover wurde lokal gespeichert und der Library zugewiesen."
            if safety_retry:
                success_message = "Replicate hat den ersten Cover-Prompt blockiert. Es wurde automatisch ein sicherer, textloser Fallback erzeugt und lokal gespeichert."
            self.db.add(StatusNotification(event_type="cover_generation_completed", title=f"Cover erstellt: {title}", message=success_message, severity="success", status="unread", task_local_id=task.id, content_type="audio", content_id=asset.id, target_tab="library", target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": "generate_cover_art", "status": "SUCCESS", "safety_retry": safety_retry}, completed_at=utc_now_naive()))
            self.db.commit()
        except Exception as exc:
            task.status = "FAILED"
            task.heartbeat_at = utc_now_naive()
            task.completed_at = task.heartbeat_at
            task.error_message = str(exc)
            task.result_payload = {"audio_asset_id": asset.id, "status": "FAILED", "error": str(exc), "safety_error": _is_replicate_safety_error(exc)}
            self._finish_started_notification(task.id, "FAILED")
            self.db.add(task)
            self.db.add(StatusNotification(event_type="cover_generation_failed", title=f"Cover fehlgeschlagen: {title}", message=str(exc), severity="error", status="unread", task_local_id=task.id, content_type="audio", content_id=asset.id, target_tab="status", target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": "generate_cover_art", "status": "FAILED", "safety_error": _is_replicate_safety_error(exc)}, completed_at=utc_now_naive()))
            self.db.commit()

    def _build_concept(self, title: str, style: str, prompt_text: str, lyrics: str, note: str | None, token: str) -> str:
        try:
            return self._enhance_with_llm(self.settings.replicate_cover_text_model, title, style, prompt_text, lyrics, note, token)
        except Exception:
            return _fallback_concept(title, style, prompt_text, lyrics, note)

    def _enhance_with_llm(self, text_model: str, title: str, style: str, prompt_text: str, lyrics: str, note: str | None, token: str) -> str:
        import os
        import replicate
        old_token = os.environ.get("REPLICATE_API_TOKEN")
        os.environ["REPLICATE_API_TOKEN"] = token
        try:
            body = "\n".join(part for part in (prompt_text, lyrics) if part).strip()
            if len(body) > 2000:
                body = body[:2000] + " ..."
            user_message = f"Create a cover concept for this song.\nTITLE: {title}\nMUSIC STYLE: {style}\nLYRICS / STRUCTURE:\n{body or title}"
            if note:
                user_message += f"\n\nIMPORTANT EXTRA INSTRUCTION: {note.strip()}"
            output = replicate.run(text_model, input={"prompt": user_message, "system_prompt": ART_DIRECTOR_SYSTEM, "max_tokens": 300, "temperature": 0.7})
            text = output if isinstance(output, str) else "".join(str(chunk) for chunk in output)
            return text.strip().strip('"').strip("'").strip() or _fallback_concept(title, style, prompt_text, lyrics, note)
        finally:
            if old_token is None:
                os.environ.pop("REPLICATE_API_TOKEN", None)
            else:
                os.environ["REPLICATE_API_TOKEN"] = old_token

    def _generate_cover_image(self, asset_id: int, title: str, model: str, prompt: str, token: str, reference_path: str | None) -> tuple[Path, str, str | None]:
        import os
        import replicate
        old_token = os.environ.get("REPLICATE_API_TOKEN")
        os.environ["REPLICATE_API_TOKEN"] = token
        target_path = self.settings.cover_storage_path / f"ai_cover_{asset_id}_{slugify(title)}_{utc_now_naive().strftime('%Y%m%d_%H%M%S')}.jpg"
        self.settings.cover_storage_path.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"prompt": prompt, "aspect_ratio": "1:1", "output_format": "jpg", "output_quality": 95}
        input_images = []
        try:
            if reference_path and MODELS[model]["family"] == "flux2":
                handle = open(Path(reference_path).expanduser(), "rb")
                input_images.append(handle)
                payload["input_images"] = input_images
            if MODELS[model]["family"] == "flux1":
                payload.update({"num_inference_steps": 4, "go_fast": True, "disable_safety_checker": False})
            output = replicate.run(MODELS[model]["id"], input=payload)
            remote_url = save_output(output, target_path)
            return target_path, f"{self.settings.suno_cover_public_route.rstrip('/')}/{target_path.name}", remote_url
        finally:
            for handle in input_images:
                try:
                    handle.close()
                except Exception:
                    pass
            if old_token is None:
                os.environ.pop("REPLICATE_API_TOKEN", None)
            else:
                os.environ["REPLICATE_API_TOKEN"] = old_token

    def _cover_metadata(self, target_path: Path, public_url: str, remote_url: str | None, model: str, title: str, genre: str, note: str | None, concept: str, final_prompt: str) -> dict[str, Any]:
        data = target_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        source_url = remote_url or public_url
        cover_cache = {"status": "generated", "source_url": source_url, "replicate_source_url": remote_url, "public_url": public_url, "local_path": to_portable_path(target_path, storage_root=get_settings().cover_storage_path), "filename": target_path.name, "checksum_sha256": digest, "content_type": "image/jpeg", "file_size_bytes": len(data), "cached_at": utc_now_naive().isoformat(), "backend": "replicate"}
        generated_cover = {"backend": "replicate", "model": model, "title": title, "genre": genre, "note": note or None, "concept": concept, "final_prompt": final_prompt, "public_url": public_url, "replicate_source_url": remote_url, "generated_at": utc_now_naive().isoformat()}
        return {"cover_cache": cover_cache, "generated_cover": generated_cover}

    def _apply_cover_metadata(self, asset: AudioAsset, song: Song | None, public_url: str, metadata: dict[str, Any]) -> None:
        asset.image_url = public_url
        asset_metadata = dict(asset.metadata_json or {})
        asset_metadata.update({"source_image_url": metadata["cover_cache"].get("source_url"), "cover_cache": metadata["cover_cache"], "generated_cover": metadata["generated_cover"]})
        asset.metadata_json = asset_metadata
        self.db.add(asset)
        project_id = asset.project_id or (song.project_id if song else None)
        if song:
            song.cover_image_url = public_url
            song_metadata = dict(song.metadata_json or {})
            song_metadata.update({"source_image_url": metadata["cover_cache"].get("source_url"), "cover_cache": metadata["cover_cache"], "generated_cover": metadata["generated_cover"]})
            song.metadata_json = song_metadata
            self.db.add(song)
        if project_id:
            project = self.db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
            if project:
                project.cover_image_url = public_url
                project_metadata = dict(project.metadata_json or {})
                project_metadata["generated_cover"] = metadata["generated_cover"]
                project.metadata_json = project_metadata
                self.db.add(project)
