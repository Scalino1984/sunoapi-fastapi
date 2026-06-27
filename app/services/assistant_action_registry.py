from __future__ import annotations

from typing import Any

ACTION_REGISTRY: dict[str, dict[str, Any]] = {
    "navigate_home": {"id": "navigate_home", "label": "Zur Startseite", "type": "frontend", "requires_confirmation": False},
    "navigate_library": {"id": "navigate_library", "label": "Library öffnen", "type": "frontend", "requires_confirmation": False},
    "navigate_lyrics": {"id": "navigate_lyrics", "label": "Songtext-Studio öffnen", "type": "frontend", "requires_confirmation": False},
    "navigate_music_wizard": {"id": "navigate_music_wizard", "label": "Neuen Song starten", "type": "frontend", "requires_confirmation": False},
    "navigate_daw": {"id": "navigate_daw", "label": "Mini-DAW öffnen", "type": "frontend", "requires_confirmation": False},
    "navigate_export": {"id": "navigate_export", "label": "Exportbereich öffnen", "type": "frontend", "requires_confirmation": False},
    "refresh_app": {"id": "refresh_app", "label": "Aktualisieren", "type": "frontend", "requires_confirmation": False},
    "play_latest_audio": {"id": "play_latest_audio", "label": "Neuesten Song abspielen", "type": "frontend", "requires_confirmation": False},
    "lyrics_create_new": {"id": "lyrics_create_new", "label": "Songtext erstellen", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_make_harder": {"id": "lyrics_make_harder", "label": "Text härter machen", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_suno_ready": {"id": "lyrics_suno_ready", "label": "Suno-ready machen", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_doubletime": {"id": "lyrics_doubletime", "label": "Doubletime prüfen", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_vocal_tags": {"id": "lyrics_vocal_tags", "label": "Vocal Tags optimieren", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_hook": {"id": "lyrics_hook", "label": "Hook verbessern", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_rhyme": {"id": "lyrics_rhyme", "label": "Reimdichte erhöhen", "type": "ai_canvas", "requires_confirmation": True},
    "lyrics_save": {"id": "lyrics_save", "label": "Songtext speichern", "type": "frontend", "requires_confirmation": False},
    "lyrics_apply_preview": {"id": "lyrics_apply_preview", "label": "Canvas-Vorschau übernehmen", "type": "frontend", "requires_confirmation": False},
    "lyrics_discard_preview": {"id": "lyrics_discard_preview", "label": "Canvas-Vorschau verwerfen", "type": "frontend", "requires_confirmation": False},
    "music_open_wizard": {"id": "music_open_wizard", "label": "Song-Wizard öffnen", "type": "frontend", "requires_confirmation": False},
    "music_generate_styles": {"id": "music_generate_styles", "label": "KI-Styles vorschlagen", "type": "frontend", "requires_confirmation": False},
    "admin_open_assistant": {"id": "admin_open_assistant", "label": "KI-Anweisungen verwalten", "type": "frontend", "requires_confirmation": False},
    "admin_create_prompt": {"id": "admin_create_prompt", "label": "Neuen Prompt-Baustein anlegen", "type": "frontend", "requires_confirmation": False},
}

PAGE_ACTION_IDS: dict[str, list[str]] = {
    "home": ["navigate_music_wizard", "lyrics_create_new", "navigate_lyrics", "navigate_library"],
    "lyrics": ["lyrics_create_new", "lyrics_make_harder", "lyrics_suno_ready", "lyrics_doubletime", "lyrics_save"],
    "library": ["play_latest_audio", "navigate_lyrics", "lyrics_create_new", "navigate_music_wizard", "navigate_daw", "navigate_export"],
    "music": ["music_generate_styles", "music_open_wizard", "lyrics_create_new", "navigate_lyrics", "navigate_library"],
    "daw": ["navigate_daw", "play_latest_audio", "refresh_app", "navigate_library"],
    "admin": ["admin_open_assistant", "admin_create_prompt"],
    "status": ["refresh_app", "navigate_library"],
    "system": ["refresh_app", "navigate_home"],
}

INTENT_ACTION_MAP: list[tuple[set[str], str]] = [
    ({"härter", "harter", "aggressiver", "druck", "punch"}, "lyrics_make_harder"),
    ({"suno", "ready", "format"}, "lyrics_suno_ready"),
    ({"style", "styles", "stil", "genre", "musikstil", "vorschlag", "vorschläge"}, "music_generate_styles"),
    ({"vocal", "tags", "tag", "delivery", "energy"}, "lyrics_vocal_tags"),
    ({"doubletime", "schneller", "triplet", "flow"}, "lyrics_doubletime"),
    ({"hook", "refrain", "chorus"}, "lyrics_hook"),
    ({"reime", "reimdichte", "binnenreim", "kettenreim"}, "lyrics_rhyme"),
    ({"speichern", "save"}, "lyrics_save"),
    ({"export", "download", "zip"}, "navigate_export"),
    ({"library", "bibliothek", "audio"}, "navigate_library"),
    ({"wizard", "workflow"}, "navigate_music_wizard"),
]

CANVAS_ACTION_PROMPTS: dict[str, str] = {
    "lyrics_create_new": "Erstelle einen komplett neuen, hochwertigen Songtext oder im Instrumentalmodus einen vollständigen Instrumental-Bauplan als Canvas-Version. Wenn der Nutzer keine Details nennt, wähle eigenständig ein starkes, modernes Suno-taugliches Konzept mit klarer Struktur.",
    "lyrics_make_harder": "Überarbeite den aktuellen Canvas härter, direkter, druckvoller und intensiver. Bewahre Thema, Perspektive und Struktur. Gib eine vollständige neue Canvas-Version zurück.",
    "lyrics_suno_ready": "Formatiere den aktuellen Canvas Suno-kompatibel mit klaren Sections, sinnvollen Vocal-/Sound-/Energy-Hinweisen und sauberer Struktur. Bewahre Inhalt und Stimmung.",
    "lyrics_doubletime": "Prüfe und überarbeite geeignete Stellen für Doubletime-Rap. Achte auf kurze Silbenketten, Atempausen, klare Taktbarkeit und saubere Sections. Gib eine vollständige neue Canvas-Version zurück.",
    "lyrics_hook": "Verbessere vor allem Hook/Refrain-Stellen mit mehr Wiedererkennungswert, klarerer Melodieidee und stärkerer Wirkung. Bewahre die übrigen Parts möglichst stabil.",
    "lyrics_rhyme": "Erhöhe die Reimdichte mit Binnenreimen, Doppelreimen, Kettenreimen und sauberem Flow. Bewahre Inhalt, Stimme und Struktur.",
    "lyrics_vocal_tags": "Bearbeite gezielt Vocal Tags, Delivery-, Energy- und Section-Hinweise. Ergänze oder ändere Tags sauber, ohne den Songtext unnötig umzuschreiben.",
}


def clone_action(action_id: str, *, label: str | None = None, action_type: str | None = None, requires_confirmation: bool | None = None) -> dict[str, Any]:
    base = dict(ACTION_REGISTRY.get(action_id) or {})
    if not base:
        base = {
            "id": action_id,
            "label": label or action_id.replace("_", " ").title(),
            "type": action_type or ("ai_canvas" if action_id.startswith("lyrics_") else "frontend"),
            "requires_confirmation": bool(requires_confirmation) if requires_confirmation is not None else action_id.startswith("lyrics_"),
        }
    if label is not None:
        base["label"] = label
    if action_type is not None:
        base["type"] = action_type
    if requires_confirmation is not None:
        base["requires_confirmation"] = bool(requires_confirmation)
    return base


def normalize_actions(actions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in actions or []:
        if not isinstance(item, dict):
            continue
        action_id = str(item.get("id") or "").strip()
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        result.append(
            clone_action(
                action_id,
                label=str(item.get("label") or "").strip() or None,
                action_type=str(item.get("type") or "").strip() or None,
                requires_confirmation=item.get("requires_confirmation") if "requires_confirmation" in item else None,
            )
        )
    return result


def default_actions_for_page(active_tab: str | None) -> list[dict[str, Any]]:
    key = str(active_tab or "").lower().strip()
    ids = PAGE_ACTION_IDS.get(key) or ["navigate_home", "lyrics_create_new", "navigate_lyrics", "navigate_library"]
    return [clone_action(action_id) for action_id in ids]


def detect_action_by_keywords(message: str, active_tab: str | None = None) -> str | None:
    text = (message or "").lower()
    for keywords, action_id in INTENT_ACTION_MAP:
        if any(keyword in text for keyword in keywords):
            if action_id.startswith("lyrics_") and str(active_tab or "").lower() not in {"lyrics", "home", "music", "library"}:
                return "navigate_lyrics"
            return action_id
    return None
