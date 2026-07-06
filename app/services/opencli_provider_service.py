from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import ActivityLog, AudioAsset, AudioProject, Song, StatusNotification, SunoTask
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.portable_path_service import to_portable_path
from app.services.asset_capabilities import local_only_capabilities, mark_opencli_generation
from app.services.task_lifecycle_service import append_task_debug_event, append_task_step_log
from app.utils.time_utils import utc_now_naive


AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
METADATA_EXTENSIONS = {".json"}
SUPPORTED_OPENCLI_FLAGS = {
    "model",
    "customMode",
    "instrumental",
    "prompt",
    "title",
    "style",
    "negative_tags",
    "styleWeight",
    "weirdnessConstraint",
}


class OpenCliProviderError(RuntimeError):
    """Kontrollierter Fehler für den optionalen OpenCLI-Provider."""


class OpenCliProviderService:
    """
    Interner OpenCLI-Provider für Suno Song Studio.

    Wichtig: Der Provider hängt absichtlich an der bestehenden Task-/Song-/AudioAsset-Kette.
    Er ersetzt keine SunoAPI-Funktion, sondern erzeugt lokale AudioAssets über einen eigenen Task-Typ.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def runtime_status(self, *, include_account: bool = False) -> dict[str, Any]:
        installed_path = shutil.which(self.settings.suno_opencli_binary)
        status: dict[str, Any] = {
            "enabled": bool(self.settings.suno_opencli_enabled),
            "binary": self.settings.suno_opencli_binary,
            "installed": installed_path is not None,
            "binary_path": installed_path,
            "formats": self.settings.opencli_formats_list,
            "confirm_paid": bool(self.settings.suno_opencli_confirm_paid),
            "wait_timeout_seconds": int(self.settings.suno_opencli_wait_timeout_seconds),
            "timeout_seconds": int(self.settings.suno_opencli_timeout_seconds),
            "max_imported_clips": int(self.settings.suno_opencli_max_imported_clips),
            "models": ["chirp-fenix", "chirp-bluejay", "chirp-v4", "chirp-v3-5"],
            "model_map": self.settings.opencli_model_map,
            "ready": bool(self.settings.suno_opencli_enabled and installed_path),
        }
        if include_account and status["ready"]:
            try:
                status["opencli_status"] = self._run_opencli(["status"], timeout=45, stream=False)
            except Exception as exc:
                status["ready"] = False
                status["error"] = str(exc)
        return status

    def create_generation_task(self, payload: dict[str, Any]) -> SunoTask:
        request_payload = self._normalize_generation_payload(payload)
        now = utc_now_naive()
        task = SunoTask(
            task_type="generate_music_opencli",
            status="QUEUED",
            progress=0,
            started_at=now,
            heartbeat_at=now,
            request_payload=request_payload,
            response_payload={
                "source": "opencli",
                "provider": "opencli",
                "queued_at": now.isoformat(),
            },
        )
        self.db.add(task)
        self.db.flush()
        task.task_id = f"opencli-{task.id}"
        append_task_debug_event(
            self.db,
            task,
            event="opencli_generation_queued",
            detail="OpenCLI-Generierung wurde eingereiht.",
            data={"task_id": task.task_id, "request_keys": sorted(request_payload.keys())},
            commit=False,
        )
        append_task_step_log(
            self.db,
            task,
            phase="queued",
            phase_label="OpenCLI eingereiht",
            detail="Generierung wartet auf lokale OpenCLI-Ausfuehrung.",
            data={"task_id": task.task_id},
            commit=False,
        )
        self.db.add(ActivityLog(
            action="opencli_generate_queued",
            content_type="task",
            content_id=task.id,
            old_value=None,
            new_value={"task_id": task.task_id, "status": task.status},
            metadata_json={"provider": "opencli", "request_keys": sorted(request_payload.keys())},
        ))
        self.db.add(StatusNotification(
            event_type="opencli_generation_queued",
            title="OpenCLI-Generierung eingereiht",
            message=f"{request_payload.get('title') or 'Neuer Song'} · wartet auf OpenCLI",
            severity="info",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task",
            content_id=task.id,
            target_tab="status",
            target_payload={"task_local_id": task.id, "provider": "opencli", "status": "QUEUED"},
        ))
        self.db.commit()
        self.db.refresh(task)
        return task

    def run_generation_task(self, task_id: int) -> None:
        task = self.db.query(SunoTask).filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False)).first()
        if not task:
            return

        old_status = task.status
        started_notification = self._mark_task_running(task)
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        output_dir = self._output_dir_for_task(task)
        output_dir.mkdir(parents=True, exist_ok=True)
        append_task_debug_event(
            self.db,
            task,
            event="opencli_generation_started",
            detail="OpenCLI-Generierung wurde gestartet.",
            data={"task_id": task.task_id, "output_dir": str(output_dir), "request_keys": sorted(request_payload.keys())},
            commit=False,
        )
        append_task_step_log(
            self.db,
            task,
            phase="started",
            phase_label="OpenCLI gestartet",
            detail="Lokale OpenCLI-Generierung laeuft.",
            data={"task_id": task.task_id},
            commit=False,
        )

        try:
            self._assert_provider_ready()
            command = self._build_generate_command(request_payload, output_dir)
            result = self._run_opencli(command, timeout=int(self.settings.suno_opencli_timeout_seconds), stream=False)
            download_results = self._download_generated_clips(result, output_dir)
            task.response_payload = {
                **(task.response_payload if isinstance(task.response_payload, dict) else {}),
                "source": "opencli",
                "provider": "opencli",
                "command_summary": self._safe_command_summary(command),
                "download_summary": [self._safe_command_summary(item.get("command", [])) for item in download_results if isinstance(item, dict)],
                "completed_at": utc_now_naive().isoformat(),
            }
            task.result_payload = self._result_payload(result, output_dir, download_results=download_results)
            candidates = self._select_primary_audio_files(output_dir)
            if not candidates:
                raise OpenCliProviderError(
                    "OpenCLI wurde beendet, aber es wurde keine abspielbare lokale Audiodatei gefunden. "
                    "Die Generierung kann bei Suno sichtbar sein, aber der lokale Download/Import war leer oder ungültig."
                )
            song = self._create_song(task, request_payload, output_dir)
            assets = self._register_generated_files(task, song, output_dir)
            task.status = "SUCCESS"
            task.progress = 100
            task.completed_at = utc_now_naive()
            task.heartbeat_at = task.completed_at
            task.error_message = None
            append_task_debug_event(
                self.db,
                task,
                event="opencli_generation_finished",
                detail="OpenCLI-Generierung wurde abgeschlossen.",
                data={
                    "task_id": task.task_id,
                    "status": task.status,
                    "song_id": song.id if song else None,
                    "audio_asset_ids": [asset.id for asset in assets],
                    "output_dir": str(output_dir),
                },
                commit=False,
            )
            append_task_step_log(
                self.db,
                task,
                phase="completed",
                phase_label="OpenCLI abgeschlossen",
                detail="Song und lokale Audiodateien wurden erzeugt und importiert.",
                data={"task_id": task.task_id, "audio_asset_count": len(assets)},
                commit=False,
            )
            self._mark_notification_done(started_notification)
            self._create_completed_notification(task, song, assets)
            self.db.add(ActivityLog(
                action="opencli_generate_completed",
                content_type="task",
                content_id=task.id,
                old_value={"status": old_status},
                new_value={"status": task.status, "song_id": song.id if song else None, "audio_asset_ids": [asset.id for asset in assets]},
                metadata_json={"provider": "opencli", "output_dir": str(output_dir)},
            ))
        except Exception as exc:
            task.status = "FAILED"
            task.completed_at = utc_now_naive()
            task.heartbeat_at = task.completed_at
            task.error_message = str(exc)
            task.result_payload = {
                **(task.result_payload if isinstance(task.result_payload, dict) else {}),
                "source": "opencli",
                "provider": "opencli",
                "failed_at": utc_now_naive().isoformat(),
                "error": str(exc),
                "output_dir": str(output_dir),
            }
            append_task_debug_event(
                self.db,
                task,
                event="opencli_generation_failed",
                detail=str(exc),
                level="error",
                data={"task_id": task.task_id, "exception_type": type(exc).__name__, "output_dir": str(output_dir)},
                commit=False,
            )
            append_task_step_log(
                self.db,
                task,
                phase="failed",
                phase_label="OpenCLI fehlgeschlagen",
                detail=str(exc),
                data={"task_id": task.task_id},
                commit=False,
            )
            self._mark_notification_done(started_notification)
            self._create_failed_notification(task, str(exc))
            self.db.add(ActivityLog(
                action="opencli_generate_failed",
                content_type="task",
                content_id=task.id,
                old_value={"status": old_status},
                new_value={"status": task.status, "error": str(exc)},
                metadata_json={"provider": "opencli", "output_dir": str(output_dir)},
            ))
        finally:
            task.updated_at = utc_now_naive()
            self.db.commit()

    def refresh_generation_task(self, task: SunoTask) -> SunoTask:
        """Aktualisiert lokale OpenCLI-Tasks ohne externe SunoAPI-Abfrage.

        Normalfall: Der Background-Task setzt RUNNING/SUCCESS/FAILED selbst.
        Fallback: Wenn Dateien und Result-Payload bereits vorliegen, aber der Status noch offen ist,
        wird der Import kontrolliert finalisiert. So bleiben Statusseite und Library konsistent.
        """
        if not task or task.task_type != "generate_music_opencli":
            return task
        if str(task.status or "").upper() in {"SUCCESS", "FAILED", "COMPLETED", "ERROR"}:
            return task

        existing_assets = self.db.query(AudioAsset).filter(
            AudioAsset.task_local_id == task.id,
            AudioAsset.is_deleted.is_(False),
        ).count()
        if existing_assets:
            task.status = "SUCCESS"
            task.progress = 100
            task.heartbeat_at = utc_now_naive()
            task.completed_at = task.completed_at or task.heartbeat_at
            self.db.commit()
            self.db.refresh(task)
            return task

        result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        if not result_payload.get("files"):
            return task

        output_dir = self._output_dir_for_task(task)
        candidates = self._select_primary_audio_files(output_dir)
        if not candidates:
            return task

        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        song = self._create_song(task, request_payload, output_dir)
        assets = self._register_generated_files(task, song, output_dir)
        task.status = "SUCCESS"
        task.progress = 100
        task.heartbeat_at = utc_now_naive()
        task.completed_at = task.completed_at or task.heartbeat_at
        task.error_message = None
        task.updated_at = utc_now_naive()
        self._create_completed_notification(task, song, assets)
        self.db.add(ActivityLog(
            action="opencli_generate_refresh_finalized",
            content_type="task",
            content_id=task.id,
            old_value=None,
            new_value={"status": task.status, "audio_asset_ids": [asset.id for asset in assets]},
            metadata_json={"provider": "opencli", "output_dir": str(output_dir)},
        ))
        self.db.commit()
        self.db.refresh(task)
        return task

    def _normalize_generation_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        custom_mode = bool(data.get("customMode") or data.get("custom_mode"))
        model = data.get("model")
        resolved_model = self.settings.resolve_opencli_model(str(model) if model else None)
        unsupported = sorted(set(data.keys()) - SUPPORTED_OPENCLI_FLAGS)
        normalized = {
            "provider": "opencli",
            "model": model,
            "opencli_model": resolved_model,
            "customMode": custom_mode,
            "instrumental": bool(data.get("instrumental")),
            "prompt": str(data.get("prompt") or "").strip(),
            "title": str(data.get("title") or "").strip() or None,
            "style": str(data.get("style") or data.get("tags") or "").strip() or None,
            "negative_tags": str(data.get("negative_tags") or "").strip() or None,
            "styleWeight": self._float_or_none(data.get("styleWeight")),
            "weirdnessConstraint": self._float_or_none(data.get("weirdnessConstraint")),
            "audioWeight": self._float_or_none(data.get("audioWeight")),
            "generation_source": "opencli",
            "is_opencli_generation": True,
            "capabilities": local_only_capabilities(),
            "ignored_fields": unsupported,
            "requested_at": utc_now_naive().isoformat(),
        }
        if not normalized["prompt"] and not normalized["instrumental"]:
            raise OpenCliProviderError("OpenCLI benötigt einen Prompt/Lyrics-Text oder Instrumental=true.")
        if custom_mode and not normalized["instrumental"] and not normalized["prompt"]:
            raise OpenCliProviderError("OpenCLI-Custom-Mode benötigt Lyrics im Prompt-Feld.")
        return normalized

    def _assert_provider_ready(self) -> None:
        if not self.settings.suno_opencli_enabled:
            raise OpenCliProviderError("OpenCLI-Provider ist deaktiviert. Setze SUNO_OPENCLI_ENABLED=true und starte den Dienst neu.")
        if shutil.which(self.settings.suno_opencli_binary) is None:
            raise OpenCliProviderError(f"OpenCLI-Binary '{self.settings.suno_opencli_binary}' wurde nicht gefunden. Installation: npm i -g @jackwener/opencli")

    def _build_generate_command(self, payload: dict[str, Any], output_dir: Path) -> list[str]:
        command = ["generate"]
        prompt = str(payload.get("prompt") or "").strip()
        custom_mode = bool(payload.get("customMode"))
        instrumental = bool(payload.get("instrumental"))

        if custom_mode and prompt and not instrumental:
            command += ["--lyrics", prompt]
            if payload.get("style"):
                command += ["--tags", str(payload["style"])]
            if payload.get("negative_tags"):
                command += ["--negative-tags", str(payload["negative_tags"])]
        elif prompt:
            command.append(prompt)

        if payload.get("title"):
            command += ["--title", str(payload["title"])]
        if payload.get("opencli_model"):
            command += ["--model", str(payload["opencli_model"])]
        if payload.get("weirdnessConstraint") is not None:
            command += ["--weirdness", str(payload["weirdnessConstraint"])]
        if payload.get("styleWeight") is not None:
            command += ["--style-weight", str(payload["styleWeight"])]
        # Wichtig: Generieren und lokalen Download bewusst trennen.
        # Der direkte Generate-Download registrierte bei manchen OpenCLI-Versionen zusätzliche
        # temporäre/teilweise Dateien als leere Library-Varianten.
        if int(self.settings.suno_opencli_wait_timeout_seconds) > 0:
            command += ["--timeout", str(int(self.settings.suno_opencli_wait_timeout_seconds))]
        if instrumental:
            command += ["--instrumental"]
        if self.settings.suno_opencli_confirm_paid:
            command += ["--confirm-paid"]
        command += ["-f", "json"]
        return command

    def _run_opencli(self, command: list[str], *, timeout: int, stream: bool = False) -> Any:
        args = [self.settings.suno_opencli_binary, "suno", *command]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenCliProviderError(f"OpenCLI-Timeout nach {timeout}s bei {' '.join(args[:4])} …") from exc
        except FileNotFoundError as exc:
            raise OpenCliProviderError(f"OpenCLI-Binary '{self.settings.suno_opencli_binary}' ist nicht ausführbar.") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            hint = self._exit_hint(completed.returncode)
            message = f"opencli suno {command[0]} -> Exit {completed.returncode}. {hint}".strip()
            if stderr:
                message += f"\n{stderr[-4000:]}"
            raise OpenCliProviderError(message)
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"stdout": stdout, "stderr": stderr}

    def _download_generated_clips(self, result: Any, output_dir: Path) -> list[dict[str, Any]]:
        records = self._extract_clip_records(result)
        max_clips = max(1, int(self.settings.suno_opencli_max_imported_clips or 2))
        selected = records[:max_clips]
        downloads: list[dict[str, Any]] = []

        # Wenn OpenCLI bei einer Version trotz fehlender Clip-IDs direkt Dateien schreibt,
        # bleibt der Fallback über _select_primary_audio_files aktiv.
        if not selected:
            return downloads

        for index, record in enumerate(selected, start=1):
            clip_id = str(record.get("id") or "").strip()
            if not clip_id:
                continue
            clip_dir = (output_dir / f"clip_{index:02d}_{self._safe_path_token(clip_id)}").resolve()
            clip_dir.mkdir(parents=True, exist_ok=True)
            command = self._build_download_command(clip_id, clip_dir)
            try:
                download_result = self._run_opencli(
                    command,
                    timeout=int(self.settings.suno_opencli_timeout_seconds),
                    stream=False,
                )
                downloads.append({
                    "clip_id": clip_id,
                    "title": record.get("title"),
                    "status": "downloaded",
                    "command": command,
                    "result": download_result,
                    "output_dir": str(clip_dir),
                })
            except Exception as exc:
                downloads.append({
                    "clip_id": clip_id,
                    "title": record.get("title"),
                    "status": "failed",
                    "command": command,
                    "error": str(exc),
                    "output_dir": str(clip_dir),
                })

        if downloads and not any(item.get("status") == "downloaded" for item in downloads):
            errors = "; ".join(str(item.get("error") or item.get("clip_id"))[:300] for item in downloads)
            raise OpenCliProviderError(f"OpenCLI hat Clips erzeugt, aber der lokale Download ist fehlgeschlagen: {errors}")
        return downloads

    def _build_download_command(self, clip_id: str, output_dir: Path) -> list[str]:
        command = ["download", clip_id, "--output", str(output_dir)]
        if self.settings.opencli_formats_list:
            command += ["--formats", ",".join(self.settings.opencli_formats_list)]
        if self.settings.suno_opencli_confirm_paid:
            command += ["--confirm-paid"]
        command += ["-f", "json"]
        return command

    def _output_dir_for_task(self, task: SunoTask) -> Path:
        root = self.settings.audio_storage_path.resolve()
        output = (root / "opencli" / f"task_{task.id}").resolve()
        output.relative_to(root)
        return output

    def _result_payload(self, result: Any, output_dir: Path, *, download_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        metadata_files = self._collect_metadata_files(output_dir)
        return {
            "source": "opencli",
            "provider": "opencli",
            "generation_source": "opencli",
            "is_opencli_generation": True,
            "capabilities": local_only_capabilities(),
            "raw_result": result,
            "download_results": download_results or [],
            "output_dir": str(output_dir),
            "files": [self._file_info(path) for path in self._iter_output_files(output_dir)],
            "audio_candidates": [self._file_info(item["path"]) | {"duration_seconds": item.get("duration_seconds")} for item in self._collect_audio_candidates(output_dir)],
            "metadata_files": metadata_files,
        }

    def _create_song(self, task: SunoTask, request_payload: dict[str, Any], output_dir: Path) -> Song:
        result_payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        metadata_files = result_payload.get("metadata_files") if isinstance(result_payload.get("metadata_files"), list) else []
        first_meta = metadata_files[0] if metadata_files and isinstance(metadata_files[0], dict) else {}
        title = request_payload.get("title") or first_meta.get("title") or self._extract_value(result_payload.get("raw_result"), ("title", "name", "songTitle")) or "OpenCLI Song"
        lyrics = request_payload.get("prompt") if request_payload.get("customMode") and not request_payload.get("instrumental") else None
        prompt = request_payload.get("prompt") or lyrics
        now_iso = utc_now_naive().isoformat()
        project = AudioProject(
            title=str(title),
            description="Über OpenCLI generiertes Song-Projekt",
            status="active",
            metadata_json={"source": "opencli", "task_local_id": task.id, "created_at": now_iso},
        )
        self.db.add(project)
        self.db.flush()
        cover_url = self._first_public_cover_url(output_dir)
        if cover_url:
            project.cover_image_url = cover_url
        song = Song(
            title=str(title),
            model=str(request_payload.get("model") or request_payload.get("opencli_model") or "opencli"),
            prompt=prompt,
            lyrics=lyrics,
            cover_image_url=cover_url,
            task_id=task.task_id,
            project_id=project.id,
            metadata_json=mark_opencli_generation({
                "source": "opencli",
                "provider": "opencli",
                "request_payload": request_payload,
                "response_payload": task.response_payload,
                "result_payload": task.result_payload,
                "opencli": {
                    "output_dir": str(output_dir),
                    "generated_at": now_iso,
                },
            }),
        )
        self.db.add(song)
        self.db.flush()
        project.final_audio_asset_id = None
        self.db.flush()
        return song

    def _register_generated_files(self, task: SunoTask, song: Song, output_dir: Path) -> list[AudioAsset]:
        candidates = self._select_primary_audio_files(output_dir)
        if not candidates:
            return []

        cover_url = self._first_public_cover_url(output_dir)
        assets: list[AudioAsset] = []
        for index, candidate in enumerate(candidates, start=1):
            path = candidate["path"]
            duration = candidate.get("duration_seconds")
            if path.stat().st_size > self.settings.audio_max_download_bytes:
                raise OpenCliProviderError(f"OpenCLI-Datei ist größer als erlaubt: {path.name}")
            digest = candidate.get("checksum_sha256") or self._sha256_file(path)
            duplicate = self.db.query(AudioAsset).filter(
                AudioAsset.checksum_sha256 == digest,
                AudioAsset.status == "cached",
                AudioAsset.is_deleted.is_(False),
            ).first()
            if duplicate:
                asset = AudioAsset(
                    task_local_id=task.id,
                    song_id=song.id,
                    suno_task_id=task.task_id,
                    audio_id=f"{task.task_id}-{index}",
                    title=song.title,
                    display_title=song.title,
                    image_url=cover_url or duplicate.image_url,
                    source_url=duplicate.source_url or duplicate.public_url or self._public_url_for_audio_file(path),
                    local_path=duplicate.local_path,
                    public_url=duplicate.public_url,
                    filename=duplicate.filename,
                    content_type=duplicate.content_type,
                    file_size_bytes=duplicate.file_size_bytes,
                    duration_seconds=duplicate.duration_seconds or (int(duration) if duration else None),
                    checksum_sha256=digest,
                    status="cached",
                    metadata_json=self._asset_metadata(task, song, path, index, duplicate=True),
                    project_id=song.project_id,
                    operation_label="OpenCLI",
                    version_label=f"OpenCLI {index}",
                    is_final=index == 1,
                )
            else:
                public_url = self._public_url_for_audio_file(path)
                content_type = normalize_audio_content_type(mimetypes.guess_type(path.name)[0], path)
                asset = AudioAsset(
                    task_local_id=task.id,
                    song_id=song.id,
                    suno_task_id=task.task_id,
                    audio_id=f"{task.task_id}-{index}",
                    title=song.title,
                    display_title=song.title,
                    image_url=cover_url,
                    source_url=public_url,
                    local_path=to_portable_path(path, storage_root=self.settings.audio_storage_path),
                    public_url=public_url,
                    filename=path.name,
                    content_type=content_type,
                    file_size_bytes=path.stat().st_size,
                    duration_seconds=int(duration) if duration else None,
                    checksum_sha256=digest,
                    status="cached",
                    metadata_json=self._asset_metadata(task, song, path, index),
                    project_id=song.project_id,
                    operation_label="OpenCLI",
                    version_label=f"OpenCLI {index}",
                    is_final=index == 1,
                )
            self.db.add(asset)
            self.db.flush()
            assets.append(asset)
            if index == 1:
                song.audio_url = asset.public_url
                if song.project_id:
                    project = self.db.query(AudioProject).filter(AudioProject.id == song.project_id).first()
                    if project:
                        project.final_audio_asset_id = asset.id
        if cover_url and not song.cover_image_url:
            song.cover_image_url = cover_url
        self.db.flush()
        return assets

    def _asset_metadata(self, task: SunoTask, song: Song, path: Path, index: int, *, duplicate: bool = False) -> dict[str, Any]:
        request_payload = task.request_payload if isinstance(task.request_payload, dict) else {}
        return mark_opencli_generation({
            "source": "opencli",
            "provider": "opencli",
            "operation": "OpenCLI",
            "candidate": {
                "id": f"{task.task_id}-{index}",
                "audio_id": f"{task.task_id}-{index}",
                "title": song.title,
                "prompt": request_payload.get("prompt"),
                "lyrics": request_payload.get("prompt") if request_payload.get("customMode") and not request_payload.get("instrumental") else None,
                "text": request_payload.get("prompt") if request_payload.get("customMode") and not request_payload.get("instrumental") else None,
                "style": request_payload.get("style"),
                "tags": request_payload.get("style"),
                "model": request_payload.get("model"),
                "opencli_model": request_payload.get("opencli_model"),
                "sourceAudioUrl": self._public_url_for_audio_file(path),
                "source_audio_url": self._public_url_for_audio_file(path),
            },
            "request_payload": request_payload,
            "opencli": {
                "task_local_id": task.id,
                "task_id": task.task_id,
                "local_path": to_portable_path(path, storage_root=self.settings.audio_storage_path),
                "public_url": self._public_url_for_audio_file(path),
                "duplicate_reused": duplicate,
                "registered_at": utc_now_naive().isoformat(),
            },
        })

    def _mark_task_running(self, task: SunoTask) -> StatusNotification:
        now = utc_now_naive()
        task.status = "RUNNING"
        task.started_at = task.started_at or now
        task.heartbeat_at = now
        task.progress = max(0, int(task.progress or 0))
        task.updated_at = now
        notification = StatusNotification(
            event_type="opencli_generation_started",
            title="OpenCLI-Generierung gestartet",
            message=f"{(task.request_payload or {}).get('title') or 'Neuer Song'} · opencli suno generate läuft lokal.",
            severity="info",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task",
            content_id=task.id,
            target_tab="status",
            target_payload={"task_local_id": task.id, "provider": "opencli", "status": "RUNNING"},
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        self.db.refresh(task)
        return notification

    def _mark_notification_done(self, notification: StatusNotification | None) -> None:
        if not notification:
            return
        notification.status = "done"
        notification.completed_at = utc_now_naive()
        self.db.add(notification)

    def _create_completed_notification(self, task: SunoTask, song: Song, assets: list[AudioAsset]) -> None:
        first_asset = assets[0] if assets else None
        self.db.add(StatusNotification(
            event_type="opencli_generation_completed",
            title="OpenCLI-Song ist fertig",
            message=f"{song.title or 'Song'} · {len(assets)} lokale Audiodatei(en) importiert.",
            severity="success",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="audio" if first_asset else "song",
            content_id=first_asset.id if first_asset else song.id,
            target_tab="library",
            target_payload={
                "task_local_id": task.id,
                "suno_task_id": task.task_id,
                "provider": "opencli",
                "song_id": song.id,
                "audio_asset_id": first_asset.id if first_asset else None,
                "audio_asset_ids": [asset.id for asset in assets],
                "status": "SUCCESS",
            },
        ))

    def _create_failed_notification(self, task: SunoTask, error: str) -> None:
        self.db.add(StatusNotification(
            event_type="opencli_generation_failed",
            title="OpenCLI-Generierung fehlgeschlagen",
            message=error[:1000],
            severity="error",
            status="unread",
            task_local_id=task.id,
            suno_task_id=task.task_id,
            content_type="task",
            content_id=task.id,
            target_tab="status",
            target_payload={"task_local_id": task.id, "provider": "opencli", "status": "FAILED"},
        ))

    def _collect_audio_candidates(self, output_dir: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self._iter_output_files(output_dir):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            if path.name.lower().endswith((".part", ".tmp", ".download")):
                continue
            size = path.stat().st_size
            if size <= 64 * 1024:
                continue
            duration = read_audio_duration_seconds(path)
            digest = self._sha256_file(path)
            rows.append({
                "path": path,
                "size": size,
                "duration_seconds": float(duration) if duration else None,
                "checksum_sha256": digest,
                "format_rank": self._format_rank(path),
            })
        return rows

    def _select_primary_audio_files(self, output_dir: Path) -> list[dict[str, Any]]:
        candidates = self._collect_audio_candidates(output_dir)
        if not candidates:
            return []

        # Primär nur abspielbare Dateien importieren. Falls ffprobe/ffmpeg fehlt und daher
        # keine Dauer ermittelt werden kann, nutzen wir einen Größen-Fallback, importieren aber
        # weiterhin nur die begrenzte Anzahl erwarteter Suno-Clips.
        playable = [item for item in candidates if (item.get("duration_seconds") or 0) >= 5]
        pool = playable or [item for item in candidates if int(item.get("size") or 0) >= 256 * 1024]

        by_checksum: dict[str, dict[str, Any]] = {}
        for item in pool:
            digest = str(item.get("checksum_sha256") or "")
            if not digest:
                continue
            current = by_checksum.get(digest)
            if not current or self._candidate_sort_key(item) < self._candidate_sort_key(current):
                by_checksum[digest] = item

        unique = list(by_checksum.values())
        unique.sort(key=self._candidate_sort_key)
        max_clips = max(1, int(self.settings.suno_opencli_max_imported_clips or 2))
        return unique[:max_clips]

    def _extract_clip_records(self, value: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        id_keys = ("clip_id", "clipId", "audio_id", "audioId", "id")
        media_keys = (
            "audio_url", "audioUrl", "source_audio_url", "sourceAudioUrl", "stream_url",
            "download_url", "downloadUrl", "url", "video_url", "image_url", "duration",
            "duration_seconds", "title", "name", "status", "state",
        )

        def score_record(node: dict[str, Any]) -> int:
            score = 0
            for key in media_keys:
                if key in node and node.get(key) not in (None, ""):
                    score += 1
            if any(isinstance(node.get(key), str) and node.get(key).strip() for key in ("audio_url", "audioUrl", "source_audio_url", "sourceAudioUrl", "stream_url", "download_url", "downloadUrl")):
                score += 10
            status = str(node.get("status") or node.get("state") or "").lower()
            if status in {"complete", "completed", "succeeded", "success", "ready", "done"}:
                score += 3
            return score

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                raw_id = None
                for key in id_keys:
                    candidate = node.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        raw_id = candidate.strip()
                        break
                if raw_id and raw_id not in seen and not raw_id.startswith("opencli-"):
                    score = score_record(node)
                    # Parent-/Request-IDs ohne Medienkontext werden bewusst ignoriert,
                    # damit nicht die falsche ID an `opencli suno download` übergeben wird.
                    if score > 0:
                        seen.add(raw_id)
                        records.append({
                            "id": raw_id,
                            "title": str(node.get("title") or node.get("name") or node.get("songTitle") or "") or None,
                            "status": str(node.get("status") or node.get("state") or "") or None,
                            "score": score,
                        })
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        if not records:
            def collect_string_ids(node: Any) -> None:
                if isinstance(node, str):
                    candidate = node.strip()
                    if 8 <= len(candidate) <= 128 and "/" not in candidate and " " not in candidate and candidate not in seen:
                        seen.add(candidate)
                        records.append({"id": candidate, "title": None, "status": None, "score": 0})
                elif isinstance(node, dict):
                    for child in node.values():
                        collect_string_ids(child)
                elif isinstance(node, list):
                    for child in node:
                        collect_string_ids(child)
            collect_string_ids(value)
        records.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("title") or ""), str(item.get("id") or "")))
        max_clips = max(1, int(self.settings.suno_opencli_max_imported_clips or 2))
        return records[:max_clips]

    @staticmethod
    def _candidate_sort_key(item: dict[str, Any]) -> tuple[int, str]:
        path = item["path"]
        duration = item.get("duration_seconds") or 0
        # Längere echte Songs vor kurzen Artefakten, bevorzugtes Format vor Zusatzformat.
        return (-int(duration), OpenCliProviderService._format_rank(path), path.name.lower())

    @staticmethod
    def _format_rank(path: Path) -> int:
        return {".mp3": 0, ".m4a": 1, ".wav": 2, ".flac": 3, ".aac": 4, ".ogg": 5}.get(path.suffix.lower(), 9)

    @staticmethod
    def _safe_path_token(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip())
        return cleaned[:80] or "clip"

    def _iter_output_files(self, output_dir: Path) -> list[Path]:
        if not output_dir.exists():
            return []
        root = self.settings.audio_storage_path.resolve()
        files: list[Path] = []
        for path in output_dir.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            files.append(resolved)
        return sorted(files, key=lambda item: item.as_posix().lower())

    def _collect_metadata_files(self, output_dir: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self._iter_output_files(output_dir):
            if path.suffix.lower() not in METADATA_EXTENSIONS:
                continue
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
            elif isinstance(parsed, list):
                rows.extend([item for item in parsed if isinstance(item, dict)])
        return rows[:20]

    def _first_public_cover_url(self, output_dir: Path) -> str | None:
        cover_file = self._first_cover_file(output_dir)
        if not cover_file:
            return None
        cached_url = self._cache_local_cover_file(cover_file)
        return cached_url or self._public_url_for_audio_file(cover_file)

    def _first_cover_file(self, output_dir: Path) -> Path | None:
        for path in self._iter_output_files(output_dir):
            if path.suffix.lower() in COVER_EXTENSIONS and path.stat().st_size > 0:
                return path
        return None

    def _cache_local_cover_file(self, path: Path) -> str | None:
        try:
            source = path.resolve()
            if source.suffix.lower() not in COVER_EXTENSIONS or source.stat().st_size <= 0:
                return None
            root = self.settings.cover_storage_path.resolve()
            root.mkdir(parents=True, exist_ok=True)
            digest = self._sha256_file(source)
            suffix = source.suffix.lower() if source.suffix.lower() in COVER_EXTENSIONS else '.jpg'
            safe_stem = self._safe_path_token(source.stem)[:48]
            target = (root / f"opencli_{digest[:16]}_{safe_stem}{suffix}").resolve()
            target.relative_to(root)
            if not target.exists() or target.stat().st_size <= 0:
                shutil.copy2(source, target)
            relative = target.relative_to(root).as_posix()
            return f"{self.settings.suno_cover_public_route.rstrip('/')}/{quote(relative, safe='/')}"
        except Exception:
            return None

    def _public_url_for_audio_file(self, path: Path) -> str:
        root = self.settings.audio_storage_path.resolve()
        relative = path.resolve().relative_to(root).as_posix()
        return f"{self.settings.suno_audio_public_route.rstrip('/')}/{quote(relative, safe="/")}"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _file_info(path: Path) -> dict[str, Any]:
        return {"name": path.name, "path": str(path), "size": path.stat().st_size, "suffix": path.suffix.lower()}

    @staticmethod
    def _safe_command_summary(command: list[str]) -> list[str]:
        result: list[str] = []
        skip_next = False
        sensitive_value_flags = {"--lyrics"}
        for index, item in enumerate(command):
            if skip_next:
                skip_next = False
                continue
            if item in sensitive_value_flags and index + 1 < len(command):
                result.extend([item, f"<text:{len(command[index + 1])} chars>"])
                skip_next = True
            elif index == 1 and command and command[0] == "generate" and not item.startswith("-"):
                result.append(f"<prompt:{len(item)} chars>")
            else:
                result.append(item)
        return result

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed < 0 or parsed > 1:
            return None
        return parsed

    @staticmethod
    def _extract_value(value: Any, keys: tuple[str, ...]) -> str | None:
        if isinstance(value, dict):
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            for child in value.values():
                found = OpenCliProviderService._extract_value(child, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = OpenCliProviderService._extract_value(child, keys)
                if found:
                    return found
        return None

    @staticmethod
    def _exit_hint(code: int) -> str:
        return {
            66: "Leeres Ergebnis.",
            69: "Browser-Bridge nicht erreichbar. Prüfe Extension/Daemon mit opencli doctor.",
            75: "OpenCLI-Timeout. Erhöhe SUNO_OPENCLI_WAIT_TIMEOUT_SECONDS.",
            77: "Nicht eingeloggt. Führe opencli suno login aus.",
            78: "OpenCLI-Konfigurationsfehler.",
        }.get(code, "")


def run_opencli_generation_background(task_id: int) -> None:
    db = SessionLocal()
    try:
        OpenCliProviderService(db).run_generation_task(task_id)
    finally:
        db.close()
