from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SunoTask
from app.schemas import AuditApplyRequest, AuditRunRequest
from app.services.audit_registry_service import list_audit_checks
from app.services.audit_runner_service import serialize_audit_task, start_audit_task, start_repair_task
from app.services.task_lifecycle_service import request_task_cancel

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/checks")
def audit_checks() -> dict:
    return {"items": list_audit_checks()}


@router.get("/runs")
def audit_runs(
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(SunoTask)
        .filter(SunoTask.is_deleted.is_(False), SunoTask.task_type.in_(["maintenance_audit", "maintenance_repair"]))
        .order_by(SunoTask.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [serialize_audit_task(row, include_result=False) for row in rows]}


@router.post("/runs", status_code=202)
def create_audit_run(payload: AuditRunRequest, db: Session = Depends(get_db)) -> dict:
    try:
        task = start_audit_task(db, payload.check_ids, payload.parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"accepted": True, "task_local_id": task.id, "status": task.status, "task": serialize_audit_task(task)}


@router.get("/runs/{task_id}")
def read_audit_run(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = (
        db.query(SunoTask)
        .filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False), SunoTask.task_type.in_(["maintenance_audit", "maintenance_repair"]))
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Audit-Lauf nicht gefunden.")
    return serialize_audit_task(task)


@router.get("/runs/{task_id}/report")
def read_audit_report(task_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    task = (
        db.query(SunoTask)
        .filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False), SunoTask.task_type.in_(["maintenance_audit", "maintenance_repair"]))
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Audit-Lauf nicht gefunden.")
    if not isinstance(task.result_payload, dict) or not task.result_payload:
        raise HTTPException(status_code=409, detail="Für diesen Lauf liegt noch kein Report vor.")
    return JSONResponse(content=task.result_payload, headers={"Content-Disposition": f'attachment; filename="audit_run_{task.id}.json"'})


@router.post("/runs/{task_id}/apply", status_code=202)
def apply_audit_run(task_id: int, payload: AuditApplyRequest, db: Session = Depends(get_db)) -> dict:
    if payload.confirm.strip().upper() != "REPARATUR ANWENDEN":
        raise HTTPException(status_code=400, detail='Bestätigungstext muss "REPARATUR ANWENDEN" lauten.')
    try:
        task = start_repair_task(db, task_id, repair_actions=payload.repair_actions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"accepted": True, "task_local_id": task.id, "source_audit_task_id": task_id, "status": task.status, "task": serialize_audit_task(task)}


@router.post("/runs/{task_id}/cancel")
def cancel_audit_run(task_id: int, db: Session = Depends(get_db)) -> dict:
    existing = (
        db.query(SunoTask)
        .filter(
            SunoTask.id == task_id,
            SunoTask.is_deleted.is_(False),
            SunoTask.task_type.in_(["maintenance_audit", "maintenance_repair"]),
        )
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Audit-Lauf nicht gefunden.")
    task = request_task_cancel(db, task_id, reason="Audit/Wartung wurde manuell abgebrochen.")
    return {"ok": True, "task": serialize_audit_task(task)}
