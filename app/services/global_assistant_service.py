from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AiAssistantProfile, AiAssistantProfileFile, AiInstructionFile, VocalTag
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.services.assistant_action_registry import (
    CANVAS_ACTION_PROMPTS,
    clone_action,
    default_actions_for_page as registry_default_actions_for_page,
    detect_action_by_keywords,
    normalize_actions,
)


SUNO_STYLE_LYRICS_MAX_LENGTH = 5000
SUNO_STYLE_PROMPT_MAX_LENGTH = 1000
SUNO_STYLE_PROMPT_TARGET_LENGTH = 940
SUNO_STYLE_ARRANGEMENT_MAX_LENGTH = 220
SUNO_STYLE_DEFAULT_BPM = 100
SUNO_STYLE_MIN_BPM = 40
SUNO_STYLE_MAX_BPM = 240
STYLE_BATCH_MODES = {"auto", "batch", "chunked", "single"}

SUNO_STYLE_DOCUMENTATION_REFERENCE = {
    "source": "SunoAI Master-Dokumentation + Vocal-Tag-Baukasten, Stand 2026-06",
    "style_prompt_architecture": [
        "Style-Feld und Lyrics-Feld strikt trennen: Style-Feld = globales Klangfundament; Lyrics-Metatags = Abschnittslogik und lokale Vocal-Steuerung.",
        "Style-Prompt in dieser Priorität bauen: Hauptgenre/Ära, Stimmung, Hauptinstrumente, Vocal-Charakter, Produktion/Textur, Tempo/BPM.",
        "Die wichtigsten Genre- und Klangbegriffe stehen in den ersten 20 bis 30 Wörtern.",
        "4 bis 7 starke Kern-Deskriptoren sind besser als widersprüchliche Keyword-Ketten; danach erst kompakte Details für Drums, Bass, Hook, Textur und Mix.",
        "Negative Tags gehören in negative_tags, nicht in Lyrics-Metatags und nicht als Widerspruch ins style-Feld.",
    ],
    "professional_formula": [
        "Präzise Metatags + Persona/Vocal-Charakter + hohe Style-Treue + moderate Weirdness + strategische Exclude Styles.",
        "BPM immer als feste ganze Zahl nennen, z. B. 170 BPM. Niemals Bereiche wie 167-172 BPM und niemals fehlende BPM.",
        "Energie, Sprache/Dialekt, Vocal-Delivery und Produktionsästhetik immer konkret nennen.",
        "Arrangement nur als kurzer roter Faden: Intro, Verse, Chorus/Hook, Bridge/Breakdown, Outro.",
    ],
    "lyric_vocal_tag_formula": [
        "Nutze Doppelpunkt-Syntax: [SECTION: voice identity, vocal texture, delivery style, emotion/attitude, energy, language/accent, vocal production].",
        "Pro Abschnitt nur eine Tag-Zeile; Originaltext wird nicht neu geschrieben.",
        "Verse, Chorus und Bridge unterschiedlich taggen, damit Dynamik entsteht.",
        "Chorus/Hook darf kräftiger sein als Verse; Bridge darf kontrastieren; Outro darf Fade/Dub/Echo enthalten.",
        "Tags in englischer Steuer-Syntax formulieren; Sprache/Dialekt explizit setzen, wenn Aussprache wichtig ist.",
        "Keine Instrumentenlisten als lyric_vocal_tags; dort nur Stimme, Timbre, Delivery, Emotion, Energie, Sprache/Akzent und sparsame Vocal-FX.",
    ],
    "avoid": [
        "Keine direkten Künstler-Imitationen.",
        "Keine widersprüchlichen Energy-Tags wie low energy und explosive energy im selben Abschnitt.",
        "Keine überladenen Tags mit mehr als 6 Deskriptoren pro Abschnitt.",
        "Keine Style-Prompts, Instrumentenlisten oder Sound-Pack-Rezepte in lyric_vocal_tags.",
    ],
}

SUNO_VOCAL_TAG_RECIPE_REFERENCE = {
    "jamaican_patois_dancehall": {
        "intro": "[Intro: sound system toaster, Jamaican Patois adlibs, crowd response]",
        "verse": "[Verse: gritty male vocals, dancehall toaster, defiant, high energy, native Jamaican Patois]",
        "chorus": "[Chorus: catchy patois hook, melodic singjay, layered harmonies, party energy]",
        "bridge": "[Bridge: spoken Jamaican Patois, smoky male voice, stripped back]",
        "outro": "[Outro: dub echo, fading patois adlibs, crowd chant]",
    },
    "grimy_boom_bap": {
        "intro": "[Intro: spoken male narrator, gritty street tone]",
        "verse": "[Verse: raspy male rapper, punchy boom bap flow, defiant, medium energy]",
        "chorus": "[Chorus: shouted hook, doubled vocals, gritty, high energy]",
        "bridge": "[Bridge: spoken word, smoky voice, reflective]",
        "outro": "[Outro: low spoken voice, vinyl crackle, fade out]",
    },
    "cyber_dark_rap": {
        "intro": "[Intro: robotic spoken male narrator, low filtered voice, ominous]",
        "verse": "[Verse: gritty male vocals, rapid-fire rap flow, defiant, high energy, robotic voice filter]",
        "chorus": "[Chorus: shouted hook, doubled vocals, call-and-response, explosive energy]",
        "bridge": "[Bridge: distorted vocals, glitchy, building intensity]",
        "outro": "[Outro: fading robotic vocals, dub echo, digital decay]",
    },
    "emotional_pop_rap": {
        "intro": "[Intro: low intimate male vocals, cinematic]",
        "verse": "[Verse: breathy male vocals, vulnerable, intimate, medium energy]",
        "chorus": "[Chorus: powerful male vocals, emotional, layered harmonies, high energy]",
        "bridge": "[Bridge: vulnerable falsetto, echoing softly, low energy]",
        "outro": "[Outro: fading vocals, soft harmonies, nostalgic]",
    },
    "trap_drill": {
        "intro": "[Intro: whispered vocals, ominous, low energy]",
        "verse": "[Verse: dark male vocals, syncopated trap flow, menacing, high energy]",
        "chorus": "[Chorus: auto-tuned male vocals, hypnotic hook, high energy]",
        "bridge": "[Bridge: whispered vocals, stripped back, rising tension]",
        "outro": "[Outro: filtered vocals, delay, fade out]",
    },
}

GLOBAL_ASSISTANT_SYSTEM_INSTRUCTION = """
Du bist der globale KI-Assistent innerhalb einer Suno-/Songwriting-Web-App.
Deine Aufgabe ist nicht nur Regeln anzubieten, sondern aktiv mitzudenken, Absichten zu erkennen und kreative Arbeit zu leisten.
Arbeite extrem einfach, verständlich und schrittweise. Der Nutzer soll keine technischen Begriffe kennen müssen.
Nutze den App-Kontext intelligent: aktuelle Seite, vorhandener Canvas, Projektstatus und verfügbare Aktionen.
Wenn der Nutzer etwas Kreatives verlangt, zum Beispiel Songtext erstellen, Hook schreiben, Text verbessern, Style finden oder Suno-Prompt bauen, erledige diese Aufgabe direkt.
Wenn Informationen fehlen, triff eine sinnvolle Annahme und schreibe trotzdem einen brauchbaren ersten Vorschlag. Frage nur dann nach, wenn ohne Antwort kein sinnvoller Fortschritt möglich ist.
Canvas-Arbeit ist nur erlaubt, wenn der aktuelle Aufruf ausdrücklich als Canvas-Vorschau/Ausführung gekennzeichnet ist. Bei normalen Chatfragen lieferst du Inhalt im Chat und setzt canvas_text auf null.
Für Songtexte: liefere bei Canvas-Arbeit immer eine vollständige, direkt nutzbare Canvas-Vorschau mit klaren Sections wie [Intro], [Verse 1], [Hook], [Verse 2], [Bridge], [Outro].
Für Instrumental-Baupläne: liefere bei Canvas-Arbeit ausschließlich Timecode-/Arrangement-/Sounddesign-Abschnitte, keine Lyrics.
Für Änderungen am Canvas: verändere nicht direkt dauerhaft, sondern liefere eine Vorschau zum Übernehmen oder Verwerfen.
Du darfst über erlaubte App-Aktionen arbeiten, aber nicht behaupten, eine Aktion sei ausgeführt, wenn du sie nur vorschlägst.
Antworte kurz, direkt und auf Deutsch. Keine internen IDs erklären. Keine technischen Rohdaten anzeigen. Gib niemals rohes JSON im Chattext aus.
Wenn du Songtext oder Instrumental-Bauplan als Canvas erzeugst oder änderst, muss der vollständige Inhalt ausschließlich im Feld canvas_text landen. assistant_message enthält nur eine kurze, menschliche Erklärung.
Du musst Vocal Tags verstehen, ergänzen und ändern können. Wenn der Nutzer Chorus, Hook, Refrain, Verse 3, Strophe 3, Bridge oder Intro nennt, bearbeite gezielt genau diese Sektion und lasse andere Sektionen möglichst unverändert.
""".strip()


@dataclass
class AssistantResult:
    reply: str
    suggested_actions: list[dict[str, Any]]
    proposed_canvas: str | None = None
    change_summary: str | None = None
    context_summary: str | None = None
    runtime_info: dict[str, Any] | None = None


CREATIVE_KEYWORDS = {
    "erstelle", "erstellen", "schreib", "schreibe", "generiere", "mach", "mache", "bau", "baue",
    "verbessere", "überarbeite", "formatiere", "entwickle", "komponiere", "text", "songtext",
    "lyrics", "hook", "chorus", "verse", "refrain", "strophe", "bridge", "intro", "outro", "suno", "prompt", "style", "stil", "vocal", "tag", "tags", "bauplan", "instrumental",
}

HELP_ONLY_PATTERNS = (
    "was ist der nächste schritt",
    "nächster schritt",
    "hilf mir hier",
    "was kann ich hier",
    "erklär",
    "erklaer",
    "wo bin ich",
    "was soll ich tun",
)

CANVAS_EXECUTION_PATTERNS = (
    "canvas",
    "übernehmen",
    "uebernehmen",
    "einfügen",
    "einfuegen",
    "ersetze",
    "ändere",
    "aendere",
    "mach die hook",
    "mach den text",
    "mach den songtext",
    "suno-ready",
    "suno ready",
    "formatiere",
    "überarbeite",
    "ueberarbeite",
    "verbessere",
)


