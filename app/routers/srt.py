from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.srt_parser import export_srt, parse_srt, renumber_segments
from app.services.srt_validation import validate_srt_segments

router = APIRouter(prefix="/api/srt", tags=["srt"])


class SrtSegmentsPayload(BaseModel):
    segments: list[dict[str, Any]] = Field(default_factory=list)


class SrtRawPayload(BaseModel):
    srt: str = ""


@router.post("/validate")
def validate_srt(payload: SrtSegmentsPayload) -> dict[str, Any]:
    return validate_srt_segments(payload.segments)


@router.post("/export")
def export_srt_from_segments(payload: SrtSegmentsPayload) -> dict[str, Any]:
    result = validate_srt_segments(payload.segments)
    if not result["valid"]:
        raise HTTPException(status_code=422, detail={"message": "SRT-Segmente sind ungültig.", "issues": result["issues"]})
    return {"srt": export_srt(result["segments"]), "segments": result["segments"], "issues": result["issues"]}


@router.post("/parse")
def parse_raw_srt(payload: SrtRawPayload) -> dict[str, Any]:
    segments = parse_srt(payload.srt)
    result = validate_srt_segments(segments)
    return {"segments": result["segments"], "issues": result["issues"], "valid": result["valid"]}
