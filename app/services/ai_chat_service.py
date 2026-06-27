from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class AiProviderError(RuntimeError):
    pass


@dataclass
class AiCanvasResult:
    assistant_message: str
    canvas_text: str | None
    change_summary: str | None
    raw_response: dict[str, Any]


@dataclass
class AiJsonResult:
    data: dict[str, Any]
    raw_text: str
    raw_response: dict[str, Any]


SYSTEM_PROMPT = """Du bist ein präziser Songstudio-Assistent für Songtexte, Suno-taugliche Strukturen und Instrumental-/Sound-Baupläne.
Du kannst frei mit dem Nutzer über Ideen, Stil, Dramaturgie, Reime, Story, Struktur, Arrangement und Produktionsentscheidungen diskutieren.
Du arbeitest nur dann direkt am Canvas, wenn der aktuelle Aufruf ausdrücklich als Ausführung/Canvas-Bearbeitung gekennzeichnet ist.
Bei normalen Chatfragen erklärst, berätst, diskutierst und entwirfst du im Chat, ohne den Canvas zu verändern.
Wenn der Nutzer in der freien Diskussion einen vollständigen Text, einen Instrumental-Bauplan, eine Reimbank, Sound-Ideen, eine Struktur oder konkrete Zeilen verlangt, liefere den Inhalt vollständig im Feld assistant_message. Antworte niemals nur mit einer Zusammenfassung wie "Pipeline läuft" oder "erstellt", wenn der eigentliche Inhalt fehlt.
Wenn du den Canvas bearbeitest, gib immer den vollständigen aktualisierten Canvas zurück und bewahre vorhandene Sektionen, die nicht geändert werden sollen.
Canvas-Regel im Songtext-Modus: canvas_text darf ausschließlich finalen Songtext enthalten: Vocal Tags, Songsektionen, Lyrics, kurze Adlibs/Performance-Hinweise. Keine Reimbanken, Pipeline-Überschriften, Flow-Pläne, Qualitätsprüfungen, Erklärungen, Fragen oder Meta-Kommentare im Canvas. Alles Analytische gehört vollständig in assistant_message.
Canvas-Regel im Instrumental-Bauplan-Modus: canvas_text darf ausschließlich den finalen instrumental nutzbaren Bauplan enthalten: Timecode-Sektionen, Arrangement-Abschnitte, Instrumentierung, Sounddesign, Energieverlauf, Drops, Breakdowns, Builds, Outro. Keine Lyrics, keine gesungenen Zeilen, keine Reimbanken, keine Pipeline-Analyse, keine Meta-Erklärung im Canvas.
Bei einem Ausführungsbefehl wie "einfügen", "übernehmen", "Canvas erstellen" oder "schreib den finalen Song/Bauplan" darfst du niemals behaupten, der Canvas sei geändert, ohne im Feld canvas_text den vollständigen neuen Canvas zu liefern.
Antworte ausschließlich als gültiges JSON-Objekt ohne Markdown-Codeblock und ohne erklärenden Text außerhalb des JSON:
{
  "assistant_message": "natürliche Antwort für den Chat, bei freien Entwürfen inklusive vollständigem Inhalt",
  "canvas_text": "vollständiger aktualisierter Canvas oder null, wenn keine Änderung ausgeführt wird",
  "change_summary": "knappe Zusammenfassung der Änderung oder null",
  "suggested_title": "optional"
}
Keine erfundenen Fakten. Keine Klartext-Secrets. Nutze den bisherigen Chatverlauf als Arbeitsgedächtnis.
"""

