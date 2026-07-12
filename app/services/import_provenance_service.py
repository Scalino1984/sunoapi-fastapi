"""Herkunftsschutz für bestehende SunoAPI.org-Tasks.

Ein manueller Importversuch darf eine bereits über die lokale App erzeugte Task
nicht nachträglich als ``manual_sunoapi_import`` kennzeichnen. Die Funktionen in
diesem Modul sind absichtlich rein und werden sowohl vom Import-Service als auch
vom Audit-/Reparaturskript verwendet.
"""

from __future__ import annotations

from typing import Any


MANUAL_SUNOAPI_IMPORT_SOURCE = "manual_sunoapi_import"
LOCAL_GENERATION_CALLBACK_KEYS = (
    "callback_url",
    "callBackUrl",
    "call_back_url",
)


def payload_source(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("source") or "").strip().lower()


def is_manual_sunoapi_import_payload(payload: Any) -> bool:
    return payload_source(payload) == MANUAL_SUNOAPI_IMPORT_SOURCE


def has_local_generation_evidence(
    *,
    task_type: str | None,
    request_payload: Any,
    response_payload: Any,
) -> bool:
    """Erkennt nur belastbare Hinweise auf eine lokale App-Generierung.

    Der Callback wird von den regulären Generierungswegen der App vor dem
    Provider-Aufruf ergänzt. Der manuelle Task-ID-Import erzeugt diesen Wert
    nicht. Dadurch bleibt die Erkennung konservativ und überschreibt keine
    echten Altimporte nur aufgrund ähnlicher Generierungsoptionen.
    """

    request = request_payload if isinstance(request_payload, dict) else {}
    response = response_payload if isinstance(response_payload, dict) else {}
    normalized_task_type = str(task_type or "").strip().lower()

    if normalized_task_type == "generate_music_opencli":
        return True
    if bool(request.get("local_task")):
        return True
    if any(str(request.get(key) or "").strip() for key in LOCAL_GENERATION_CALLBACK_KEYS):
        return True

    response_source = payload_source(response)
    response_provider = str(response.get("provider") or "").strip().lower()
    if response_source in {"opencli", "local"} or response_provider == "opencli":
        return True

    return False


def is_confirmed_manual_sunoapi_import(
    *,
    task_type: str | None,
    request_payload: Any,
    response_payload: Any,
) -> bool:
    """Bestätigt einen manuellen Import, ohne lokale Tasks falsch einzuordnen."""

    if is_manual_sunoapi_import_payload(response_payload):
        return True
    if not is_manual_sunoapi_import_payload(request_payload):
        return False
    return not has_local_generation_evidence(
        task_type=task_type,
        request_payload=request_payload,
        response_payload=response_payload,
    )


def has_false_manual_sunoapi_import_marker(
    *,
    task_type: str | None,
    request_payload: Any,
    response_payload: Any,
) -> bool:
    return is_manual_sunoapi_import_payload(request_payload) and not is_confirmed_manual_sunoapi_import(
        task_type=task_type,
        request_payload=request_payload,
        response_payload=response_payload,
    )


def strip_manual_sunoapi_import_source(payload: Any) -> dict[str, Any]:
    """Entfernt ausschließlich die falsche Herkunftsmarkierung.

    Alle Generierungsoptionen, Providerdetails, IDs, Cache-Flags und sonstigen
    Metadaten bleiben unverändert erhalten.
    """

    cleaned = dict(payload) if isinstance(payload, dict) else {}
    if is_manual_sunoapi_import_payload(cleaned):
        cleaned.pop("source", None)
    return cleaned