class GlobalAssistantService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _trim_text(self, value: Any, limit: int, *, marker: str = "… gekürzt") -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if limit <= 0 or len(text) <= limit:
            return text
        head = int(limit * 0.62)
        tail = max(200, limit - head - 80)
        return f"{text[:head].rstrip()}\n\n{marker} ({len(text)} Zeichen insgesamt)\n\n{text[-tail:].lstrip()}"

    def _normalize_work_mode(self, value: Any) -> str:
        normalized = str(value or "lyrics").strip().lower().replace("-", "_")
        if normalized in {"instrumental", "instrumental_blueprint", "blueprint", "sound_blueprint", "sounds"}:
            return "instrumental_blueprint"
        return "lyrics"

    def _resolve_work_mode(self, app_context: dict[str, Any]) -> str:
        return self._normalize_work_mode(
            app_context.get("current_studio_mode")
            or app_context.get("studio_mode")
            or app_context.get("work_mode")
            or app_context.get("mode")
        )

    def _budget_canvas(self, app_context: dict[str, Any], *, allow_canvas_changes: bool) -> str:
        canvas = str(app_context.get("current_canvas") or "")
        return self._trim_text(canvas, 20000 if allow_canvas_changes else 4000)

    def _budget_instruction_files(self, instruction_files: list[dict[str, Any]], *, allow_canvas_changes: bool) -> list[dict[str, str]]:
        limit_per_file = 8000 if allow_canvas_changes else 3000
        max_files = 6 if allow_canvas_changes else 3
        result: list[dict[str, str]] = []
        for row in instruction_files[:max_files]:
            result.append({
                "title": self._trim_text(row.get("title"), 180),
                "description": self._trim_text(row.get("description"), 500),
                "content": self._trim_text(row.get("content"), limit_per_file),
            })
        return result

    def _budget_vocal_tags(self, vocal_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tag in vocal_tags[:120]:
            result.append({
                "label": self._trim_text(tag.get("label"), 80),
                "tag": self._trim_text(tag.get("tag"), 140),
                "category": self._trim_text(tag.get("category"), 80),
                "description": self._trim_text(tag.get("description"), 240),
            })
        return result

    def _budget_history(self, history: list[dict[str, Any]] | None, *, allow_canvas_changes: bool) -> list[dict[str, str]]:
        max_rows = 12 if allow_canvas_changes else 8
        max_chars = 2200 if allow_canvas_changes else 1200
        rows: list[dict[str, str]] = []
        for item in (history or [])[-max_rows:]:
            role = "user" if str(item.get("role") or "").startswith("user") else "assistant"
            content = self._trim_text(item.get("content") or item.get("text") or "", max_chars)
            if content:
                rows.append({"role": role, "content": content})
        return rows

    def _available_actions(self, app_context: dict[str, Any], active_tab: str) -> list[dict[str, Any]]:
        context_actions = normalize_actions(app_context.get("available_actions") if isinstance(app_context, dict) else None)
        return context_actions or self.default_actions_for_page(active_tab)

    def build_context_summary(self, app_context: dict[str, Any]) -> str:
        page = app_context.get("page_label") or app_context.get("active_tab") or "unbekannt"
        route = app_context.get("route") or app_context.get("active_tab") or "unbekannt"
        project = app_context.get("current_project_title") or app_context.get("current_project_id") or "kein Projekt ausgewählt"
        canvas = app_context.get("current_canvas") or ""
        assets_count = app_context.get("assets_count", 0)
        lyrics_count = app_context.get("lyrics_count", 0)
        workflow = app_context.get("workflow_step") or "kein aktiver Schritt"
        work_mode = "Instrumental-Bauplan" if self._resolve_work_mode(app_context) == "instrumental_blueprint" else "Songtext"
        return f"Seite: {page} ({route}); Modus: {work_mode}; Projekt: {project}; Canvas-Länge: {len(canvas)} Zeichen; Audios: {assets_count}; Songtexte: {lyrics_count}; Workflow: {workflow}"

    def default_actions_for_page(self, active_tab: str | None) -> list[dict[str, Any]]:
        return registry_default_actions_for_page(active_tab)

    def is_create_lyrics_intent(self, message: str) -> bool:
        text = (message or "").lower()
        create_words = ("erstelle", "erstellen", "schreib", "schreibe", "generiere", "mach", "mache", "bau", "baue")
        lyrics_words = ("songtext", "lyrics", "text", "hook", "refrain", "verse", "strophe", "bauplan", "instrumental")
        return any(word in text for word in create_words) and any(word in text for word in lyrics_words)

    def is_creative_request(self, message: str) -> bool:
        text = (message or "").lower().strip()
        if not text:
            return False
        if any(pattern in text for pattern in HELP_ONLY_PATTERNS) and not self.is_create_lyrics_intent(text):
            return False
        return any(keyword in text for keyword in CREATIVE_KEYWORDS)

    def detect_action(self, message: str, active_tab: str | None) -> str | None:
        text = (message or "").lower()
        if self.is_create_lyrics_intent(text):
            return "lyrics_create_new"
        return detect_action_by_keywords(message, active_tab)

    def simple_help_reply(self, message: str, app_context: dict[str, Any], actions: list[dict[str, Any]]) -> str:
        active_tab = str(app_context.get("active_tab") or "home")
        page = app_context.get("page_label") or active_tab
        if not message.strip():
            return f"Ich bin bereit. Du bist gerade im Bereich „{page}“. Sag mir normal, was du möchtest — ich kann helfen, schreiben, prüfen oder dich zum passenden Schritt führen."
        if active_tab == "lyrics":
            mode = self._resolve_work_mode(app_context)
            if mode == "instrumental_blueprint":
                return "Ich sehe, dass du am Instrumental-Bauplan arbeitest. Du kannst mir direkt sagen: „Erstelle einen Bauplan“, „Mach den Aufbau Suno-ready“ oder „Verstärke das Sounddesign“."
            return "Ich sehe, dass du am Songtext arbeitest. Du kannst mir direkt sagen: „Erstelle einen neuen Songtext“, „Mach die Hook stärker“ oder „Mach den Text Suno-ready“."
        if active_tab == "library":
            return "Ich sehe deine Library. Ich kann dir helfen, den neuesten Song zu öffnen, einen Text weiterzubearbeiten, eine DAW-Version vorzubereiten oder ein Projekt zu exportieren."
        if active_tab == "music":
            return "Ich sehe den Musikbereich. Ich kann dich durch den Song-Wizard führen oder direkt einen passenden Songtext/Suno-Prompt vorbereiten."
        if active_tab == "admin":
            return "Du bist im Adminbereich. Hier kannst du KI-Profile, Prompt-Bausteine und globale Anweisungen pflegen, damit der Assistent später gezielter arbeitet."
        return "Sag mir einfach, was du machen möchtest. Ich erkenne den aktuellen Bereich und kann direkt helfen, statt nur Menüs zu erklären."

    def get_profile_context(self, db: Session, profile_id: int | None) -> tuple[str | None, list[dict[str, str]], dict[str, Any]]:
        profile = None
        if profile_id:
            profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == profile_id, AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
        if not profile:
            try:
                from app.routers.admin import get_ai_admin_settings
                default_id = get_ai_admin_settings(db).get("default_assistant_profile_id")
                if default_id:
                    profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == default_id, AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
            except Exception:
                profile = None
        if not profile:
            return None, [], {}
        links = db.query(AiAssistantProfileFile).filter(AiAssistantProfileFile.profile_id == profile.id, AiAssistantProfileFile.is_active.is_(True)).order_by(AiAssistantProfileFile.sort_order.asc(), AiAssistantProfileFile.id.asc()).all()
        file_ids = [link.file_id for link in links]
        instruction_files: list[dict[str, str]] = []
        if file_ids:
            rows = db.query(AiInstructionFile).filter(AiInstructionFile.id.in_(file_ids), AiInstructionFile.is_deleted.is_(False), AiInstructionFile.is_active.is_(True)).all()
            row_map = {row.id: row for row in rows}
            for file_id in file_ids:
                row = row_map.get(file_id)
                if row:
                    instruction_files.append({"title": row.title, "description": row.description or "", "content": row.content})
        parts = []
        if profile.system_instruction:
            parts.append(profile.system_instruction)
        if profile.response_format_instruction:
            parts.append("Antwort-/Formatvorgaben:\n" + profile.response_format_instruction)
        return "\n\n".join(parts).strip() or None, instruction_files, {"profile_id": profile.id, "profile_name": profile.name, "provider": profile.provider, "model": profile.model, "temperature": profile.temperature, "max_output_tokens": profile.max_output_tokens}

    def _get_ai_runtime(self, db: Session, profile_id: int | None) -> tuple[str, str, str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        from app.routers.admin import get_ai_admin_settings

        admin_settings = get_ai_admin_settings(db)
        profile_instruction, instruction_files, profile_options = self.get_profile_context(db, profile_id)
        system_parts = [GLOBAL_ASSISTANT_SYSTEM_INSTRUCTION, admin_settings.get("system_instruction") or ""]
        if profile_instruction:
            system_parts.append(profile_instruction)
        system_instruction = "\n\n".join(part.strip() for part in system_parts if part and part.strip())
        vocal_tags = [
            {"label": tag.label, "tag": tag.tag, "category": tag.category, "description": tag.description}
            for tag in db.query(VocalTag).filter(VocalTag.is_deleted.is_(False), VocalTag.is_active.is_(True)).order_by(VocalTag.category.asc(), VocalTag.sort_order.asc(), VocalTag.label.asc()).all()
        ]
        provider = profile_options.get("provider") or admin_settings.get("default_provider") or self.settings.ai_default_provider
        model = profile_options.get("model") or admin_settings.get("default_model") or self.settings.ai_default_model
        return provider, model, system_instruction, vocal_tags, instruction_files, profile_options

    def get_runtime_info(self, db: Session, profile_id: int | None = None) -> dict[str, Any]:
        provider, model, _system_instruction, vocal_tags, instruction_files, profile_options = self._get_ai_runtime(db, profile_id)
        has_profile = bool(profile_options.get("profile_id"))
        return {
            "provider": provider,
            "model": model,
            "profile_id": profile_options.get("profile_id"),
            "profile_name": profile_options.get("profile_name") or ("Admin-Standardprofil" if has_profile else None),
            "temperature": profile_options.get("temperature"),
            "max_output_tokens": profile_options.get("max_output_tokens"),
            "instruction_files_count": len(instruction_files),
            "vocal_tags_count": len(vocal_tags),
            "source": "assistant_profile" if has_profile else "admin_defaults",
        }

    def _normalize_style_suggestions(self, payload: dict[str, Any], amount: int) -> list[dict[str, Any]]:
        source = payload.get("suggestions") if isinstance(payload, dict) else None
        if not isinstance(source, list):
            source = payload.get("styles") if isinstance(payload, dict) else None
        if not isinstance(source, list):
            source = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(source, list):
            source = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(source, dict):
            source = [source]
        if not isinstance(source, list):
            source = []

        if not source and isinstance(payload, dict):
            single_style = payload.get("style") or payload.get("prompt") or payload.get("suno_style") or payload.get("sunoStyle")
            if isinstance(single_style, str) and single_style.strip():
                source = [payload]

        suggestions: list[dict[str, Any]] = []
        for index, item in enumerate(source, start=1):
            normalized = self._normalize_style_item(item, index=index)
            if not normalized:
                continue
            suggestions.append(normalized)
            if len(suggestions) >= amount:
                break

        if not suggestions and isinstance(payload, dict):
            text = payload.get("assistant_message") or payload.get("message") or payload.get("raw_text")
            extracted = self._extract_style_suggestions_from_text(str(text or ""), amount)
            suggestions = []
            for index, item in enumerate(extracted, start=1):
                normalized = self._normalize_style_item(item, index=index)
                if normalized:
                    suggestions.append(normalized)
                if len(suggestions) >= amount:
                    break

        return suggestions

    def _normalize_style_item(self, item: Any, *, index: int = 1, fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
        fallback = fallback or {}
        if isinstance(item, str):
            title = fallback.get("title") or f"KI-Style {index}"
            style = item.strip()
            reason = fallback.get("reason") or "Direkt aus dem Songtext abgeleiteter Suno-Style."
            raw: dict[str, Any] = {}
        elif isinstance(item, dict):
            raw = item
            title = str(raw.get("title") or raw.get("name") or fallback.get("title") or f"KI-Style {index}").strip()
            style = str(raw.get("style") or raw.get("prompt") or raw.get("suno_style") or raw.get("sunoStyle") or fallback.get("style") or "").strip()
            reason = str(raw.get("reason") or raw.get("begründung") or raw.get("description") or fallback.get("reason") or "").strip()
        else:
            return None

        if not style:
            return None

        raw_bpm = raw.get("bpm") or raw.get("tempo") or fallback.get("bpm") or ""
        suggested_song_title = (
            raw.get("suggested_song_title")
            or raw.get("suggestedSongTitle")
            or raw.get("song_title")
            or raw.get("songTitle")
            or raw.get("recommended_title")
            or raw.get("recommendedTitle")
            or fallback.get("suggested_song_title")
            or ""
        )
        fixed_bpm = self._normalize_bpm_value(
            raw_bpm,
            style,
            fallback.get("style"),
            title,
            reason,
            raw.get("energy") or raw.get("mood") or fallback.get("energy") or "",
            raw.get("vocal_delivery") or raw.get("vocals") or raw.get("voice") or fallback.get("vocal_delivery") or "",
        )
        style = self._normalize_bpm_mentions_in_text(style, fixed_bpm)

        normalized: dict[str, Any] = {
            "title": self._limit_text(title, 120) or f"KI-Style {index}",
            "suggested_song_title": self._limit_text(suggested_song_title, 120) or None,
            "style": self._limit_text(style, 1600),
            "reason": self._limit_text(reason, 600) or "Passt laut KI-Analyse zu Songtext, Stimmung, Delivery und Suno-Zielrichtung.",
            "bpm": fixed_bpm,
            "key_hint": self._limit_text(raw.get("key_hint") or raw.get("key") or fallback.get("key_hint") or "", 120) or None,
            "energy": self._limit_text(raw.get("energy") or raw.get("mood") or fallback.get("energy") or "", 160) or None,
            "vocal_delivery": self._limit_text(raw.get("vocal_delivery") or raw.get("vocals") or raw.get("voice") or fallback.get("vocal_delivery") or "", 300) or None,
            "instruments": self._normalize_instruments(raw.get("instruments") or raw.get("instrumente") or fallback.get("instruments")),
            "arrangement": self._normalize_arrangement(raw.get("arrangement") or raw.get("sections") or fallback.get("arrangement")),
            "negative_tags": self._normalize_negative_tags(raw.get("negative_tags") or raw.get("negativeTags") or raw.get("avoid") or fallback.get("negative_tags")),
            "lyric_vocal_tags": self._normalize_lyric_vocal_tags(
                raw.get("lyric_vocal_tags")
                or raw.get("lyrics_vocal_tags")
                or raw.get("songtext_vocal_tags")
                or raw.get("songtextTags")
                or raw.get("vocal_tags_for_lyrics")
                or raw.get("vocal_tags")
                or fallback.get("lyric_vocal_tags")
            ),
            "scores": self._normalize_scores(raw.get("scores") or raw.get("score") or fallback.get("scores")),
            "role": self._limit_text(raw.get("role") or raw.get("rolle") or fallback.get("role") or "", 120) or None,
        }
        normalized["style"] = self._build_master_style_prompt(normalized)
        return normalized

    def _build_master_style_prompt(self, item: dict[str, Any]) -> str:
        """Build one Suno-ready master style prompt from structured style fields.

        The UI may still keep instruments/arrangement/scores for explanation, but the
        generated style field must be complete enough to paste directly into Suno.
        This prevents a split workflow where important instrument or arrangement
        instructions are visible in cards but missing from the actual generation field.
        """
        parts: list[str] = []
        bpm = self._normalize_bpm_value(
            item.get("bpm"),
            item.get("style"),
            item.get("title"),
            item.get("energy"),
            item.get("vocal_delivery"),
        )
        base_style = self._normalize_bpm_mentions_in_text(
            self._limit_text(item.get("style") or "", 1600),
            bpm,
        )
        base_style = self._limit_style_prompt(base_style, SUNO_STYLE_PROMPT_MAX_LENGTH)
        if base_style:
            parts.append(base_style.rstrip(" .;,"))

        energy = self._limit_text(item.get("energy") or "", 160)
        vocal_delivery = self._limit_text(item.get("vocal_delivery") or "", 300)
        key_hint = self._limit_text(item.get("key_hint") or "", 120)
        if bpm and not self._style_prompt_has_fixed_bpm(base_style):
            parts.append(f"tempo {bpm} BPM")
        if energy and energy.lower() not in base_style.lower():
            parts.append(f"energy and mood: {energy}")
        if key_hint and key_hint.lower() not in base_style.lower():
            parts.append(f"key/mode hint: {key_hint}")
        if vocal_delivery and vocal_delivery.lower() not in base_style.lower():
            parts.append(f"vocal delivery: {vocal_delivery}")

        instruments = item.get("instruments") if isinstance(item.get("instruments"), list) else []
        instrument_phrases: list[str] = []
        for instrument in instruments[:7]:
            if isinstance(instrument, dict):
                name = self._limit_text(instrument.get("name") or instrument.get("instrument") or "", 80)
                role = self._limit_text(instrument.get("role") or "", 50)
                if name:
                    instrument_phrases.append(f"{role} {name}".strip())
            else:
                name = self._limit_text(instrument, 80)
                if name:
                    instrument_phrases.append(name)
        if instrument_phrases:
            instrument_text = ", ".join(dict.fromkeys(instrument_phrases))
            if instrument_text.lower() not in base_style.lower():
                parts.append(f"instrumentation: {instrument_text}")

        arrangement = item.get("arrangement") if isinstance(item.get("arrangement"), list) else []
        arrangement_phrases: list[str] = []
        for section in arrangement[:4]:
            if isinstance(section, dict):
                label = self._limit_text(section.get("section") or section.get("part") or "", 50)
                idea = self._limit_text(section.get("idea") or section.get("description") or section.get("text") or "", 120)
                if idea:
                    arrangement_phrases.append(f"{label}: {idea}" if label else idea)
            else:
                idea = self._limit_text(section, 120)
                if idea:
                    arrangement_phrases.append(idea)
        if arrangement_phrases:
            arrangement_text = "; ".join(arrangement_phrases)
            if arrangement_text.lower() not in base_style.lower():
                parts.append(f"arrangement: {arrangement_text}")

        master = self._ensure_style_prompt_has_fixed_bpm("; ".join(part for part in parts if part).strip(" ;"), bpm)
        if len(master) <= SUNO_STYLE_PROMPT_MAX_LENGTH:
            return master or base_style

        # SunoAPI accepts only a limited style field. Keep the actual style as the
        # single master prompt, but compress it before it reaches the generation form.
        # Preserve the AI's complete style field first; older logic reduced the base
        # style to 560 chars even when it was already a valid Suno prompt.
        if len(base_style) >= 720:
            return self._ensure_style_prompt_has_fixed_bpm(base_style, bpm)

        compact_parts: list[str] = []
        if base_style:
            compact_parts.append(self._limit_style_prompt(base_style, 720).rstrip(" .;,"))
        compact_instruments = ", ".join(dict.fromkeys(instrument_phrases[:6]))
        if compact_instruments:
            compact_parts.append(f"instrumentation: {self._limit_text(compact_instruments, 260)}")
        if vocal_delivery and vocal_delivery.lower() not in base_style.lower():
            compact_parts.append(f"vocals: {self._limit_text(vocal_delivery, 160)}")
        if energy and energy.lower() not in base_style.lower():
            compact_parts.append(f"energy: {self._limit_text(energy, 90)}")
        compact_arrangement = "; ".join(arrangement_phrases[:3])
        if compact_arrangement:
            compact_parts.append(f"arrangement: {self._limit_text(compact_arrangement, SUNO_STYLE_ARRANGEMENT_MAX_LENGTH)}")
        compact = self._ensure_style_prompt_has_fixed_bpm("; ".join(part for part in compact_parts if part).strip(" ;"), bpm)
        return self._limit_style_prompt(compact, SUNO_STYLE_PROMPT_MAX_LENGTH) or self._limit_style_prompt(master, SUNO_STYLE_PROMPT_MAX_LENGTH) or base_style

    def _is_valid_bpm(self, value: int | None) -> bool:
        return value is not None and SUNO_STYLE_MIN_BPM <= value <= SUNO_STYLE_MAX_BPM

    def _parse_bpm_candidate(self, first: str | int | None, second: str | int | None = None) -> int | None:
        try:
            first_int = int(str(first or "").strip())
        except ValueError:
            return None
        if not self._is_valid_bpm(first_int):
            return None
        if second is None or str(second).strip() == "":
            return first_int
        try:
            second_int = int(str(second or "").strip())
        except ValueError:
            return first_int
        if not self._is_valid_bpm(second_int):
            return first_int
        return int(((first_int + second_int) / 2) + 0.5)

    def _extract_bpm_from_text(self, value: Any, *, strict: bool = True) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None

        marker_patterns = (
            r"(?i)\b(?:tempo|bpm)\s*[:=]?\s*(?:ca\.?|circa|about|around|approx(?:\.|imately)?)?\s*(\d{2,3})\s*(?:[-–—]|to|bis)\s*(\d{2,3})\s*(?:bpm)?\b",
            r"(?i)\b(?:ca\.?|circa|about|around|approx(?:\.|imately)?)\s*(\d{2,3})\s*(?:[-–—]|to|bis)\s*(\d{2,3})\s*bpm\b",
            r"(?i)(?<!\d)(\d{2,3})\s*(?:[-–—]|to|bis)\s*(\d{2,3})\s*bpm\b",
            r"(?i)\b(?:tempo|bpm)\s*[:=]?\s*(?:ca\.?|circa|about|around|approx(?:\.|imately)?)?\s*(\d{2,3})\s*(?:bpm)?\b",
            r"(?i)\b(?:ca\.?|circa|about|around|approx(?:\.|imately)?)\s*(\d{2,3})\s*bpm\b",
            r"(?i)(?<!\d)(\d{2,3})\s*bpm\b",
        )
        for pattern in marker_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                bpm = self._parse_bpm_candidate(groups[0], groups[1] if len(groups) > 1 else None)
                if bpm is not None:
                    return bpm

        if strict:
            return None

        free_patterns = (
            r"(?<!\d)(\d{2,3})\s*(?:[-–—]|to|bis)\s*(\d{2,3})(?!\d)",
            r"(?<!\d)(\d{2,3})(?!\d)",
        )
        for pattern in free_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                bpm = self._parse_bpm_candidate(groups[0], groups[1] if len(groups) > 1 else None)
                if bpm is not None:
                    return bpm
        return None

    def _infer_default_bpm(self, *values: Any) -> int:
        text = " ".join(str(value or "") for value in values).lower()
        if re.search(r"\b(double[- ]?time|ultra[- ]?fast|rapid[- ]?fire|frantic|jungle|drum\s*(?:and|&)\s*bass|dnb|breakcore)\b", text):
            return 170
        if re.search(r"\b(uk\s*garage|garage|2[- ]?step)\b", text):
            return 132
        if re.search(r"\b(techno|hard techno|industrial techno)\b", text):
            return 130
        if re.search(r"\b(deep house|house|club house|dance)\b", text):
            return 124
        if re.search(r"\b(drill)\b", text):
            return 142
        if re.search(r"\b(trap)\b", text):
            return 140
        if re.search(r"\b(dancehall|ragga|toasting|patois)\b", text):
            return 96
        if re.search(r"\b(reggae|dub)\b", text):
            return 78
        if re.search(r"\b(boom\s*bap|boombap|nyc rap|hip[- ]?hop|rap)\b", text):
            return 96
        if re.search(r"\b(synthwave|80s|new wave)\b", text):
            return 92
        if re.search(r"\b(r&b|rnb|soul)\b", text):
            return 88
        if re.search(r"\b(ballad|slow jam|acoustic)\b", text):
            return 72
        if re.search(r"\b(rock|metal|punk)\b", text):
            return 120
        return SUNO_STYLE_DEFAULT_BPM

    def _normalize_bpm_value(self, *values: Any) -> str:
        for index, value in enumerate(values):
            bpm = self._extract_bpm_from_text(value, strict=index != 0)
            if bpm is not None:
                return str(bpm)
        return str(self._infer_default_bpm(*values))

    def _normalize_bpm_range(self, bpm_min: Any = None, bpm_max: Any = None) -> tuple[int, int] | None:
        min_empty = bpm_min is None or str(bpm_min).strip() == ""
        max_empty = bpm_max is None or str(bpm_max).strip() == ""
        if min_empty and max_empty:
            return None
        if min_empty or max_empty:
            raise ValueError("BPM-Eingrenzung benötigt immer Von- und Bis-Wert.")
        try:
            lower = int(str(bpm_min).strip())
            upper = int(str(bpm_max).strip())
        except ValueError as exc:
            raise ValueError("BPM-Eingrenzung muss aus ganzen Zahlen bestehen.") from exc
        if not self._is_valid_bpm(lower) or not self._is_valid_bpm(upper):
            raise ValueError(f"BPM-Eingrenzung muss zwischen {SUNO_STYLE_MIN_BPM} und {SUNO_STYLE_MAX_BPM} liegen.")
        if lower > upper:
            raise ValueError("BPM-Eingrenzung ist ungültig: Von darf nicht größer als Bis sein.")
        return lower, upper

    def _coerce_bpm_to_range(self, value: Any, bpm_range: tuple[int, int], *context: Any) -> str:
        bpm = self._extract_bpm_from_text(value, strict=False)
        if bpm is None:
            bpm = self._infer_default_bpm(value, *context)
        lower, upper = bpm_range
        return str(max(lower, min(upper, bpm)))

    def _apply_bpm_range_to_suggestions(self, suggestions: list[dict[str, Any]], bpm_range: tuple[int, int] | None) -> None:
        if not bpm_range:
            return
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            fixed_bpm = self._coerce_bpm_to_range(
                suggestion.get("bpm"),
                bpm_range,
                suggestion.get("style"),
                suggestion.get("title"),
                suggestion.get("reason"),
                suggestion.get("energy"),
                suggestion.get("vocal_delivery"),
            )
            suggestion["bpm"] = fixed_bpm
            suggestion["style"] = self._force_style_prompt_bpm(suggestion.get("style") or "", fixed_bpm)

    def _force_style_prompt_bpm(self, value: Any, bpm: str | int | None) -> str:
        text = self._normalize_bpm_mentions_in_text(value, bpm)
        fixed = str(bpm or "").strip()
        if not text or not fixed:
            return text
        text = re.sub(
            r"(?i)\b(?P<prefix>(?:tempo\s*[:=]?\s*)?)\d{2,3}\s*bpm\b",
            lambda match: f"{match.group('prefix') or ''}{fixed} BPM",
            text,
        )
        text = re.sub(
            r"(?i)\bbpm\s*[:=]\s*\d{2,3}\b",
            f"BPM: {fixed}",
            text,
        )
        if not self._style_prompt_has_fixed_bpm(text):
            text = f"{text.rstrip(' .;,')}; tempo {fixed} BPM" if text else f"tempo {fixed} BPM"
        return re.sub(r"\s+", " ", text).strip()

    def _normalize_bpm_mentions_in_text(self, value: Any, bpm: str | int | None) -> str:
        text = str(value or "").strip()
        fixed = str(bpm or "").strip()
        if not text or not fixed:
            return text
        fixed_phrase = f"{fixed} BPM"

        def replace_range(match: re.Match[str]) -> str:
            prefix = match.group("prefix") or ""
            return f"{prefix}{fixed_phrase}"

        text = re.sub(
            r"(?i)\b(?P<prefix>(?:tempo\s*[:=]?\s*)?)(?:ca\.?|circa|about|around|approx(?:\.|imately)?)?\s*(?P<a>\d{2,3})\s*(?:[-–—]|to|bis)\s*(?P<b>\d{2,3})\s*bpm\b",
            replace_range,
            text,
        )
        text = re.sub(
            r"(?i)\bbpm\s*[:=]\s*(?:ca\.?|circa|about|around|approx(?:\.|imately)?)?\s*\d{2,3}\s*(?:[-–—]|to|bis)\s*\d{2,3}\b",
            f"BPM: {fixed}",
            text,
        )
        text = re.sub(
            r"(?i)\b(?:ca\.?|circa|about|around|approx(?:\.|imately)?)\s*\d{2,3}\s*bpm\b",
            fixed_phrase,
            text,
        )
        return re.sub(r"\s+", " ", text).strip()

    def _style_prompt_has_fixed_bpm(self, value: Any) -> bool:
        return self._extract_bpm_from_text(value, strict=True) is not None

    def _ensure_style_prompt_has_fixed_bpm(self, value: Any, bpm: str | int | None) -> str:
        text = self._normalize_bpm_mentions_in_text(value, bpm)
        fixed = str(bpm or "").strip()
        if not fixed:
            return self._limit_style_prompt(text, SUNO_STYLE_PROMPT_MAX_LENGTH)
        if self._style_prompt_has_fixed_bpm(text):
            return self._limit_style_prompt(text, SUNO_STYLE_PROMPT_MAX_LENGTH)
        addition = f"tempo {fixed} BPM"
        if not text:
            return addition
        separator = "; " if text else ""
        if len(text) + len(separator) + len(addition) <= SUNO_STYLE_PROMPT_MAX_LENGTH:
            return f"{text}{separator}{addition}"
        reserve = len(separator) + len(addition)
        return f"{self._limit_style_prompt(text, max(0, SUNO_STYLE_PROMPT_MAX_LENGTH - reserve)).rstrip(' .;,')}{separator}{addition}"

    def _limit_text(self, value: Any, max_length: int) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) > max_length:
            return text[:max_length].rstrip()
        return text

    def _limit_style_prompt(self, value: Any, max_length: int = SUNO_STYLE_PROMPT_MAX_LENGTH) -> str:
        text = re.sub(r"\s+", " ", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
        if len(text) <= max_length:
            return text
        clipped = text[:max_length].rstrip()
        soft_min = int(max_length * 0.72)
        breakpoints = [
            clipped.rfind("; "),
            clipped.rfind(". "),
            clipped.rfind(", "),
            clipped.rfind(" | "),
            clipped.rfind(" - "),
        ]
        soft_break = max(breakpoints)
        if soft_break >= soft_min:
            clipped = clipped[:soft_break]
        else:
            space_break = clipped.rfind(" ")
            if space_break >= soft_min:
                clipped = clipped[:space_break]
        return clipped.strip(" ,;.-|")

    def _normalize_instruments(self, value: Any, max_items: int = 10) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
        elif isinstance(value, list):
            items = value
        else:
            return []
        result: list[dict[str, str]] = []
        for item in items:
            if len(result) >= max_items:
                break
            if isinstance(item, dict):
                name = self._limit_text(item.get("name") or item.get("instrument") or item.get("label") or "", 120)
                role = self._limit_text(item.get("role") or item.get("category") or "", 80)
                reason = self._limit_text(item.get("reason") or item.get("why") or item.get("beschreibung") or "", 180)
            else:
                name = self._limit_text(item, 120)
                role = ""
                reason = ""
            if not name:
                continue
            entry = {"name": name}
            if role:
                entry["role"] = role
            if reason:
                entry["reason"] = reason
            result.append(entry)
        return result

    def _normalize_arrangement(self, value: Any, max_items: int = 8) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [part.strip() for part in re.split(r"\n+|;", value) if part.strip()]
        elif isinstance(value, list):
            items = value
        else:
            return []
        result: list[dict[str, str]] = []
        for index, item in enumerate(items, start=1):
            if len(result) >= max_items:
                break
            if isinstance(item, dict):
                section = self._limit_text(item.get("section") or item.get("part") or item.get("name") or f"Abschnitt {index}", 80)
                idea = self._limit_text(item.get("idea") or item.get("description") or item.get("beschreibung") or item.get("text") or "", 240)
            else:
                section = f"Abschnitt {index}"
                idea = self._limit_text(item, 240)
            if not idea:
                continue
            result.append({"section": section or f"Abschnitt {index}", "idea": idea})
        return result

    def _normalize_lyric_vocal_tags(self, value: Any, max_items: int = 8) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [part.strip() for part in re.split(r"\n+", value) if part.strip()]
        elif isinstance(value, list):
            raw_items = value
        elif isinstance(value, dict):
            raw_items = []
            for section, tag in value.items():
                if isinstance(tag, dict):
                    raw_items.append({"section": section, **tag})
                else:
                    raw_items.append({"section": section, "tag": tag})
        else:
            return []

        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(raw_items, start=1):
            if len(result) >= max_items:
                break
            if isinstance(item, dict):
                section = self._limit_text(
                    item.get("section")
                    or item.get("part")
                    or item.get("name")
                    or item.get("abschnitt")
                    or f"Section {index}",
                    80,
                )
                tag = self._limit_text(
                    item.get("tag")
                    or item.get("vocal_tag")
                    or item.get("vocalTag")
                    or item.get("text")
                    or item.get("value")
                    or "",
                    260,
                )
                reason = self._limit_text(item.get("reason") or item.get("why") or item.get("beschreibung") or "", 220)
            else:
                line = self._limit_text(item, 340)
                section = f"Section {index}"
                tag = line
                reason = ""
                if ":" in line and not line.lstrip().startswith("["):
                    possible_section, possible_tag = line.split(":", 1)
                    if possible_tag.strip():
                        section = self._limit_text(possible_section, 80)
                        tag = self._limit_text(possible_tag, 260)
            tag = self._normalize_single_vocal_tag(tag)
            section = section.strip(" []|:-") or f"Section {index}"
            if not tag:
                continue
            key = (section.lower(), tag.lower())
            if key in seen:
                continue
            seen.add(key)
            entry = {"section": section, "tag": tag}
            if reason:
                entry["reason"] = reason
            result.append(entry)
        return result

    def _normalize_single_vocal_tag(self, value: Any) -> str:
        tag = self._limit_text(value, 260)
        if not tag:
            return ""
        tag = re.sub(r"\s+", " ", tag).strip()
        if not tag.startswith("["):
            tag = f"[{tag.strip(' []')}]"
        return self._normalize_vocal_tag_formula(tag)

    def _normalize_vocal_tag_formula(self, value: Any) -> str:
        tag = self._limit_text(value, 260)
        if not tag:
            return ""
        tag = re.sub(r"\s+", " ", tag).strip()
        inner = tag.strip().strip("[]").strip()
        if not inner:
            return ""

        # Die ältere Pipe-Form bleibt importfähig, wird aber für neue Ausgaben in die
        # stabilere Suno-Doppelpunkt-Syntax aus dem Vocal-Baukasten normalisiert.
        if "|" in inner and ":" not in inner.split("|", 1)[0]:
            parts = [part.strip(" ,;|/-") for part in inner.split("|") if part.strip(" ,;|/-")]
            if len(parts) >= 2:
                section = parts[0]
                descriptors = ", ".join(parts[1:])
                inner = f"{section}: {descriptors}"

        inner = re.sub(r"\s*,\s*", ", ", inner)
        inner = re.sub(r"\s*:\s*", ": ", inner, count=1)
        inner = re.sub(r"\s+", " ", inner).strip(" ,;")
        return f"[{inner}]" if inner else ""

    def _clean_section_descriptor(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^\s*[\[(]", "", text)
        text = re.sub(r"[\])]\s*$", "", text)
        text = text.split(":", 1)[0].split("|", 1)[0]
        text = text.lower()
        text = re.sub(r"[^a-zäöüß0-9 ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _freeform_lyric_section_meta(self, value: Any) -> dict[str, str] | None:
        text = self._clean_section_descriptor(re.sub(r"[\[\]()]+", " ", str(value or "")))
        if not text:
            return None
        typed_number_match = re.search(
            r"\b(?:verse|strophe|part|hook|chorus|refrain|bridge|breakdown|break|drop|pre chorus|prechorus|post chorus|postchorus)\s*(\d{1,2})\b",
            text,
        )
        number_match = typed_number_match or re.search(r"\b(\d{1,2})\b", text)
        number = number_match.group(1) if number_match else ""
        if re.search(r"\b(intro|einleitung)\b", text):
            return {"base": "intro", "key": "intro", "label": "Intro"}
        if re.search(r"\b(verse|strophe|part)\b", text):
            return {"base": "verse", "key": f"verse-{number}" if number else "verse", "label": f"Verse {number}" if number else "Verse"}
        if re.search(r"\b(pre chorus|prechorus|pre refrain)\b", text):
            return {"base": "pre-chorus", "key": f"pre-chorus-{number}" if number else "pre-chorus", "label": f"Pre-Chorus {number}" if number else "Pre-Chorus"}
        if re.search(r"\b(post chorus|postchorus)\b", text):
            return {"base": "post-chorus", "key": f"post-chorus-{number}" if number else "post-chorus", "label": f"Post-Chorus {number}" if number else "Post-Chorus"}
        if re.search(r"\b(hook|chorus|refrain)\b", text):
            return {"base": "chorus", "key": f"chorus-{number}" if number else "chorus", "label": f"Chorus {number}" if number else "Chorus"}
        if re.search(r"\b(bridge|breakdown|break)\b", text):
            return {"base": "bridge", "key": f"bridge-{number}" if number else "bridge", "label": f"Bridge {number}" if number else "Bridge"}
        if re.search(r"\b(drop)\b", text):
            return {"base": "drop", "key": f"drop-{number}" if number else "drop", "label": f"Drop {number}" if number else "Drop"}
        if re.search(r"\b(outro|ende|finale)\b", text):
            return {"base": "outro", "key": "outro", "label": "Outro"}
        if re.search(r"\b(adlib|adlibs)\b", text):
            return {"base": "adlibs", "key": "adlibs", "label": "Adlibs"}
        return None

    def _lyric_section_meta(self, value: Any) -> dict[str, str] | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if not (re.match(r"^\[[^\]]+\]$", raw) or re.match(r"^\([^)]+\)$", raw)):
            return None
        text = self._clean_section_descriptor(raw)
        if not text:
            return None
        number_match = re.search(r"\b(\d{1,2})\b", text)
        number = number_match.group(1) if number_match else ""

        if re.search(r"\b(intro|einleitung)\b", text):
            return {"base": "intro", "key": "intro", "label": "Intro"}
        if re.search(r"\b(verse|strophe|part)\b", text):
            return {"base": "verse", "key": f"verse-{number}" if number else "verse", "label": f"Verse {number}" if number else "Verse"}
        if re.search(r"\b(pre chorus|prechorus|pre refrain)\b", text):
            return {"base": "pre-chorus", "key": f"pre-chorus-{number}" if number else "pre-chorus", "label": f"Pre-Chorus {number}" if number else "Pre-Chorus"}
        if re.search(r"\b(post chorus|postchorus)\b", text):
            return {"base": "post-chorus", "key": f"post-chorus-{number}" if number else "post-chorus", "label": f"Post-Chorus {number}" if number else "Post-Chorus"}
        if re.search(r"\b(hook|chorus|refrain)\b", text):
            return {"base": "chorus", "key": f"chorus-{number}" if number else "chorus", "label": f"Chorus {number}" if number else "Chorus"}
        if re.search(r"\b(bridge|breakdown|break)\b", text):
            return {"base": "bridge", "key": f"bridge-{number}" if number else "bridge", "label": f"Bridge {number}" if number else "Bridge"}
        if re.search(r"\b(drop)\b", text):
            return {"base": "drop", "key": f"drop-{number}" if number else "drop", "label": f"Drop {number}" if number else "Drop"}
        if re.search(r"\b(outro|ende|finale)\b", text):
            return {"base": "outro", "key": "outro", "label": "Outro"}
        if re.search(r"\b(adlib|adlibs)\b", text):
            return {"base": "adlibs", "key": "adlibs", "label": "Adlibs"}
        return None

    def _lyric_section_key(self, value: Any) -> str:
        meta = self._freeform_lyric_section_meta(value)
        return meta["key"] if meta else "section"

    def _lyric_section_base_key(self, value: Any) -> str:
        meta = self._freeform_lyric_section_meta(value)
        return meta["base"] if meta else self._lyric_section_key(value)

    def _detect_lyric_sections(self, lyrics: str) -> list[str]:
        wanted_sections: list[str] = []
        seen_keys: set[str] = set()
        for line in str(lyrics or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            meta = self._lyric_section_meta(line.strip())
            if not meta:
                continue
            key = meta["key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            wanted_sections.append(meta["label"])
        if not wanted_sections:
            wanted_sections = ["Intro", "Verse", "Chorus", "Bridge", "Outro"]
        return wanted_sections

    def _detect_vocal_recipe_key(self, lyrics: str, style_context: str = "") -> str:
        haystack = f"{lyrics or ''}\n{style_context or ''}".lower()
        if any(token in haystack for token in ("patois", "patwa", "jamaican", "dancehall", "reggae", "ragga", "toasting", "singjay", "sound system")):
            return "jamaican_patois_dancehall"
        if any(token in haystack for token in ("cyber", "robotic", "virus", "glitch", "computer", "machine", "digital", "firewall", "system")):
            return "cyber_dark_rap"
        if any(token in haystack for token in ("boom bap", "boombap", "nyc", "grimy", "dusty", "vinyl", "mpc")):
            return "grimy_boom_bap"
        if any(token in haystack for token in ("trap", "drill", "808", "menacing", "dark trap")):
            return "trap_drill"
        if any(token in haystack for token in ("emotional", "melancholic", "heartbreak", "ballad", "vulnerable", "piano", "soul")):
            return "emotional_pop_rap"
        return "grimy_boom_bap"

    def _blend_recipe_tag(self, recipe_key: str, section: str, base_tag: str, style_context: str = "") -> str:
        haystack = f"{style_context or ''}".lower()
        tag = base_tag
        if recipe_key == "jamaican_patois_dancehall" and any(token in haystack for token in ("cyber", "robotic", "glitch", "virus", "computer", "firewall", "system")):
            cyber_additions = {
                "intro": "robotic voice filter",
                "verse": "rapid-fire rap flow",
                "chorus": "shouted call-and-response",
                "bridge": "glitchy, rising tension",
                "outro": "robotic voice filter",
            }
            addition = cyber_additions.get(section)
            if addition and addition.lower() not in tag.lower():
                tag = tag.rstrip("]") + f", {addition}]"
        if any(token in haystack for token in ("funny", "comedic", "comic", "humor", "humour", "schelmisch")) and section == "verse":
            if "comedic" not in tag.lower():
                tag = tag.rstrip("]") + ", comedic rap delivery]"
        if any(token in haystack for token in ("aggressive", "hard", "druck", "tense", "dark")) and section in {"verse", "chorus"}:
            if "aggressive" not in tag.lower() and "defiant" not in tag.lower():
                tag = tag.rstrip("]") + ", defiant]"
        return self._normalize_single_vocal_tag(tag)

    def _fallback_lyric_vocal_tags(self, lyrics: str, available_vocal_tags: list[dict[str, Any]], max_items: int = 6, style_context: str = "") -> list[dict[str, str]]:
        wanted_sections = self._detect_lyric_sections(lyrics)
        recipe_key = self._detect_vocal_recipe_key(lyrics, style_context)
        recipe = SUNO_VOCAL_TAG_RECIPE_REFERENCE.get(recipe_key, SUNO_VOCAL_TAG_RECIPE_REFERENCE["grimy_boom_bap"])

        result: list[dict[str, str]] = []
        used_keys: set[str] = set()
        for section in wanted_sections:
            if len(result) >= max_items:
                break
            key = self._lyric_section_key(section)
            base_key = self._lyric_section_base_key(section)
            tag = recipe.get(base_key) or recipe.get("verse")
            if not tag:
                continue
            normalized_tag = self._blend_recipe_tag(recipe_key, base_key, tag, style_context)
            if not normalized_tag or key in used_keys:
                continue
            used_keys.add(key)
            result.append({
                "section": section.capitalize(),
                "tag": normalized_tag,
                "reason": "Dokumentationsbasierter Fallback aus SunoAI Master-Dokumentation und Vocal-Tag-Baukasten.",
            })

        if len(result) >= min(max_items, 3) or not available_vocal_tags:
            return result[:max_items]

        # Ergänzung aus den in der App gepflegten Vocal-Tags, falls eine Installation
        # bereits eigene Tags führt und die Dokumentationsrezepte weniger Abschnitte abdecken.
        indexed_tags = list(enumerate(available_vocal_tags))
        used_tag_indexes: set[int] = set()
        for section in wanted_sections:
            if len(result) >= max_items:
                break
            key = self._lyric_section_key(section)
            base_key = self._lyric_section_base_key(section)
            if key in used_keys:
                continue
            selected: tuple[int, dict[str, Any]] | None = None
            for tag_index, row in indexed_tags:
                if tag_index in used_tag_indexes:
                    continue
                haystack = f"{row.get('category') or ''} {row.get('label') or ''} {row.get('tag') or ''}".lower()
                if key in haystack or base_key in haystack or (base_key == "chorus" and "hook" in haystack):
                    selected = (tag_index, row)
                    break
            if not selected:
                continue
            selected_index, selected_row = selected
            used_tag_indexes.add(selected_index)
            tag = self._normalize_single_vocal_tag(selected_row.get("tag") or selected_row.get("label") or "")
            if not tag:
                continue
            used_keys.add(key)
            result.append({
                "section": section.capitalize(),
                "tag": tag,
                "reason": "Ergänzung aus aktiven Vocal-Tags der App.",
            })
        return result[:max_items]

    def _enhance_lyric_vocal_tags(self, lyrics: str, suggestion: dict[str, Any], available_vocal_tags: list[dict[str, Any]], max_items: int = 6) -> list[dict[str, str]]:
        style_context = " ".join(str(suggestion.get(key) or "") for key in ("style", "energy", "vocal_delivery", "negative_tags", "role", "title"))
        existing = self._normalize_lyric_vocal_tags(suggestion.get("lyric_vocal_tags"), max_items=max_items)
        fallback = self._fallback_lyric_vocal_tags(lyrics, available_vocal_tags, max_items=max_items, style_context=style_context)

        merged: list[dict[str, str]] = []
        used_keys: set[str] = set()
        for source_item in existing + fallback:
            tag = self._normalize_single_vocal_tag(source_item.get("tag") or "")
            if not tag:
                continue
            key = self._lyric_section_key(f"{source_item.get('section') or ''} {tag}")
            if key in used_keys:
                continue
            used_keys.add(key)
            entry = {
                "section": self._limit_text(source_item.get("section") or key.capitalize(), 80) or key.capitalize(),
                "tag": tag,
            }
            reason = self._limit_text(source_item.get("reason") or "", 220)
            if reason:
                entry["reason"] = reason
            merged.append(entry)
            if len(merged) >= max_items:
                break
        return merged

    def _normalize_negative_tags(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        return self._limit_text(text, 500) or None

    def _normalize_scores(self, value: Any) -> dict[str, float | None] | None:
        if not isinstance(value, dict):
            return None
        aliases = {
            "fit": ["fit", "match", "passung"],
            "hook_potential": ["hook_potential", "hook", "hookPotential"],
            "suno_clarity": ["suno_clarity", "clarity", "sunoClarity", "klarheit"],
            "risk": ["risk", "risiko"],
        }
        result: dict[str, float | None] = {}
        for key, candidates in aliases.items():
            raw = None
            for candidate in candidates:
                if candidate in value:
                    raw = value.get(candidate)
                    break
            if raw is None or raw == "":
                result[key] = None
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                result[key] = None
                continue
            if number > 1 and number <= 100:
                number = number / 100
            result[key] = round(max(0.0, min(1.0, number)), 2)
        return result if any(v is not None for v in result.values()) else None

    def _normalize_style_features(self, features: dict[str, Any] | None) -> dict[str, bool]:
        source = features if isinstance(features, dict) else {}
        return {
            "instruments": bool(source.get("instruments", True)),
            "arrangement": bool(source.get("arrangement", True)),
            "negative_tags": bool(source.get("negative_tags", True)),
            "scores": bool(source.get("scores", True)),
            "vocal_delivery": bool(source.get("vocal_delivery", True)),
            "lyric_vocal_tags": bool(source.get("lyric_vocal_tags", source.get("songtext_vocal_tags", True))),
        }

    def _normalize_variant_strategy(self, value: str | None) -> str:
        key = re.sub(r"[^a-z0-9_-]+", "_", str(value or "balanced").strip().lower()).strip("_")
        allowed = {"balanced", "diverse", "hook_focus", "darker", "radio", "experimental", "instrumental_focus"}
        return key if key in allowed else "balanced"

    def _normalize_style_batch_mode(self, value: Any | None) -> str:
        key = re.sub(r"[^a-z0-9_-]+", "_", str(value or self.settings.ai_style_generation_batch_mode or "auto").strip().lower()).strip("_")
        return key if key in STYLE_BATCH_MODES else "auto"

    def _style_low_token_model_names(self) -> set[str]:
        return {item.strip().lower() for item in str(self.settings.ai_style_generation_low_token_models or "").split(",") if item.strip()}

    def _is_low_token_style_runtime(self, provider: str, model: str, profile_options: dict[str, Any]) -> bool:
        model_key = str(model or "").strip().lower()
        provider_key = str(provider or "").strip().lower()
        if model_key in self._style_low_token_model_names():
            return True
        try:
            max_output_tokens = int(profile_options.get("max_output_tokens") or self.settings.ai_max_output_tokens or 0)
        except (TypeError, ValueError):
            max_output_tokens = 0
        threshold = max(1200, int(self.settings.ai_style_generation_low_token_max_output_tokens or 4000))
        if max_output_tokens and max_output_tokens <= threshold:
            return True
        weak_markers = ("nano", "8b", "20b", "small", "mini-instruct")
        if provider_key in {"groq", "openai"} and any(marker in model_key for marker in weak_markers):
            return True
        return False

    def _resolve_style_batch_plan(
        self,
        requested_amount: int,
        *,
        provider: str,
        model: str,
        profile_options: dict[str, Any],
        batch_mode: str | None = None,
    ) -> dict[str, Any]:
        amount = max(1, min(int(requested_amount or 1), 5))
        mode = self._normalize_style_batch_mode(batch_mode)
        low_token = self._is_low_token_style_runtime(provider, model, profile_options)
        default_batch_size = max(1, min(int(self.settings.ai_style_generation_default_batch_size or 3), 5))
        low_token_batch_size = max(1, min(int(self.settings.ai_style_generation_low_token_batch_size or 1), 5))

        if mode == "single":
            batch_size = 1
        elif mode == "batch":
            batch_size = amount
        elif mode == "chunked":
            batch_size = low_token_batch_size if low_token else min(default_batch_size, 2)
        else:
            batch_size = low_token_batch_size if low_token else default_batch_size
        batch_size = max(1, min(batch_size, amount))

        batches: list[int] = []
        remaining = amount
        while remaining > 0:
            size = min(batch_size, remaining)
            batches.append(size)
            remaining -= size
        return {
            "mode": mode,
            "low_token_runtime": low_token,
            "batch_size": batch_size,
            "batches": batches,
            "request_count": len(batches),
            "compact_reference": bool(low_token and self.settings.ai_style_generation_compact_reference_for_low_token),
        }

    def _compact_style_reference(self) -> dict[str, Any]:
        return {
            "style_prompt_architecture": [
                "Style-Feld und Lyrics-Feld strikt trennen.",
                "Priorität: Genre/Ära, Stimmung, Instrumente, Vocal-Charakter, Produktion, BPM.",
                "Style-Feld maximal 1000 Zeichen und direkt in Suno nutzbar.",
            ],
            "lyric_vocal_tag_formula": [
                "[SECTION: voice identity, vocal texture, delivery style, emotion, energy, language/accent, vocal production]",
                "Nur kurze Section-Tags liefern; voller getaggter Songtext wird separat erzeugt.",
            ],
        }

    def _build_style_instruction_payload(
        self,
        *,
        requested_amount: int,
        batch_amount: int,
        batch_index: int,
        batch_total: int,
        clean_lyrics: str,
        title: str | None,
        current_style: str | None,
        extra_prompt: str | None,
        normalized_features: dict[str, bool],
        normalized_strategy: str,
        vocal_tags: list[dict[str, Any]],
        instruction_files: list[dict[str, Any]],
        compact_reference: bool,
        bpm_range: tuple[int, int] | None = None,
        previous_suggestions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        reference = self._compact_style_reference() if compact_reference else SUNO_STYLE_DOCUMENTATION_REFERENCE
        previous_titles = [self._limit_text(item.get("title"), 120) for item in (previous_suggestions or []) if item.get("title")]
        rules = [
            f"Gib exakt {batch_amount} Vorschlag/Vorschläge für diesen Batch zurück. Insgesamt werden {requested_amount} Vorschläge erzeugt.",
            "Jeder Style ist ein vollständiger kopierbarer Suno-Master-Style-Prompt in einem Feld mit maximal 1000 Zeichen; Zielbereich 900 bis 950 Zeichen, damit der Prompt vollständig endet und nicht serverseitig gekürzt werden muss.",
            "Liefere pro Vorschlag zusätzlich suggested_song_title als kurzen release-tauglichen Songtitel. suggested_song_title ist der eigentliche Songtitel, title bleibt nur der Name der Style-Variante.",
            "Style-Prompts müssen abgeschlossen formuliert sein: keine abgeschnittenen Satzenden, keine offenen Aufzählungen, keine wichtigen Informationen erst am Ende verstecken.",
            "Instrumente, Arrangement, Vocal-Delivery, feste BPM, Energie und Produktion müssen im style-Feld enthalten sein, nicht nur in Zusatzfeldern.",
            'bpm ist Pflicht und muss immer eine feste ganze Zahl als String enthalten, z. B. "170". Keine Bereiche wie "167-172", keine ca.-Angaben und kein leeres bpm-Feld.',
            'Das style-Feld muss dieselbe feste BPM enthalten, z. B. "170 BPM". Wenn ein Tempo-Wunsch als Bereich vorliegt, wähle den musikalisch passendsten Mittelwert.',
            "Nutze erkennbare Sprache, Rap-/Gesangsstimme, Stimmung, Hook-Art, Beat-Art und Energie aus dem Text.",
            "Wenn der Text Vocal Tags enthält, berücksichtige sie aktiv.",
            "Wenn der Zusatzprompt Wünsche nennt, priorisiere diese, solange sie zum Songtext passen.",
            "Liefere Instrumente nur, wenn features.instruments=true; maximal 10 Instrumente je Vorschlag.",
            "Liefere Arrangement nur, wenn features.arrangement=true; maximal Intro, Verse, Hook, Bridge/Breakdown und Outro.",
            "Liefere negative_tags nur, wenn features.negative_tags=true und sie dem Ziel wirklich helfen. Keine automatischen Überschreibungen annehmen.",
            "Liefere lyric_vocal_tags nur, wenn features.lyric_vocal_tags=true: 3 bis 6 kurze konkrete Suno-Songtext-Section-Tags passend exakt zu diesem Style. Keinen vollständigen Songtext ausgeben; der volle getaggte Songtext wird in einem separaten Vorschau-Request erzeugt.",
            "lyric_vocal_tags müssen die Doppelpunkt-Formel nutzen: [SECTION: voice identity, vocal texture, delivery style, emotion/attitude, energy, language/accent, vocal production].",
            "Nutze pro Abschnitt 3 bis 6 klare englische Deskriptoren. Verse, Chorus und Bridge müssen sich hörbar unterscheiden; Chorus/Hook stärker und wiedererkennbarer, Bridge kontrastierender.",
            "lyric_vocal_tags dürfen nicht im style-Feld versteckt werden. Nutze verfügbare Vocal-Tags plus Vocal-Baukasten als Referenz, passe sie aber auf Style, Sprache, Energie und Delivery an.",
            "Keine Instrumentenlisten, Sound-Pack-Rezepte oder Negative Tags in lyric_vocal_tags. Dort nur Stimme, Timbre, Delivery, Emotion, Energie, Sprache/Akzent und sparsame Vocal-FX.",
            "Liefere Scores nur, wenn features.scores=true; Werte immer zwischen 0 und 1.",
            "Das style-Feld bleibt die zentrale Hauptausgabe und muss alle musikalisch wichtigen Informationen enthalten. Zusatzfelder sind nur strukturierte Erklärung, nicht die einzige Quelle.",
        ]
        if compact_reference:
            rules.append("Tokenschwacher Modus: besonders kompakt antworten, keine langen Begründungen, keine Wiederholung der Regeln, JSON sauber halten.")
        if previous_titles:
            rules.append(f"Vermeide Dopplungen zu bereits erzeugten Titeln/Rollen: {', '.join(previous_titles[:8])}.")
        if bpm_range:
            lower, upper = bpm_range
            rules.append(f"Tempo-Eingrenzung aktiv: Wähle exakt eine ganze BPM-Zahl zwischen {lower} und {upper}. Entscheide innerhalb dieses Bereichs nach Style, Textfluss, Hook-Energie und Groove. Keine BPM außerhalb dieses Bereichs.")
        return {
            "task": "generate_suno_style_suggestions",
            "amount": batch_amount,
            "requested_total_amount": requested_amount,
            "batch_index": batch_index,
            "batch_total": batch_total,
            "song_title": title or "",
            "lyrics_or_prompt": self._trim_text(clean_lyrics, SUNO_STYLE_LYRICS_MAX_LENGTH),
            "current_style": self._trim_text(current_style, SUNO_STYLE_PROMPT_MAX_LENGTH),
            "extra_user_control_prompt": self._trim_text(extra_prompt, 3000),
            "features": normalized_features,
            "variant_strategy": normalized_strategy,
            "tempo_constraints": {"enabled": bool(bpm_range), "bpm_min": bpm_range[0], "bpm_max": bpm_range[1]} if bpm_range else {"enabled": False},
            "suno_quality_reference": reference,
            "vocal_tag_recipe_reference": self._compact_style_reference() if compact_reference else SUNO_VOCAL_TAG_RECIPE_REFERENCE,
            "variant_strategy_meaning": {
                "balanced": "sichere, klare und gut passende Suno-Styles",
                "diverse": "bewusst unterschiedliche Richtungen",
                "hook_focus": "Hook, Wiedererkennbarkeit und Refrain maximieren",
                "darker": "dunkler, härter und druckvoller",
                "radio": "klarer, zugänglicher und weniger überladen",
                "experimental": "mutigere Fusion und ungewöhnlichere Klangquellen",
                "instrumental_focus": "Bauplan und Instrumentierung priorisieren",
            }.get(normalized_strategy, "sichere, klare und gut passende Suno-Styles"),
            "available_vocal_tags": vocal_tags[:4] if compact_reference else vocal_tags,
            "linked_instruction_files": [] if compact_reference else instruction_files,
            "previous_suggestion_titles": previous_titles,
            "rules": rules,
        }

    def _extract_style_suggestions_from_text(self, text: str, amount: int) -> list[dict[str, Any]]:
        cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            return []
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
        has_structured_labels = bool(re.search(r"(?im)^\s*(?:title|titel|name|style|stil|suno[- ]?style|prompt|reason|begründung|beschreibung)\s*:", cleaned))
        if len(blocks) <= 1 and not has_structured_labels:
            blocks = [line.strip(" -•\t") for line in cleaned.split("\n") if line.strip()]

        suggestions: list[dict[str, Any]] = []
        for block in blocks:
            if len(suggestions) >= amount:
                break
            raw = re.sub(r"^\s*(?:\d+[.)]|[-•])\s*", "", block).strip()
            if not raw or raw.startswith("{") or raw.startswith("["):
                continue

            title = f"KI-Style {len(suggestions) + 1}"
            reason = "Aus der KI-Antwort extrahierter Suno-Style."
            style = raw

            title_match = re.search(r"(?im)^\s*(?:title|titel|name)\s*:\s*(.+)$", raw)
            style_match = re.search(r"(?ims)^\s*(?:style|stil|suno[- ]?style|prompt)\s*:\s*(.+?)(?:\n\s*(?:reason|begründung|beschreibung)\s*:|$)", raw)
            reason_match = re.search(r"(?ims)^\s*(?:reason|begründung|beschreibung)\s*:\s*(.+)$", raw)
            if title_match:
                title = title_match.group(1).strip()[:120] or title
            elif ":" in raw and len(raw.split(":", 1)[0]) <= 80:
                possible_title, rest = raw.split(":", 1)
                if len(rest.strip()) >= 20:
                    title = possible_title.strip(" *#")[:120] or title
                    style = rest.strip()
            if style_match:
                style = style_match.group(1).strip()
            if reason_match:
                reason = reason_match.group(1).strip()[:600] or reason

            style = re.sub(r"(?im)^\s*(?:title|titel|name|style|stil|suno[- ]?style|prompt|reason|begründung|beschreibung)\s*:\s*", "", style).strip()
            style = re.sub(r"\n{2,}", " ", style).strip()
            if len(style) < 20:
                continue
            suggestions.append({
                "title": title[:120] or f"KI-Style {len(suggestions) + 1}",
                "suggested_song_title": None,
                "style": style[:1500],
                "reason": reason[:600] or "Passt laut KI-Analyse zu Songtext, Stimmung, Delivery und Suno-Zielrichtung.",
                "instruments": [],
                "arrangement": [],
                "negative_tags": None,
                "lyric_vocal_tags": [],
                "scores": None,
                "bpm": None,
                "key_hint": None,
                "energy": None,
                "vocal_delivery": None,
                "role": None,
            })
        return suggestions

    async def generate_style_suggestions(
        self,
        db: Session,
        *,
        lyrics: str,
        amount: int = 3,
        extra_prompt: str | None = None,
        title: str | None = None,
        current_style: str | None = None,
        bpm_min: int | None = None,
        bpm_max: int | None = None,
        profile_id: int | None = None,
        features: dict[str, Any] | None = None,
        variant_strategy: str | None = None,
        batch_mode: str | None = None,
    ) -> dict[str, Any]:
        clean_lyrics = str(lyrics or "").strip()
        if not clean_lyrics:
            raise ValueError("Für KI-Style-Vorschläge wird ein Songtext oder Prompt benötigt.")
        if len(clean_lyrics) > SUNO_STYLE_LYRICS_MAX_LENGTH:
            raise ValueError(f"Songtext/Prompt darf für Styles generieren maximal {SUNO_STYLE_LYRICS_MAX_LENGTH} Zeichen enthalten.")
        clean_current_style = str(current_style or "").strip()
        if len(clean_current_style) > SUNO_STYLE_PROMPT_MAX_LENGTH:
            raise ValueError(f"Music Style darf für Styles generieren maximal {SUNO_STYLE_PROMPT_MAX_LENGTH} Zeichen enthalten.")
        bpm_range = self._normalize_bpm_range(bpm_min, bpm_max)

        requested_amount = max(1, min(int(amount or 3), 5))
        normalized_features = self._normalize_style_features(features)
        normalized_strategy = self._normalize_variant_strategy(variant_strategy)
        provider, model, system_instruction, vocal_tags, instruction_files, profile_options = self._get_ai_runtime(db, profile_id)
        vocal_tags = self._budget_vocal_tags(vocal_tags)
        instruction_files = self._budget_instruction_files(instruction_files, allow_canvas_changes=False)
        batch_plan = self._resolve_style_batch_plan(
            requested_amount,
            provider=provider,
            model=model,
            profile_options=profile_options,
            batch_mode=batch_mode,
        )
        runtime_info = {
            "provider": provider,
            "model": model,
            "profile_id": profile_options.get("profile_id"),
            "profile_name": profile_options.get("profile_name"),
            "temperature": profile_options.get("temperature"),
            "max_output_tokens": profile_options.get("max_output_tokens"),
            "instruction_files_count": len(instruction_files),
            "vocal_tags_count": len(vocal_tags),
            "source": "assistant_profile" if profile_options.get("profile_id") else "admin_defaults",
            "lyrics_max_chars": SUNO_STYLE_LYRICS_MAX_LENGTH,
            "music_style_max_chars": SUNO_STYLE_PROMPT_MAX_LENGTH,
            "music_style_target_chars": SUNO_STYLE_PROMPT_TARGET_LENGTH,
            "bpm_range": {"min": bpm_range[0], "max": bpm_range[1]} if bpm_range else None,
            "deferred_lyric_tagging": bool(self.settings.ai_style_generation_deferred_lyric_tagging_enabled),
            "style_batching": {
                "mode": batch_plan["mode"],
                "low_token_runtime": batch_plan["low_token_runtime"],
                "batch_size": batch_plan["batch_size"],
                "request_count": batch_plan["request_count"],
                "batches": batch_plan["batches"],
                "compact_reference": batch_plan["compact_reference"],
            },
        }
        style_system = (
            f"{system_instruction}\n\n"
            "Spezialaufgabe: Analysiere Songtexte und erstelle professionelle Suno-Style-Prompts als strukturiertes Musik-Briefing. "
            "Nutze die integrierte SunoAI Master-Dokumentation und den Vocal-Tag-Baukasten als Qualitätsreferenz. "
            "Die Styles müssen direkt in Suno nutzbar sein und präzise Genre, Subgenre, feste BPM als einzelne ganze Zahl, Drums, Bass, Instrumente, Vocal-Delivery, Stimmung, Sprache und Produktionsästhetik nennen. Keine BPM-Bereiche und keine fehlende BPM. "
            "Wenn tempo_constraints aktiv sind, muss die feste BPM innerhalb dieses Bereichs liegen und trotzdem musikalisch passend zu Text, Hook und Groove gewählt werden. "
            "Das style-Feld bleibt ein vollständiger Music-Style-Prompt mit Zielbereich 900 bis 950 Zeichen und harter Obergrenze 1000 Zeichen; section-spezifische Songtext-Vocal-Tags gehören ausschließlich in lyric_vocal_tags. "
            "Style-Prompts müssen sauber abgeschlossen sein und dürfen nicht mitten in einer Aufzählung oder einem Satz enden. "
            "Gib pro Vorschlag ein separates Feld suggested_song_title für den eigentlichen Songtitel aus; title ist nur die interne Überschrift der Style-Variante. "
            "Erstelle unterschiedliche, aber passende Varianten. Keine vollständigen Songtexte schreiben. Keine erfundenen URLs oder technischen IDs. "
            "Verwende keine direkten Künstler-Imitationen; übersetze Referenzen in neutrale Produktionsmerkmale. "
            "Antwortformat exakt als JSON: {\"suggestions\":[{\"title\":\"Style-Variante\",\"suggested_song_title\":\"Songtitel\",\"role\":\"Beste Hook-Variante\",\"style\":\"vollständiger Suno-Master-Style-Prompt inklusive Genre, fester BPM-Zahl, Instrumentierung, Vocal-Delivery, Arrangement und Produktionsästhetik in einem Feld\",\"reason\":\"...\",\"bpm\":\"96\",\"key_hint\":\"minor\",\"energy\":\"dark, punchy\",\"vocal_delivery\":\"...\",\"instruments\":[{\"name\":\"dusty drums\",\"role\":\"drums\",\"reason\":\"...\"}],\"arrangement\":[{\"section\":\"Hook\",\"idea\":\"...\"}],\"lyric_vocal_tags\":[{\"section\":\"Verse 1\",\"tag\":\"[Verse 1: gritty male vocals, aggressive rap flow, defiant, high energy, native Jamaican Patois]\",\"reason\":\"...\"},{\"section\":\"Chorus\",\"tag\":\"[Chorus: catchy patois hook, shouted call-and-response, doubled vocals, explosive energy]\",\"reason\":\"...\"}],\"negative_tags\":\"...\",\"scores\":{\"fit\":0.9,\"hook_potential\":0.8,\"suno_clarity\":0.88,\"risk\":0.1}}]}"
        )

        suggestions: list[dict[str, Any]] = []
        for batch_index, batch_amount in enumerate(batch_plan["batches"], start=1):
            instruction_payload = self._build_style_instruction_payload(
                requested_amount=requested_amount,
                batch_amount=batch_amount,
                batch_index=batch_index,
                batch_total=len(batch_plan["batches"]),
                clean_lyrics=clean_lyrics,
                title=title,
                current_style=clean_current_style,
                extra_prompt=extra_prompt,
                normalized_features=normalized_features,
                normalized_strategy=normalized_strategy,
                vocal_tags=vocal_tags,
                instruction_files=instruction_files,
                compact_reference=batch_plan["compact_reference"],
                bpm_range=bpm_range,
                previous_suggestions=suggestions,
            )
            result = await AiChatService().run_json_task(
                provider=provider,
                model=model,
                system_prompt=style_system,
                instruction_payload=instruction_payload,
                profile_options=profile_options,
            )
            parsed_batch = self._normalize_style_suggestions(result.data, batch_amount)
            if not parsed_batch:
                parsed_batch = self._normalize_style_suggestions({"raw_text": result.raw_text}, batch_amount)
            self._apply_bpm_range_to_suggestions(parsed_batch, bpm_range)
            suggestions.extend(parsed_batch)
            if len(suggestions) >= requested_amount:
                break

        suggestions = suggestions[:requested_amount]
        if not suggestions:
            raise ValueError("Die KI hat keine verwertbaren Style-Vorschläge geliefert. Bitte Zusatzprompt oder Songtext präzisieren.")
        if normalized_features.get("lyric_vocal_tags", True):
            for suggestion in suggestions:
                suggestion["lyric_vocal_tags"] = self._enhance_lyric_vocal_tags(clean_lyrics, suggestion, vocal_tags)
        else:
            for suggestion in suggestions:
                suggestion["lyric_vocal_tags"] = []
        return {
            "ok": True,
            "amount": len(suggestions),
            "suggestions": suggestions,
            "runtime_info": runtime_info,
        }

    def _strip_fenced_text(self, value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.I).strip()
        text = re.sub(r"\s*```$", "", text).strip()
        return text

    def _is_protected_lyric_directive(self, line: str) -> bool:
        return bool(re.match(r"^\[(end|fade out|fade to silence|stop|silence)\]$", str(line or "").strip(), re.IGNORECASE))

    def _is_standalone_bracket_directive(self, line: str) -> bool:
        text = str(line or "").strip()
        return bool(re.match(r"^\[[^\]]+\]$", text)) and not self._is_protected_lyric_directive(text)

    def _is_round_section_header(self, line: str) -> bool:
        text = str(line or "").strip()
        return bool(re.match(r"^\([^)]+\)$", text)) and bool(self._lyric_section_meta(text))

    def _fallback_section_tag_from_meta(self, meta: dict[str, str] | None) -> str:
        label = str((meta or {}).get("label") or "").strip()
        return f"[{label}]" if label else ""

    def _strip_leading_orphan_tag_block(self, lines: list[str]) -> list[str]:
        index = 0
        while index < len(lines) and not str(lines[index] or "").strip():
            index += 1
        start_index = index
        tag_count = 0
        while index < len(lines):
            trimmed = str(lines[index] or "").strip()
            if not trimmed:
                break
            if not re.match(r"^\[[^\]]+\]$", trimmed) or not self._lyric_section_meta(trimmed):
                break
            tag_count += 1
            index += 1
        if not tag_count:
            return lines
        next_index = index
        while next_index < len(lines) and not str(lines[next_index] or "").strip():
            next_index += 1
        next_line = str(lines[next_index] or "").strip() if next_index < len(lines) else ""
        if not re.match(r"^\([^)]+\)$", next_line) or not self._lyric_section_meta(next_line):
            return lines
        return [*lines[:start_index], *lines[next_index:]]

    def _merge_lyric_vocal_tags_into_lyrics(self, lyrics: str, tags: list[dict[str, str]]) -> str:
        normalized_tags = [tag for tag in tags if isinstance(tag, dict) and tag.get("tag")]
        if not normalized_tags:
            return str(lyrics or "").strip()

        exact_tags: dict[str, dict[str, str]] = {}
        base_tags: dict[str, dict[str, str]] = {}
        for item in normalized_tags:
            key_source = f"{item.get('section') or ''} {item.get('tag') or ''}"
            key = self._lyric_section_key(key_source)
            base = self._lyric_section_base_key(key_source)
            if key and key != "section" and key not in exact_tags:
                exact_tags[key] = item
            if base and base != "section" and base not in base_tags:
                base_tags[base] = item

        text = str(lyrics or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = self._strip_leading_orphan_tag_block(text.split("\n"))
        output: list[str] = []
        inserted_keys: set[str] = set()
        inserted_bases: set[str] = set()

        index = 0
        while index < len(lines):
            line = lines[index]
            meta = self._lyric_section_meta(line.strip())
            replacement = None
            if meta:
                replacement = exact_tags.get(meta["key"]) or base_tags.get(meta["base"])

            if replacement and replacement.get("tag"):
                tag_text = str(replacement.get("tag") or "").strip()
                output.append(tag_text)
                inserted_keys.add(self._lyric_section_key(f"{replacement.get('section') or ''} {tag_text}"))
                inserted_bases.add(self._lyric_section_base_key(f"{replacement.get('section') or ''} {tag_text}"))

                cursor = index + 1
                while cursor < len(lines):
                    candidate = str(lines[cursor] or "").strip()
                    if not candidate:
                        next_non_empty = ""
                        for probe in range(cursor + 1, len(lines)):
                            if str(lines[probe] or "").strip():
                                next_non_empty = str(lines[probe] or "").strip()
                                break
                        if next_non_empty and (self._is_standalone_bracket_directive(next_non_empty) or self._is_round_section_header(next_non_empty)):
                            cursor += 1
                            continue
                        break
                    if self._is_standalone_bracket_directive(candidate) or self._is_round_section_header(candidate):
                        cursor += 1
                        continue
                    break
                index = cursor
                continue

            if meta and self._is_round_section_header(line):
                fallback_tag = self._fallback_section_tag_from_meta(meta)
                output.append(fallback_tag or line)
                index += 1
                continue

            output.append(line)
            index += 1

        merged = "\n".join(output).strip()
        merged = re.sub(r"\n{3,}", "\n\n", merged)
        missing: list[str] = []
        for item in normalized_tags:
            tag_text = str(item.get("tag") or "").strip()
            key = self._lyric_section_key(f"{item.get('section') or ''} {tag_text}")
            base = self._lyric_section_base_key(f"{item.get('section') or ''} {tag_text}")
            if key not in inserted_keys and base not in inserted_bases and tag_text and tag_text not in merged:
                missing.append(tag_text)
        if missing:
            merged = f"{'\n'.join(missing)}\n\n{merged}".strip()
        return merged

    async def generate_style_tagged_lyrics(
        self,
        db: Session,
        *,
        lyrics: str,
        suggestion: dict[str, Any],
        title: str | None = None,
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        clean_lyrics = str(lyrics or "").strip()
        if not clean_lyrics:
            raise ValueError("Für die Songtext-Tag-Vorschau wird ein Songtext benötigt.")
        if len(clean_lyrics) > SUNO_STYLE_LYRICS_MAX_LENGTH:
            raise ValueError(f"Songtext darf maximal {SUNO_STYLE_LYRICS_MAX_LENGTH} Zeichen enthalten.")
        normalized_suggestion = self._normalize_style_item(suggestion or {}, index=1)
        if not normalized_suggestion:
            raise ValueError("Für die Songtext-Tag-Vorschau wird ein gültiger Style-Vorschlag benötigt.")

        provider, model, system_instruction, vocal_tags, instruction_files, profile_options = self._get_ai_runtime(db, profile_id)
        vocal_tags = self._budget_vocal_tags(vocal_tags)
        instruction_files = self._budget_instruction_files(instruction_files, allow_canvas_changes=False)
        runtime_info = {
            "provider": provider,
            "model": model,
            "profile_id": profile_options.get("profile_id"),
            "profile_name": profile_options.get("profile_name"),
            "lyrics_max_chars": SUNO_STYLE_LYRICS_MAX_LENGTH,
            "music_style_max_chars": SUNO_STYLE_PROMPT_MAX_LENGTH,
            "source": "style_tagged_lyrics_preview",
        }
        fallback_tags = self._enhance_lyric_vocal_tags(clean_lyrics, normalized_suggestion, vocal_tags)
        fallback_text = self._merge_lyric_vocal_tags_into_lyrics(clean_lyrics, fallback_tags)

        tag_system = (
            f"{system_instruction}\n\n"
            "Spezialaufgabe: Erzeuge für genau einen Suno-Style einen vollständigen getaggten Songtext. "
            "Der Originaltext muss erhalten bleiben. Du musst runde Klammern semantisch unterscheiden: reine Abschnittsmarker wie (Intro), (Verse 1), (Hook) oder (Outro) sind keine Vocal-/Adlib-Tags und müssen durch eckige Suno-Section-Tags ersetzt werden; echte Adlibs oder Performance-Hinweise wie (yeah), (uh-huh), (shouted) bleiben erhalten. Du darfst Abschnittsmarker verbessern und pro Abschnitt maximal eine kombinierte Tag-Zeile setzen. "
            "Alte Vocal-, Tempo-, Delivery- und Arrangement-Tags direkt nach Abschnittsmarkern müssen ersetzt werden; niemals alte Tags zusätzlich stehen lassen oder oben vor den Songtext kopieren. Erzeuge niemals Vocal-Tags in runden Klammern wie (Verse: ...); Suno-Steuer-Tags stehen immer in eckigen Klammern. "
            "Nutze Vocal-Tags und sparsame Instrumental-/Arrangement-Metatags nur in dieser einen kombinierten Abschnittszeile, wo sie dem Abschnitt helfen. "
            "Keine neuen Lyrics, keine Erklärung im Songtext, keine Music-Style-Liste. "
            "Antwortformat exakt als JSON: {\"tagged_lyrics\":\"vollständiger Songtext mit Tags\",\"lyric_vocal_tags\":[{\"section\":\"Verse 1\",\"tag\":\"[Verse 1: gritty male vocals, aggressive rap flow, defiant, high energy]\",\"reason\":\"...\"}],\"notes\":\"kurzer Hinweis\"}"
        )
        instruction_payload = {
            "task": "generate_suno_tagged_lyrics_for_single_style",
            "song_title": title or normalized_suggestion.get("title") or "",
            "lyrics": clean_lyrics,
            "style_suggestion": {
                "title": normalized_suggestion.get("title"),
                "style": self._limit_text(normalized_suggestion.get("style"), SUNO_STYLE_PROMPT_MAX_LENGTH),
                "bpm": normalized_suggestion.get("bpm"),
                "energy": normalized_suggestion.get("energy"),
                "vocal_delivery": normalized_suggestion.get("vocal_delivery"),
                "arrangement": normalized_suggestion.get("arrangement") or [],
                "lyric_vocal_tags": fallback_tags,
                "negative_tags": normalized_suggestion.get("negative_tags"),
            },
            "suno_quality_reference": self._compact_style_reference(),
            "available_vocal_tags": vocal_tags[:8],
            "linked_instruction_files": instruction_files[:2],
            "limits": {
                "tagged_lyrics_max_chars": SUNO_STYLE_LYRICS_MAX_LENGTH,
                "style_max_chars": SUNO_STYLE_PROMPT_MAX_LENGTH,
            },
            "rules": [
                "Originaltext vollständig erhalten; keine Zeilen neu dichten oder entfernen.",
                "Vorhandene Abschnitte wie [Verse], [Chorus], [Bridge], [Intro], [Outro] sowie runde Header wie (Intro), (Verse 1), (Hook), (Outro) erkennen und in saubere eckige Section-Tags überführen.",
                "Runde Klammern nur für echte Adlibs/Performance-Hinweise im Text behalten, z.B. (yeah), (uh-huh), (whispered); nie für Section- oder Vocal-Tags verwenden.",
                "Pro Abschnitt maximal eine kombinierte Tag-Zeile setzen; alte unmittelbar folgende Tags wie [Tempo], [Delivery], [Heavy brass hits], [Spoken word] oder alte [Chorus: ...]-Zeilen ersetzen, nicht behalten.",
                "Vocal-Tags nach Formel: [SECTION: voice identity, vocal texture, delivery style, emotion/attitude, energy, language/accent, vocal production].",
                "Instrumental-/Arrangement-Tags nur sparsam in derselben kombinierten Section-Zeile setzen, z.B. [Bridge: smoky male voice, stripped back, piano only, reflective].",
                "Keine Sound-Pack-Listen, keine Negative Tags, keine separaten Style-Prompts im Songtext.",
                f"tagged_lyrics muss maximal {SUNO_STYLE_LYRICS_MAX_LENGTH} Zeichen enthalten.",
            ],
        }
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=tag_system,
            instruction_payload=instruction_payload,
            profile_options=profile_options,
        )
        data = result.data if isinstance(result.data, dict) else {}
        tagged_lyrics = self._strip_fenced_text(
            data.get("tagged_lyrics")
            or data.get("taggedLyrics")
            or data.get("getaggter_songtext")
            or data.get("lyrics")
            or ""
        )
        response_tags = self._normalize_lyric_vocal_tags(data.get("lyric_vocal_tags") or data.get("songtext_vocal_tags") or [])
        if response_tags:
            lyric_vocal_tags = response_tags
        else:
            lyric_vocal_tags = fallback_tags
        if tagged_lyrics:
            tagged_lyrics = self._merge_lyric_vocal_tags_into_lyrics(tagged_lyrics, lyric_vocal_tags)
        else:
            tagged_lyrics = fallback_text
        if len(tagged_lyrics) > SUNO_STYLE_LYRICS_MAX_LENGTH:
            fallback_text = self._merge_lyric_vocal_tags_into_lyrics(clean_lyrics, lyric_vocal_tags)
            if len(fallback_text) <= SUNO_STYLE_LYRICS_MAX_LENGTH:
                tagged_lyrics = fallback_text
            else:
                raise ValueError(
                    f"Der getaggte Songtext würde {len(fallback_text)} Zeichen enthalten und damit das Limit von {SUNO_STYLE_LYRICS_MAX_LENGTH} Zeichen überschreiten. Bitte Songtext kürzen oder weniger Tags verwenden."
                )
        return {
            "ok": True,
            "tagged_lyrics": tagged_lyrics,
            "lyric_vocal_tags": lyric_vocal_tags,
            "notes": self._limit_text(data.get("notes") or data.get("hinweis") or "Songtext-Tags wurden passend zum ausgewählten Style erzeugt.", 500),
            "runtime_info": runtime_info,
        }

    async def run_style_consultation(
        self,
        db: Session,
        *,
        lyrics: str = "",
        message: str,
        draft: dict[str, Any],
        history: list[dict[str, Any]] | None = None,
        mode: str = "advise_or_update",
        profile_id: int | None = None,
    ) -> dict[str, Any]:
        clean_message = str(message or "").strip()
        if not clean_message:
            raise ValueError("Für die KI-Beratung wird eine Nachricht benötigt.")
        if len(str(lyrics or "")) > SUNO_STYLE_LYRICS_MAX_LENGTH:
            raise ValueError(f"Songtext darf in der Style-Beratung maximal {SUNO_STYLE_LYRICS_MAX_LENGTH} Zeichen enthalten.")
        current_draft = self._normalize_style_item(draft or {}, index=1)
        if not current_draft:
            raise ValueError("Für die KI-Beratung wird ein gültiger Style-Entwurf benötigt.")

        provider, model, system_instruction, vocal_tags, instruction_files, profile_options = self._get_ai_runtime(db, profile_id)
        vocal_tags = self._budget_vocal_tags(vocal_tags)
        instruction_files = self._budget_instruction_files(instruction_files, allow_canvas_changes=False)
        runtime_info = {
            "provider": provider,
            "model": model,
            "profile_id": profile_options.get("profile_id"),
            "profile_name": profile_options.get("profile_name"),
            "temperature": profile_options.get("temperature"),
            "max_output_tokens": profile_options.get("max_output_tokens"),
            "instruction_files_count": len(instruction_files),
            "vocal_tags_count": len(vocal_tags),
            "source": "assistant_profile" if profile_options.get("profile_id") else "admin_defaults",
        }
        clean_history: list[dict[str, str]] = []
        for row in (history or [])[-10:]:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "user")[:40]
            content = self._trim_text(row.get("content") or "", 2000)
            if content:
                clean_history.append({"role": role, "content": content})

        consultation_system = (
            f"{system_instruction}\n\n"
            "Spezialaufgabe: Du verfeinerst einen bestehenden Suno-Style-Entwurf im Musikbereich. "
            "Du nutzt dieselbe KI-Provider-Konfiguration wie die Style-Engine und erstellst keine neuen Provider-Wege. "
            "Berate auf Deutsch, aber halte den Style selbst Suno-tauglich, kompakt und direkt nutzbar. "
            "Du darfst eine aktualisierte Arbeitsversion vorschlagen, aber die App übernimmt sie erst nach Nutzerklick. "
            "Keine Songtexte schreiben, keine API-Keys, keine direkten Künstler-Imitationen. "
            "Antwortformat exakt als JSON: {\"assistant_message\":\"kurze natürliche Antwort\",\"updated_draft\":{\"title\":\"...\",\"style\":\"vollständiger Suno-Master-Style-Prompt inklusive Instrumentierung, Arrangement, Vocal-Delivery, BPM/Energie und Produktion\",\"reason\":\"...\",\"bpm\":\"...\",\"energy\":\"...\",\"vocal_delivery\":\"...\",\"instruments\":[{\"name\":\"...\",\"role\":\"...\"}],\"arrangement\":[{\"section\":\"Hook\",\"idea\":\"...\"}],\"lyric_vocal_tags\":[{\"section\":\"Verse 1\",\"tag\":\"[Verse 1 | German Male Rap | aggressive / precise / dark | Energy: High]\",\"reason\":\"...\"}],\"negative_tags\":\"...\",\"scores\":{\"fit\":0.9,\"hook_potential\":0.8,\"suno_clarity\":0.88,\"risk\":0.1}},\"changed\":true}"
        )
        instruction_payload = {
            "task": "refine_suno_style_consultation",
            "mode": str(mode or "advise_or_update"),
            "user_message": clean_message,
            "lyrics_or_prompt": self._trim_text(lyrics, SUNO_STYLE_LYRICS_MAX_LENGTH),
            "current_draft": current_draft,
            "chat_history": clean_history,
            "available_vocal_tags": vocal_tags,
            "linked_instruction_files": instruction_files,
            "rules": [
                "Wenn der Nutzer nur Beratung möchte, setze changed=false und updated_draft=null.",
                "Wenn der Nutzer eine Änderung verlangt, liefere eine vollständige aktualisierte Arbeitsversion in updated_draft.",
                "Fülle fehlende Felder aus dem aktuellen Draft sinnvoll weiter, statt sie ohne Grund zu löschen.",
                "negative_tags nur ergänzen, wenn sie sinnvoll sind; keine Annahme treffen, dass bestehende Felder automatisch ersetzt werden.",
                "style bleibt der vollständige Master-Style-Prompt für Suno und muss Instrumentierung, Arrangement, Vocal-Delivery, feste BPM/Energie und Produktion enthalten.",
                "bpm muss auch hier immer eine feste ganze Zahl als String sein; keine Bereiche und kein leeres bpm-Feld.",
            ],
        }
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=consultation_system,
            instruction_payload=instruction_payload,
            profile_options=profile_options,
        )
        data = result.data if isinstance(result.data, dict) else {}
        assistant_message = self._limit_text(data.get("assistant_message") or data.get("message") or result.raw_text, 1800) or "Ich habe die Zusammenstellung geprüft."
        updated_source = data.get("updated_draft") or data.get("draft") or None
        changed = bool(data.get("changed"))
        updated_draft = None
        if isinstance(updated_source, dict):
            updated_draft = self._normalize_style_item(updated_source, index=1, fallback=current_draft)
            changed = bool(updated_draft and changed)
        return {
            "ok": True,
            "assistant_message": assistant_message,
            "updated_draft": updated_draft if changed else None,
            "changed": bool(changed and updated_draft),
            "runtime_info": runtime_info,
        }

    def _build_intelligent_instruction(self, *, message: str, app_context: dict[str, Any], detected: str | None = None, allow_canvas_changes: bool = False, work_mode: str = "lyrics") -> str:
        context_summary = self.build_context_summary(app_context)
        canvas = self._budget_canvas(app_context, allow_canvas_changes=allow_canvas_changes)
        page = app_context.get("page_label") or app_context.get("active_tab") or "App"
        action_hint = CANVAS_ACTION_PROMPTS.get(detected or "", "")
        mode_label = "Instrumental-Bauplan" if work_mode == "instrumental_blueprint" else "Songtext"
        return (
            f"Nutzerwunsch:\n{message or action_hint or 'Hilf im aktuellen Schritt.'}\n\n"
            f"Aktueller Bereich: {page}\n"
            f"Arbeitsmodus: {mode_label}\n"
            f"Kontext: {context_summary}\n"
            f"Erkannte Aktion: {detected or 'keine'}\n"
            f"Canvas-Arbeit erlaubt: {'ja, aber nur als Vorschau' if allow_canvas_changes else 'nein, nur Chat-Antwort'}\n"
            f"Spezialhinweis zur Aktion: {action_hint or 'Keine feste Aktion; normal antworten.'}\n\n"
            "Arbeitsregeln:\n"
            "- Antworte direkt und hilfreich auf Deutsch.\n"
            "- Bei normalem Chat: canvas_text muss null bleiben. Gib angefragte Entwürfe im assistant_message aus.\n"
            "- Bei erlaubter Canvas-Arbeit: liefere eine vollständige neue Canvas-Vorschau in canvas_text und nur eine kurze Erklärung im assistant_message.\n"
            "- Wenn Angaben fehlen: wähle eigenständig ein sinnvolles kreatives Konzept und erkläre die Annahme kurz.\n"
            "- Wenn einzelne Sektionen genannt werden, z.B. Verse 3, Strophe 3, Chorus, Hook oder Bridge: bearbeite gezielt diese Sektion und lasse den Rest möglichst stabil.\n"
            "- Wenn Vocal Tags erwähnt werden: verarbeite, ergänze oder ändere die Tags im Canvas sinnvoll.\n"
            "- Schreibe für Anfänger verständlich, ohne technische Begriffe.\n\n"
            f"Aktueller Canvas ({len(str(app_context.get('current_canvas') or ''))} Zeichen, ggf. gekürzt):\n{canvas}"
        )

    def _parse_embedded_json(self, value: str) -> dict[str, Any] | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        candidates = [cleaned]
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    def _normalize_ai_canvas_result(self, assistant_message: str | None, canvas_text: str | None, change_summary: str | None, *, allow_canvas_changes: bool) -> tuple[str, str | None, str | None]:
        reply = str(assistant_message or "").strip()
        canvas = canvas_text if allow_canvas_changes and isinstance(canvas_text, str) and canvas_text.strip() else None
        summary = change_summary if isinstance(change_summary, str) and change_summary.strip() else None
        parsed = self._parse_embedded_json(reply)
        if parsed:
            parsed_message = parsed.get("assistant_message")
            parsed_canvas = parsed.get("canvas_text")
            parsed_summary = parsed.get("change_summary")
            if allow_canvas_changes and isinstance(parsed_canvas, str) and parsed_canvas.strip() and not canvas:
                canvas = parsed_canvas.replace("\r\n", "\n")
            if isinstance(parsed_summary, str) and parsed_summary.strip() and not summary:
                summary = parsed_summary.strip()
            if isinstance(parsed_message, str) and parsed_message.strip():
                reply = parsed_message.strip()
        if canvas:
            if not reply or reply.startswith("{") or '"canvas_text"' in reply:
                reply = "Ich habe eine Canvas-Vorschau vorbereitet. Prüfe sie direkt im Songtext-Studio und übernimm sie erst, wenn sie passt."
            reply = re.sub(r"\{\s*\"assistant_message\".*", "", reply, flags=re.S).strip() or "Ich habe eine Canvas-Vorschau vorbereitet."
        return reply, canvas, summary

    def _runtime_info(self, *, provider: str, model: str, profile_options: dict[str, Any], instruction_files: list[dict[str, Any]], vocal_tags: list[dict[str, Any]], app_context: dict[str, Any], work_mode: str, allow_canvas_changes: bool, detected: str | None, history: list[dict[str, Any]]) -> dict[str, Any]:
        canvas = str(app_context.get("current_canvas") or "")
        return {
            "provider": provider,
            "model": model,
            "profile_id": profile_options.get("profile_id"),
            "profile_name": profile_options.get("profile_name"),
            "temperature": profile_options.get("temperature"),
            "max_output_tokens": profile_options.get("max_output_tokens"),
            "instruction_files_count": len(instruction_files),
            "vocal_tags_count": len(vocal_tags),
            "source": "assistant_profile" if profile_options.get("profile_id") else "admin_defaults",
            "work_mode": work_mode,
            "canvas_requested": allow_canvas_changes,
            "detected_action": detected,
            "context_budget": {
                "canvas_chars_total": len(canvas),
                "canvas_chars_sent": len(self._budget_canvas(app_context, allow_canvas_changes=allow_canvas_changes)),
                "history_messages_sent": len(history or []),
            },
        }

    async def _run_ai_for_request(
        self,
        db: Session,
        *,
        message: str,
        app_context: dict[str, Any],
        detected: str | None,
        profile_id: int | None,
        history: list[dict[str, str]] | None = None,
        allow_canvas_changes: bool = False,
    ) -> AssistantResult:
        work_mode = self._resolve_work_mode(app_context)
        provider, model, system_instruction, vocal_tags, instruction_files, profile_options = self._get_ai_runtime(db, profile_id)
        vocal_tags = self._budget_vocal_tags(vocal_tags)
        instruction_files = self._budget_instruction_files(instruction_files, allow_canvas_changes=allow_canvas_changes)
        budgeted_history = self._budget_history(history, allow_canvas_changes=allow_canvas_changes)
        runtime_info = self._runtime_info(
            provider=provider,
            model=model,
            profile_options=profile_options,
            instruction_files=instruction_files,
            vocal_tags=vocal_tags,
            app_context=app_context,
            work_mode=work_mode,
            allow_canvas_changes=allow_canvas_changes,
            detected=detected,
            history=budgeted_history,
        )
        instruction = self._build_intelligent_instruction(
            message=message,
            app_context=app_context,
            detected=detected,
            allow_canvas_changes=allow_canvas_changes,
            work_mode=work_mode,
        )
        result = await AiChatService().run_canvas_assistant(
            provider=provider,
            model=model,
            user_message=instruction,
            canvas_content=self._budget_canvas(app_context, allow_canvas_changes=allow_canvas_changes),
            history=budgeted_history,
            system_instruction=system_instruction,
            vocal_tags=vocal_tags,
            instruction_files=instruction_files,
            profile_options=profile_options,
            allow_canvas_changes=allow_canvas_changes,
            work_mode=work_mode,
        )
        reply, proposed_canvas, change_summary = self._normalize_ai_canvas_result(result.assistant_message, result.canvas_text, result.change_summary, allow_canvas_changes=allow_canvas_changes)
        active_tab = str(app_context.get("active_tab") or "home").lower()
        base_actions = self._available_actions(app_context, active_tab)
        if proposed_canvas:
            preview_actions = [clone_action("lyrics_apply_preview"), clone_action("lyrics_discard_preview")]
            base_actions = preview_actions + [item for item in base_actions if item.get("id") not in {"lyrics_apply_preview", "lyrics_discard_preview"}]
        return AssistantResult(
            reply=reply or ("Ich habe eine Canvas-Vorschau vorbereitet." if proposed_canvas else "Ich habe die Antwort vorbereitet."),
            suggested_actions=base_actions,
            proposed_canvas=proposed_canvas,
            change_summary=change_summary if proposed_canvas or allow_canvas_changes else None,
            context_summary=self.build_context_summary(app_context),
            runtime_info=runtime_info,
        )

    def _should_prepare_canvas(self, *, message: str, action_id: str | None, detected: str | None, apply_to_canvas: bool, app_context: dict[str, Any]) -> bool:
        if apply_to_canvas:
            return True
        if action_id and action_id in CANVAS_ACTION_PROMPTS:
            return True
        text = (message or "").lower()
        if detected in CANVAS_ACTION_PROMPTS and self.is_create_lyrics_intent(text):
            return True
        if detected in CANVAS_ACTION_PROMPTS and app_context.get("active_tab") == "lyrics" and any(pattern in text for pattern in CANVAS_EXECUTION_PATTERNS):
            return True
        return False

    async def run(self, db: Session, *, message: str, app_context: dict[str, Any], action_id: str | None = None, profile_id: int | None = None, apply_to_canvas: bool = False, history: list[dict[str, str]] | None = None) -> AssistantResult:
        active_tab = str(app_context.get("active_tab") or "home").lower()
        detected = action_id or self.detect_action(message, active_tab)
        base_actions = self._available_actions(app_context, active_tab)
        if detected and not any(item.get("id") == detected for item in base_actions):
            base_actions = [clone_action(detected)] + base_actions

        clean_message = str(message or "").strip()
        allow_canvas_changes = self._should_prepare_canvas(
            message=clean_message,
            action_id=action_id,
            detected=detected,
            apply_to_canvas=apply_to_canvas,
            app_context=app_context,
        )

        if clean_message or detected in CANVAS_ACTION_PROMPTS:
            try:
                return await self._run_ai_for_request(
                    db,
                    message=clean_message,
                    app_context=app_context,
                    detected=detected,
                    profile_id=profile_id,
                    history=history or [],
                    allow_canvas_changes=allow_canvas_changes,
                )
            except AiProviderError as exc:
                runtime_info = None
                try:
                    runtime_info = self.get_runtime_info(db, profile_id)
                except Exception:
                    runtime_info = None
                return AssistantResult(
                    reply=f"Ich kann gerade nicht frei antworten, weil die konfigurierte KI nicht verfügbar ist: {exc}. Prüfe im Adminbereich Provider, Modell, Profil und API-Key. Bis dahin zeige ich nur sichere Basisaktionen an.",
                    suggested_actions=base_actions,
                    context_summary=self.build_context_summary(app_context),
                    runtime_info=runtime_info,
                )
            except Exception as exc:
                runtime_info = None
                try:
                    runtime_info = self.get_runtime_info(db, profile_id)
                except Exception:
                    runtime_info = None
                return AssistantResult(
                    reply=f"Der KI-Assistent konnte die freie Antwort nicht erstellen: {exc}. Die App wurde nicht verändert.",
                    suggested_actions=base_actions,
                    context_summary=self.build_context_summary(app_context),
                    runtime_info=runtime_info,
                )

        runtime_info = None
        try:
            runtime_info = self.get_runtime_info(db, profile_id)
        except Exception:
            runtime_info = None
        return AssistantResult(
            reply=self.simple_help_reply(clean_message, app_context, base_actions),
            suggested_actions=base_actions,
            context_summary=self.build_context_summary(app_context),
            runtime_info=runtime_info,
        )