class AiChatService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def validate_provider_model(self, provider: str, model: str) -> tuple[str, str, str]:
        provider_key = str(provider or "").strip().lower()
        model_key = str(model or "").strip()
        allowed = self.settings.ai_allowed_models
        if provider_key not in allowed:
            raise AiProviderError("Unbekannter KI-Provider.")
        if model_key not in allowed[provider_key]:
            raise AiProviderError("Dieses Modell ist nicht freigegeben.")
        if not self.settings.ai_provider_has_key(provider_key):
            raise AiProviderError("Für diesen KI-Provider ist kein API-Key konfiguriert.")
        api_model = self.settings.resolve_ai_model(provider_key, model_key)
        return provider_key, model_key, api_model

    async def run_canvas_assistant(
        self,
        *,
        provider: str,
        model: str,
        user_message: str,
        canvas_content: str,
        history: list[dict[str, str]] | None = None,
        system_instruction: str | None = None,
        vocal_tags: list[dict[str, Any]] | None = None,
        instruction_files: list[dict[str, Any]] | None = None,
        profile_options: dict[str, Any] | None = None,
        allow_canvas_changes: bool = True,
        work_mode: str = "lyrics",
    ) -> AiCanvasResult:
        provider_key, model_key, api_model = self.validate_provider_model(provider, model)
        history_rows = history or []
        instruction = self._build_user_instruction(
            user_message,
            canvas_content,
            vocal_tags or [],
            instruction_files or [],
            allow_canvas_changes=allow_canvas_changes,
            work_mode=work_mode,
        )
        effective_system_prompt = self._build_system_prompt(system_instruction)
        profile_options = profile_options or {}

        raw_text, raw = await self._call_provider(
            provider_key,
            api_model,
            instruction,
            history_rows,
            effective_system_prompt,
            profile_options,
        )

        parsed = self._parse_json_response(raw_text)
        assistant_message = self._normalize_assistant_message(parsed.get("assistant_message"), raw_text)
        canvas_text, canvas_notes = self._normalize_canvas_result(parsed.get("canvas_text"), work_mode=work_mode)
        if not allow_canvas_changes:
            if canvas_text:
                assistant_message = self._append_canvas_notes_to_assistant_message(
                    assistant_message,
                    "Die KI hat in einer freien Chat-Antwort canvas_text geliefert. Dieser Inhalt wurde aus Sicherheitsgründen nicht als Canvas-Vorschau übernommen. Nutze eine Canvas-Aktion wie „Vorschau erstellen“ oder „Suno-ready machen“, wenn der Canvas geändert werden soll.",
                )
            canvas_text = None
            canvas_notes = None
        if canvas_notes:
            assistant_message = self._append_canvas_notes_to_assistant_message(assistant_message, canvas_notes)
        change_summary = self._normalize_optional_text(parsed.get("change_summary"))
        if not allow_canvas_changes:
            change_summary = None
        raw_response: dict[str, Any] = self._build_raw_response_snapshot(
            provider_key=provider_key,
            model_key=model_key,
            api_model=api_model,
            profile_options=profile_options,
            raw=raw,
            parsed=parsed,
            raw_text=raw_text,
            allow_canvas_changes=allow_canvas_changes,
            work_mode=work_mode,
            repaired=False,
        )

        if allow_canvas_changes and not canvas_text:
            repair_instruction = self._build_missing_canvas_repair_instruction(
                user_message=user_message,
                canvas_content=canvas_content,
                previous_raw_response=raw_text,
                vocal_tags=vocal_tags or [],
                instruction_files=instruction_files or [],
                work_mode=work_mode,
            )
            repair_raw_text, repair_raw = await self._call_provider(
                provider_key,
                api_model,
                repair_instruction,
                history_rows,
                effective_system_prompt,
                profile_options,
            )
            repair_parsed = self._parse_json_response(repair_raw_text)
            repaired_canvas_text, repair_canvas_notes = self._normalize_canvas_result(repair_parsed.get("canvas_text"), work_mode=work_mode)
            raw_response["repair"] = self._build_raw_response_snapshot(
                provider_key=provider_key,
                model_key=model_key,
                api_model=api_model,
                profile_options=profile_options,
                raw=repair_raw,
                parsed=repair_parsed,
                raw_text=repair_raw_text,
                allow_canvas_changes=allow_canvas_changes,
                work_mode=work_mode,
                repaired=True,
            )

            if repaired_canvas_text:
                canvas_text = repaired_canvas_text
                assistant_message = self._normalize_assistant_message(repair_parsed.get("assistant_message"), assistant_message)
                if repair_canvas_notes:
                    assistant_message = self._append_canvas_notes_to_assistant_message(assistant_message, repair_canvas_notes)
                change_summary = self._normalize_optional_text(repair_parsed.get("change_summary")) or change_summary or "Canvas aus Chatverlauf übernommen"
            else:
                assistant_message = (
                    self._normalize_assistant_message(repair_parsed.get("assistant_message"), assistant_message)
                    + "\n\nCanvas wurde nicht geändert, weil die KI keinen vollständigen canvas_text geliefert hat. Bitte formuliere den Ausführungsbefehl konkreter oder markiere den gewünschten Text im Chat erneut."
                ).strip()
                canvas_text = None
                change_summary = change_summary or "Keine Canvas-Änderung: fehlender canvas_text"

        return AiCanvasResult(
            assistant_message=assistant_message,
            canvas_text=canvas_text,
            change_summary=change_summary,
            raw_response=raw_response,
        )

    def _build_raw_response_snapshot(
        self,
        *,
        provider_key: str,
        model_key: str,
        api_model: str,
        profile_options: dict[str, Any],
        raw: dict[str, Any],
        parsed: dict[str, Any],
        raw_text: str,
        allow_canvas_changes: bool,
        work_mode: str,
        repaired: bool,
    ) -> dict[str, Any]:
        usage = raw.get("usage") if isinstance(raw, dict) else None
        snapshot: dict[str, Any] = {
            "provider": provider_key,
            "model": model_key,
            "api_model": api_model,
            "profile": {
                "profile_id": profile_options.get("profile_id"),
                "profile_name": profile_options.get("profile_name"),
                "temperature": profile_options.get("temperature"),
                "max_output_tokens": profile_options.get("max_output_tokens"),
            },
            "parsed": parsed,
            "metrics": {
                "raw_text_chars": len(raw_text or ""),
                "assistant_message_chars": len(str(parsed.get("assistant_message") or "")) if isinstance(parsed, dict) else 0,
                "canvas_text_chars": len(str(parsed.get("canvas_text") or "")) if isinstance(parsed, dict) else 0,
                "allow_canvas_changes": allow_canvas_changes,
                "work_mode": self._normalize_work_mode(work_mode),
                "repaired": repaired,
                "raw_response_stored": bool(self.settings.ai_store_raw_responses or self.settings.debug),
            },
        }
        if usage is not None:
            snapshot["usage"] = usage
        if self.settings.ai_store_raw_responses or self.settings.debug:
            snapshot["raw"] = raw
            snapshot["raw_text"] = raw_text
        return snapshot

    async def _call_provider(
        self,
        provider_key: str,
        api_model: str,
        instruction: str,
        history: list[dict[str, str]],
        system_prompt: str,
        profile_options: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if provider_key == "openai":
            return await self._call_openai(api_model, instruction, history, system_prompt, profile_options)
        if provider_key == "openrouter":
            return await self._call_openrouter(api_model, instruction, history, system_prompt, profile_options)
        if provider_key == "gemini":
            return await self._call_gemini(api_model, instruction, history, system_prompt, profile_options)
        if provider_key == "groq":
            return await self._call_groq(api_model, instruction, history, system_prompt, profile_options)
        raise AiProviderError("Unbekannter KI-Provider.")

    def _normalize_optional_text(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized or normalized.lower() in {"null", "none"}:
            return None
        return normalized

    def _normalize_assistant_message(self, value: Any, fallback: str | None = None) -> str:
        raw = value if value is not None else fallback
        if isinstance(raw, dict):
            raw = raw.get("assistant_message") or raw.get("message") or raw.get("reply") or ""
        if raw is None:
            return ""
        text = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return ""

        nested = self._parse_embedded_json_object(text)
        if nested:
            nested_message = nested.get("assistant_message") or nested.get("message") or nested.get("reply")
            if isinstance(nested_message, str) and nested_message.strip():
                return nested_message.replace("\r\n", "\n").replace("\r", "\n").strip()

        text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
        text = re.sub(r"\s*```$", "", text.strip())
        return text.strip()

    def _normalize_work_mode(self, value: str | None) -> str:
        normalized = str(value or "lyrics").strip().lower().replace("-", "_")
        if normalized in {"instrumental", "instrumental_blueprint", "blueprint", "sound_blueprint", "sounds"}:
            return "instrumental_blueprint"
        return "lyrics"

    def _normalize_canvas_result(self, value: Any, *, work_mode: str = "lyrics") -> tuple[str | None, str | None]:
        if not isinstance(value, str):
            return None, None
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized or normalized.lower() in {"null", "none", "keine änderung"}:
            return None, None
        return self._sanitize_canvas_text(normalized, work_mode=work_mode)

    def _normalize_canvas_text(self, value: Any) -> str | None:
        canvas_text, _notes = self._normalize_canvas_result(value)
        return canvas_text

    def _sanitize_canvas_text(self, text: str, *, work_mode: str = "lyrics") -> tuple[str | None, str | None]:
        """Keep only executable Canvas content.

        Analysis, pipeline notes, rhyme banks and flow plans belong into the chat.
        In lyrics mode the Canvas holds lyrics. In instrumental mode it holds a no-lyrics arrangement blueprint.
        """
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return None, None

        if self._normalize_work_mode(work_mode) == "instrumental_blueprint":
            return self._sanitize_instrumental_blueprint_text(normalized)

        section_re = re.compile(
            r"(?im)^\s*\[(intro|verse|hook|chorus|pre[- ]?chorus|post[- ]?chorus|bridge|outro|adlibs?|interlude|drop|build|break|part|strophe|refrain)\b[^\]]*\]\s*$"
        )
        match = section_re.search(normalized)
        notes: list[str] = []

        if match:
            prefix = normalized[: match.start()].strip()
            if prefix:
                notes.append(prefix)
            lyric_part = normalized[match.start():].strip()
        else:
            lyric_part = normalized

        lines = lyric_part.split("\n")
        cleaned_lines: list[str] = []
        dropped_lines: list[str] = []
        seen_section = False

        stop_heading_re = re.compile(
            r"(?i)^\s*(qualitätsprüfung|pipeline|reimwort|flow[- ]?plan|metrik[- ]?plan|schritt\s*\d|analyse|begründung|notizen|zusammenfassung|checkliste)\b"
        )
        separator_re = re.compile(r"^\s*[━─═=\-_*•·]{6,}\s*$")
        end_marker_re = re.compile(r"^\s*[—-]?\s*ende\s*[—-]?\s*$", re.I)

        stop_rest = False
        for raw_line in lines:
            if stop_rest:
                dropped_lines.append(raw_line)
                continue

            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                cleaned_lines.append("")
                continue

            if separator_re.match(stripped) or end_marker_re.match(stripped):
                dropped_lines.append(line)
                continue

            if section_re.match(stripped):
                seen_section = True
                cleaned_lines.append(stripped)
                continue

            if seen_section and stop_heading_re.match(stripped):
                dropped_lines.append(line)
                stop_rest = True
                continue

            if not seen_section and stop_heading_re.match(stripped):
                dropped_lines.append(line)
                continue

            cleaned_lines.append(line)

        canvas = "\n".join(cleaned_lines)
        canvas = re.sub(r"\n{3,}", "\n\n", canvas).strip()

        if match and not section_re.search(canvas):
            canvas = normalized[match.start():].strip()

        note_text = "\n".join(part for part in [*notes, *dropped_lines] if part and str(part).strip()).strip() or None
        if not canvas:
            return None, note_text
        return canvas, note_text

    def _sanitize_instrumental_blueprint_text(self, text: str) -> tuple[str | None, str | None]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return None, None

        blueprint_section_re = re.compile(
            r"(?im)^\s*\[(?:\d{1,2}:\d{2}(?:\s*-\s*[^\]]+)?|intro|outro|breakdown|build(?:[- ]?up)?|drop|peak|bridge|part|section|loop|ambient|soundscape|verse|hook|chorus)[^\]]*\]\s*$"
        )
        match = blueprint_section_re.search(normalized)
        notes: list[str] = []
        blueprint_part = normalized
        if match:
            prefix = normalized[: match.start()].strip()
            if prefix:
                notes.append(prefix)
            blueprint_part = normalized[match.start():].strip()

        stop_heading_re = re.compile(
            r"(?i)^\s*(qualitätsprüfung|pipeline|reimwort|flow[- ]?plan|metrik[- ]?plan|schritt\s*\d|analyse|begründung|notizen|zusammenfassung|checkliste)\b"
        )
        separator_re = re.compile(r"^\s*[━─═=\-_*•·]{6,}\s*$")
        lyric_section_re = re.compile(r"(?im)^\s*\[(?:verse|hook|chorus|refrain|adlibs?)\b[^\]]*\]\s*$")
        lyric_hint_re = re.compile(r"(?i)\b(lyrics?|gesang|vocal lines?|rap zeilen|strophe|reime?|bars?)\b")

        cleaned_lines: list[str] = []
        dropped_lines: list[str] = []
        stop_rest = False
        for raw_line in blueprint_part.split("\n"):
            if stop_rest:
                dropped_lines.append(raw_line)
                continue
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            if separator_re.match(stripped):
                dropped_lines.append(line)
                continue
            if stop_heading_re.match(stripped):
                dropped_lines.append(line)
                stop_rest = True
                continue
            if lyric_section_re.match(stripped) and lyric_hint_re.search(stripped):
                dropped_lines.append(line)
                continue
            cleaned_lines.append(line)

        canvas = "\n".join(cleaned_lines)
        canvas = re.sub(r"\n{3,}", "\n\n", canvas).strip()
        note_text = "\n".join(part for part in [*notes, *dropped_lines] if part and str(part).strip()).strip() or None
        if not canvas:
            return None, note_text
        return canvas, note_text

    def _append_canvas_notes_to_assistant_message(self, assistant_message: str, notes: str) -> str:
        notes = (notes or "").strip()
        if not notes:
            return assistant_message or ""
        base = (assistant_message or "").strip()
        if notes in base:
            return base
        if len(notes) > 6000:
            notes = notes[:6000].rstrip() + "\n…"
        appendix = (
            "Hinweis: Ich habe Analyse-/Pipeline-Informationen aus dem Canvas herausgehalten, "
            "weil der Canvas nur den finalen Songtext oder Instrumental-Bauplan enthalten soll. Diese Infos bleiben hier im Chat:\n\n"
            f"{notes}"
        )
        return f"{base}\n\n---\n\n{appendix}".strip() if base else appendix

    def _build_missing_canvas_repair_instruction(
        self,
        *,
        user_message: str,
        canvas_content: str,
        previous_raw_response: str,
        vocal_tags: list[dict[str, Any]] | None = None,
        instruction_files: list[dict[str, Any]] | None = None,
        work_mode: str = "lyrics",
    ) -> str:
        return json.dumps(
            {
                "mode": "repair_missing_canvas_text",
                "last_user_instruction": user_message,
                "current_canvas": canvas_content or "",
                "previous_model_response_without_canvas_text": previous_raw_response or "",
                "available_vocal_tags": vocal_tags or [],
                "linked_instruction_files": instruction_files or [],
                "instrumental_blueprint_format": "Nutze im Instrumental-Bauplan-Modus vorzugsweise Abschnitte wie [0:00 - Cinematic Intro] gefolgt von eckigen Sounddesign-/Instrumentierungszeilen. Beispiel: [1:00 - Build-up] [Rising synth arpeggios, percussion acceleration, no vocals].",
                "work_mode": self._normalize_work_mode(work_mode),
                "hard_rule": (
                    "Der vorherige Aufruf war ein ausdrücklicher Canvas-Ausführungsbefehl, aber canvas_text fehlte oder war leer. "
                    "Nutze den bisherigen Chatverlauf als Arbeitsgedächtnis. Wenn dort ein vollständiger Songtext, ein vollständiger Instrumental-Bauplan, ein Entwurf oder eine klare finale Version erarbeitet wurde, "
                    "übernimm diese vollständig in canvas_text. Wenn der Nutzer 'einfügen', 'übernehmen', 'in den Canvas' oder ähnlich geschrieben hat, "
                    "muss canvas_text den vollständigen einzufügenden Canvas enthalten. Im Songtext-Modus darf canvas_text nur finalen Songtext enthalten. Im Instrumental-Bauplan-Modus darf canvas_text nur Timecode-/Arrangement-/Sounddesign-Bauplan ohne Lyrics enthalten. Pipeline, Reimbank, Flow-Plan und Analyse bleiben in assistant_message. Behaupte niemals, dass etwas eingefügt wurde, ohne canvas_text zu liefern."
                ),
                "expected_output": {
                    "assistant_message": "kurze ehrliche Chat-Antwort",
                    "canvas_text": "vollständiger Canvas als Text oder null, wenn wirklich kein Canvas rekonstruierbar ist",
                    "change_summary": "kurze Zusammenfassung oder null",
                    "suggested_title": "optional",
                },
            },
            ensure_ascii=False,
        )

    async def run_json_task(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        instruction_payload: dict[str, Any],
        profile_options: dict[str, Any] | None = None,
    ) -> AiJsonResult:
        provider_key, model_key, api_model = self.validate_provider_model(provider, model)
        profile_options = profile_options or {}
        instruction = json.dumps(instruction_payload, ensure_ascii=False)
        strict_system_prompt = (
            f"{system_prompt.strip()}\n\n"
            "Antworte ausschließlich als gültiges JSON-Objekt ohne Markdown, ohne Codeblock und ohne erklärenden Fließtext außerhalb des JSON."
        )

        if provider_key == "openai":
            raw_text, raw = await self._call_openai(api_model, instruction, [], strict_system_prompt, profile_options)
        elif provider_key == "openrouter":
            raw_text, raw = await self._call_openrouter(api_model, instruction, [], strict_system_prompt, profile_options)
        elif provider_key == "gemini":
            raw_text, raw = await self._call_gemini(api_model, instruction, [], strict_system_prompt, profile_options)
        elif provider_key == "groq":
            raw_text, raw = await self._call_groq(api_model, instruction, [], strict_system_prompt, profile_options)
        else:
            raise AiProviderError("Unbekannter KI-Provider.")

        parsed = self._parse_json_response(raw_text)
        return AiJsonResult(
            data=parsed,
            raw_text=raw_text,
            raw_response=self._build_raw_response_snapshot(
                provider_key=provider_key,
                model_key=model_key,
                api_model=api_model,
                profile_options=profile_options,
                raw=raw,
                parsed=parsed,
                raw_text=raw_text,
                allow_canvas_changes=False,
                work_mode="json_task",
                repaired=False,
            ),
        )

    def _build_system_prompt(self, extra_instruction: str | None = None) -> str:
        extra = (extra_instruction or "").strip()
        if not extra:
            return SYSTEM_PROMPT
        return f"{SYSTEM_PROMPT}\n\nZusätzliche Admin-Systemanweisung:\n{extra}\n"

    def _build_user_instruction(
        self,
        user_message: str,
        canvas_content: str,
        vocal_tags: list[dict[str, Any]] | None = None,
        instruction_files: list[dict[str, Any]] | None = None,
        *,
        allow_canvas_changes: bool = True,
        work_mode: str = "lyrics",
    ) -> str:
        return json.dumps(
            {
                "mode": "execute_on_canvas" if allow_canvas_changes else "free_conversation",
                "work_mode": self._normalize_work_mode(work_mode),
                "work_mode_rule": (
                    "Songtext-Modus: Canvas ist nur für finalen Songtext mit Vocal Tags, Sektionen, Lyrics und kurzen Performance-Hinweisen."
                    if self._normalize_work_mode(work_mode) == "lyrics"
                    else "Instrumental-Bauplan-Modus: Canvas ist nur für instrumental nutzbare Timecode-Abschnitte, Arrangement, Instrumentierung, Sounddesign, Drops, Builds, Breakdowns und Outro. Keine Lyrics und keine gesungenen Zeilen."
                ),
                "user_instruction": user_message,
                "current_canvas": canvas_content or "",
                "available_vocal_tags": vocal_tags or [],
                "linked_instruction_files": instruction_files or [],
                "instrumental_blueprint_format": "Nutze im Instrumental-Bauplan-Modus vorzugsweise Abschnitte wie [0:00 - Cinematic Intro] gefolgt von eckigen Sounddesign-/Instrumentierungszeilen. Beispiel: [1:00 - Build-up] [Rising synth arpeggios, percussion acceleration, no vocals].",
                "instruction_file_rule": "Behandle verlinkte Instruction-Dateien wie GPT Knowledge/Instructions. Nutze sie aktiv, aber kopiere sie nicht unnötig vollständig in die Antwort.",
                "vocal_tag_instruction": "Nutze passende Vocal Tags intelligent, wenn sie zur Aufgabe passen. Erfinde keine Tag-Syntax, wenn passende Tags vorhanden sind.",
                "decision_rule": (
                    "Freie Konversation: Antworte intelligent im Chat, diskutiere Optionen und sammle Entscheidungen. "
                    "Wenn der Nutzer Inhalte, Zeilen, Punchlines, eine Reimbank, einen Hook, einen Instrumental-Bauplan, Soundideen oder einen vollständigen Entwurf wünscht, liefere diese Inhalte vollständig in assistant_message. "
                    "Setze canvas_text zwingend auf null und führe keine Canvas-Änderung aus. "
                    "Behaupte nicht, dass ein Text erstellt wurde, wenn du ihn nicht sichtbar im assistant_message ausgibst."
                    if not allow_canvas_changes
                    else
                    "Ausführung am Canvas: Nutze den gesamten Chatverlauf, die Admin-Anweisungen, verlinkte Dateien und den aktuellen Canvas. "
                    "Führe den konkreten Nutzerbefehl aus und gib den vollständigen neuen Canvas in canvas_text zurück. "
                    "Im Songtext-Modus darf canvas_text ausschließlich Songtext enthalten: Vocal Tags, Sektionen, Lyrics, kurze Adlibs/Performance-Hinweise. "
                    "Im Instrumental-Bauplan-Modus darf canvas_text ausschließlich den finalen Instrumental-Bauplan enthalten: Timecodes, Arrangement, Instrumentierung, Sounddesign, Energieverlauf, Drops, Breakdowns, Builds und Outro; keine Lyrics. "
                    "Reimbanken, Pipeline-Überschriften, Flow-Pläne, Qualitätschecks, Erklärungen und Fragen gehören in assistant_message, niemals in canvas_text. "
                    "Wenn der Nutzer nur 'einfügen', 'übernehmen' oder ähnlich schreibt, beziehe dich auf die zuletzt im Chat erarbeitete vollständige Version. "
                    "Wenn du keinen vollständigen Canvas liefern kannst, setze canvas_text auf null und sage ehrlich, dass noch Inhalt fehlt."
                ),
                "expected_output": "JSON only with assistant_message, canvas_text, change_summary, suggested_title",
            },
            ensure_ascii=False,
        )

    async def _call_openai(self, model: str, instruction: str, history: list[dict[str, str]], system_prompt: str, profile_options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "Content-Type": "application/json"}
        input_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        input_messages.extend(history[-12:])
        input_messages.append({"role": "user", "content": instruction})
        max_tokens = int(profile_options.get("max_output_tokens") or self.settings.ai_max_output_tokens)
        payload = {"model": model, "input": input_messages, "max_output_tokens": max_tokens}
        if profile_options.get("temperature") is not None:
            payload["temperature"] = float(profile_options["temperature"])
        async with httpx.AsyncClient(timeout=self.settings.ai_request_timeout_seconds) as client:
            response = await client.post(f"{self.settings.openai_base_url.rstrip('/')}/responses", headers=headers, json=payload)
        data = self._checked_response(response)
        text = data.get("output_text") or self._extract_openai_text(data)
        return text, data

    async def _call_openrouter(self, model: str, instruction: str, history: list[dict[str, str]], system_prompt: str, profile_options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.openrouter_site_url,
            "X-Title": self.settings.openrouter_app_name,
        }
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-12:])
        messages.append({"role": "user", "content": instruction})
        max_tokens = int(profile_options.get("max_output_tokens") or self.settings.ai_max_output_tokens)
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if profile_options.get("temperature") is not None:
            payload["temperature"] = float(profile_options["temperature"])
        async with httpx.AsyncClient(timeout=self.settings.ai_request_timeout_seconds) as client:
            response = await client.post(f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        data = self._checked_response(response)
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return text, data

    async def _call_groq(self, model: str, instruction: str, history: list[dict[str, str]], system_prompt: str, profile_options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.settings.groq_api_key}", "Content-Type": "application/json"}
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-12:])
        messages.append({"role": "user", "content": instruction})
        max_tokens = int(profile_options.get("max_output_tokens") or self.settings.ai_max_output_tokens)
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if profile_options.get("temperature") is not None:
            payload["temperature"] = float(profile_options["temperature"])
        base_url = str(getattr(self.settings, "groq_base_url", "") or "https://api.groq.com/openai/v1").rstrip("/")
        if not base_url.endswith("/openai/v1"):
            base_url = f"{base_url.rstrip('/')}/openai/v1"
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_request_timeout_seconds) as client:
                response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise AiProviderError("Groq API Zeitüberschreitung beim Chat-/Textaufruf.") from exc
        except httpx.HTTPError as exc:
            raise AiProviderError(f"Groq API ist nicht erreichbar: {exc}") from exc
        data = self._checked_response(response, provider_name="Groq")
        choices = data.get("choices") if isinstance(data, dict) else None
        message = (choices or [{}])[0].get("message", {}) if isinstance(choices, list) else {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        if isinstance(content, list):
            text = "".join(str(item.get("text", "") if isinstance(item, dict) else item) for item in content)
        else:
            text = str(content or "")
        return text, data

    async def _call_gemini(self, model: str, instruction: str, history: list[dict[str, str]], system_prompt: str, profile_options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        url = f"{self.settings.gemini_base_url.rstrip('/')}/models/{model}:generateContent"
        params = {"key": self.settings.gemini_api_key}
        history_text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in history[-12:])
        prompt = f"{system_prompt}\n\nBisheriger Chat:\n{history_text}\n\nAktuelle Aufgabe:\n{instruction}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": int(profile_options.get("max_output_tokens") or self.settings.ai_max_output_tokens)},
        }
        if profile_options.get("temperature") is not None:
            payload["generationConfig"]["temperature"] = float(profile_options["temperature"])
        async with httpx.AsyncClient(timeout=self.settings.ai_request_timeout_seconds) as client:
            response = await client.post(url, params=params, json=payload)
        data = self._checked_response(response)
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return text, data

    def _checked_response(self, response: httpx.Response, provider_name: str = "KI-Provider") -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            if not message and isinstance(data, dict):
                message = data.get("message") or data.get("detail") or data.get("raw")
            detail = str(message or f"{provider_name} Fehler {response.status_code}")
            if code and str(code) not in detail:
                detail = f"{detail} ({code})"
            raise AiProviderError(detail)
        return data

    def _extract_openai_text(self, data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts).strip()

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        for candidate in self._json_candidates(cleaned):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            parsed = self._coerce_json_result(parsed)
            if parsed:
                return parsed

        return {"assistant_message": cleaned, "canvas_text": None, "change_summary": None}

    def _json_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []
        cleaned = (text or "").strip()
        if not cleaned:
            return candidates
        candidates.append(cleaned)

        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.I | re.S)
        candidates.extend(fenced)

        balanced = self._extract_balanced_json_object(cleaned)
        if balanced:
            candidates.append(balanced)

        unique: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        return unique

    def _extract_balanced_json_object(self, text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    def _parse_embedded_json_object(self, text: str) -> dict[str, Any] | None:
        for candidate in self._json_candidates(text):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            coerced = self._coerce_json_result(parsed)
            if coerced:
                return coerced
        return None

    def _coerce_json_result(self, parsed: Any) -> dict[str, Any] | None:
        if isinstance(parsed, dict):
            nested_message = parsed.get("assistant_message")
            if isinstance(nested_message, str):
                nested = self._parse_embedded_json_object(nested_message)
                if nested and nested is not parsed:
                    merged = {**parsed, **{key: value for key, value in nested.items() if value is not None}}
                    return merged
            return parsed
        if isinstance(parsed, str):
            nested = self._parse_embedded_json_object(parsed)
            if nested:
                return nested
            return {"assistant_message": parsed, "canvas_text": None, "change_summary": None}
        return None
