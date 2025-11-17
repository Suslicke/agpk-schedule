import logging
import uuid
from io import BytesIO
from typing import Dict, Optional

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app import schemas
from app.core.database import SessionLocal, get_db
from app.core.security import require_admin
from app.services import crud
from app.services import day_planning_service as day_svc
from app.services import schedule_service as sched_svc

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)


# --- Upload ---
@router.post("/upload/schedule", summary="[ADMIN] Upload Excel with base schedule items")
async def admin_upload_schedule(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Only .xlsx files allowed")
    content = await file.read()
    df = pd.read_excel(BytesIO(content), sheet_name="Нагрузка ООД")
    logger.info("[ADMIN] Upload schedule file: %s", file.filename)
    items = crud.parse_and_create_schedule_items(db, df)
    return {"created_items": len(items)}


# --- Day planning ---
@router.post(
    "/day/plan",
    response_model=schemas.DayPlanResponse,
    summary="[ADMIN] Create day plan from weekly plan",
)
def admin_plan_day(request: schemas.DayPlanCreateRequest, db: Session = Depends(get_db)):
    try:
        ds = day_svc.plan_day_schedule(db, request)
        if request.auto_vacant_remove:
            day_svc.replace_vacant_auto(db, ds.id)
        try:
            from app.services import crud as _legacy_crud
            reasons = _legacy_crud.get_last_plan_debug(ds.id, clear=True) if request.debug else None
        except Exception:
            reasons = None
        return day_svc.get_day_schedule(db, request.date, request.group_name, reasons)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/approve",
    response_model=Dict,
    summary="[ADMIN] Approve day plan (whole day or group)",
)
def admin_approve_day(
    day_id: int,
    group_name: Optional[str] = Query(None),
    record_progress: bool = Query(True),
    enforce_no_blockers: bool = Query(False),
    db: Session = Depends(get_db),
):
    try:
        if enforce_no_blockers:
            pre = day_svc.analyze_day_schedule(db, day_id, group_name=group_name)
            if pre.get("blockers_count", 0) > 0:
                raise ValueError("Approval blocked: blockers present. Request report via /schedule/day/{day_id}/report")
        result = day_svc.approve_day_schedule(db, day_id, group_name=group_name, record_progress=record_progress)
        result["report"] = day_svc.analyze_day_schedule(db, day_id, group_name=group_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/replace_vacant_auto",
    response_model=Dict,
    summary="[ADMIN] Auto-replace vacant teachers",
)
def admin_replace_vacant_auto(day_id: int, db: Session = Depends(get_db)):
    try:
        return day_svc.replace_vacant_auto(db, day_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/replace_entry_manual",
    response_model=Dict,
    summary="[ADMIN] Manually replace entry teacher",
)
def admin_replace_entry_manual(req: schemas.ReplaceEntryManualRequest, db: Session = Depends(get_db)):
    try:
        return day_svc.replace_entry_manual(db, req.entry_id, req.teacher_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/update_entry_manual",
    response_model=Dict,
    summary="[ADMIN] Manually update entry teacher/subject/room",
)
def admin_update_entry_manual(req: schemas.UpdateEntryManualRequest, db: Session = Depends(get_db)):
    try:
        return day_svc.update_entry_manual(
            db,
            req.entry_id,
            teacher_name=req.teacher_name,
            subject_name=req.subject_name,
            room_name=req.room_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/bulk_update_strict",
    response_model=schemas.BulkUpdateStrictResponse,
    summary="[ADMIN] Bulk update the whole day (strict)",
)
def admin_bulk_update_strict(day_id: int, req: schemas.BulkUpdateStrictRequest, db: Session = Depends(get_db)):
    try:
        result = day_svc.bulk_update_day_entries_strict(db, day_id, req.items, dry_run=bool(req.dry_run))
        return schemas.BulkUpdateStrictResponse(
            updated=result["updated"],
            skipped=result["skipped"],
            errors=result["errors"],
            results=[schemas.BulkUpdateStrictResultItem(**r) for r in result["results"]],
            report=schemas.DayReport.model_validate(result["report"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Generate semester ---
@router.post(
    "/schedule/generate_semester",
    summary="[ADMIN] Generate schedules for a semester (background by default)",
)
def admin_generate_semester(request: schemas.GenerateScheduleRequest, background: BackgroundTasks):
    # Inline-duplicate logic to avoid tight coupling to public router
    from app.api.routers.schedule import _background_generate_semester, _generation_jobs
    try:
        async_mode = True if request.async_mode is None else bool(request.async_mode)
        if async_mode:
            job_id = str(uuid.uuid4())
            _generation_jobs[job_id] = {"status": "pending"}
            background.add_task(_background_generate_semester, job_id, request)
            return {"job_id": job_id, "status": "accepted"}
        db = SessionLocal()
        gens = sched_svc.generate_schedule(db, request)
        resp = [sched_svc.get_generated_schedule(db, g.id) for g in gens]
        db.close()
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
