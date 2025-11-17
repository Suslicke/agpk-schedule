import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from app.services import schedule_service as sched_svc
from app.services import day_planning_service as day_svc
from app import schemas
from app.core.database import get_db, SessionLocal
from datetime import datetime, date
from typing import List, Dict, Optional
from app.core.security import require_admin

router = APIRouter(prefix="/schedule", tags=["schedule"])
logger = logging.getLogger(__name__)


@router.get(
    "/query",
    response_model=schemas.ScheduleQueryResponse,
    summary="Query schedule by date/range with optional filters",
    tags=["schedule"],
)
def query_schedule(
    date: Optional[str] = Query(None, description="Single date YYYY-MM-DD"),
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    group_name: Optional[str] = Query(None, description="Filter by group name"),
    teacher_name: Optional[str] = Query(None, description="Filter by teacher name"),
    db: Session = Depends(get_db),
):
    """
    Unified schedule query endpoint.

    Usage examples:
    - /schedule/query?date=2025-12-23 — full schedule for a single date
    - /schedule/query?start_date=2025-12-22&end_date=2025-12-31 — schedule for date range
    - /schedule/query?start_date=2025-12-22&end_date=2025-12-31&group_name=Group1 — range filtered by group
    - /schedule/query?teacher_name=Ivanov I.I. — full schedule for teacher across all dates

    If neither date nor range is provided, returns the full available schedule.
    """
    try:
        d = None
        sd = None
        ed = None
        if date:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        if start_date:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        if end_date:
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        logger.info(
            "Query schedule: date=%s, start=%s, end=%s, group=%s, teacher=%s",
            d,
            sd,
            ed,
            group_name,
            teacher_name,
        )
        items = sched_svc.query_schedule(
            db,
            date_=d,
            start_date=sd,
            end_date=ed,
            group_name=group_name,
            teacher_name=teacher_name,
        )
        return schemas.ScheduleQueryResponse(items=items)
    except ValueError as e:
        logger.warning("Schedule query failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


_generation_jobs: dict[str, dict] = {}


def _background_generate_semester(job_id: str, request: schemas.GenerateScheduleRequest):
    logger.info("[GEN %s] Background semester generation started: %s -> %s, semester=%s, group=%s", job_id, request.start_date, request.end_date, request.semester, request.group_name or "ALL")
    db = SessionLocal()
    try:
        gens = sched_svc.generate_schedule(db, request)
        resp = [sched_svc.get_generated_schedule(db, g.id) for g in gens]
        _generation_jobs[job_id] = {"status": "done", "result": resp}
        logger.info("[GEN %s] Done. Generated %d schedules", job_id, len(resp))
    except Exception as e:
        _generation_jobs[job_id] = {"status": "error", "error": str(e)}
        logger.warning("[GEN %s] Failed: %s", job_id, e)
    finally:
        db.close()


@router.post(
    "/generate_semester",
    summary="Generate schedules for a semester (background by default)",
    tags=["schedule"],
)
def generate_semester_endpoint(request: schemas.GenerateScheduleRequest, background: BackgroundTasks, _: bool = Depends(require_admin)):
    try:
        async_mode = True if request.async_mode is None else bool(request.async_mode)
        if async_mode:
            job_id = str(uuid.uuid4())
            _generation_jobs[job_id] = {"status": "pending"}
            background.add_task(_background_generate_semester, job_id, request)
            logger.info("Generate semester accepted, job_id=%s", job_id)
            return {"job_id": job_id, "status": "accepted"}
        # sync mode
        logger.info("Generate semester (sync): %s -> %s, semester=%s, group=%s", request.start_date, request.end_date, request.semester, request.group_name or "ALL")
        db = SessionLocal()
        gens = sched_svc.generate_schedule(db, request)
        resp = [sched_svc.get_generated_schedule(db, g.id) for g in gens]
        db.close()
        logger.info("Generated %d schedules", len(resp))
        return resp
    except ValueError as e:
        logger.warning("Generate semester failed: %s", e)
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/generate_semester/status/{job_id}",
    summary="Get background semester generation status",
    tags=["schedule"],
)
def generate_semester_status(job_id: str):
    job = _generation_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job



# --- Day plan (1 day ahead) ---
@router.post(
    "/day/plan",
    response_model=schemas.DayPlanResponse,
    summary="Create day plan from weekly plan (all groups by default)",
    tags=["day_plan"],
)
def plan_day(request: schemas.DayPlanCreateRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info(
            "Plan day: date=%s, group=%s, from_plan=%s, auto_vacant_remove=%s",
            request.date,
            request.group_name,
            request.from_plan,
            request.auto_vacant_remove,
        )
        ds = day_svc.plan_day_schedule(db, request)
        if request.auto_vacant_remove:
            day_svc.replace_vacant_auto(db, ds.id)
        # Prepare debug reasons if requested
        reasons = None
        if request.debug:
            try:
                # Reuse debug notes from legacy storage if available
                from app.services import crud as _legacy_crud
                reasons = _legacy_crud.get_last_plan_debug(ds.id, clear=True)
            except Exception:
                reasons = None
        # Return only the requested group if provided; otherwise full day
        return day_svc.get_day_schedule(db, request.date, request.group_name, reasons)
    except ValueError as e:
        logger.warning("Plan day failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/day/entry/{entry_id}/options",
    summary="Get replacement options (teachers/rooms) for a day entry",
    tags=["day_plan"],
)
def get_entry_options(entry_id: int, limit_teachers: int = 20, limit_rooms: int = 20, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        opts = day_svc.get_entry_replacement_options(db, entry_id, limit_teachers=limit_teachers, limit_rooms=limit_rooms)
        return opts
    except ValueError as e:
        logger.warning("Get entry options failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/day/entry/{entry_id}/room_swap_plan",
    summary="Propose a room swap plan to free a busy room for entry",
    tags=["day_plan"],
)
def room_swap_plan(entry_id: int, desired_room_name: str, limit_alternatives: int = 5, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        plan = day_svc.propose_room_swap(db, entry_id, desired_room_name, limit_alternatives=limit_alternatives)
        return plan
    except ValueError as e:
        logger.warning("Room swap plan failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/day/entry/{entry_id}/teacher_swap_plan",
    summary="Propose a teacher swap plan to free a busy teacher for entry",
    tags=["day_plan"],
)
def teacher_swap_plan(entry_id: int, desired_teacher_name: str, limit_alternatives: int = 5, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        plan = day_svc.propose_teacher_swap(db, entry_id, desired_teacher_name, limit_alternatives=limit_alternatives)
        return plan
    except ValueError as e:
        logger.warning("Teacher swap plan failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/entry/{entry_id}/swap_teacher",
    summary="Execute teacher swap (reassign conflicting entries then set desired teacher)",
    tags=["day_plan"],
)
def swap_teacher(entry_id: int, req: schemas.SwapTeacherRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        result = day_svc.execute_teacher_swap(db, entry_id, req.desired_teacher_name, choices=req.choices or [], dry_run=bool(req.dry_run))
        return result
    except ValueError as e:
        logger.warning("Swap teacher failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/entry/{entry_id}/swap_room",
    summary="Execute room swap (reassign conflicting entries then set desired room)",
    tags=["day_plan"],
)
def swap_room(entry_id: int, req: schemas.SwapRoomRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        result = day_svc.execute_room_swap(db, entry_id, req.desired_room_name, choices=req.choices or [], dry_run=bool(req.dry_run))
        return result
    except ValueError as e:
        logger.warning("Swap room failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/entry/{entry_id}/clear_room",
    summary="Clear room for an entry (mark as empty placeholder)",
    tags=["day_plan"],
)
def clear_room(entry_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        result = day_svc.clear_entry_room(db, entry_id)
        return result
    except ValueError as e:
        logger.warning("Clear room failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/day",
    response_model=schemas.DayPlanResponse,
    summary="Get day plan by date",
    tags=["day_plan"],
)
def get_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    group_name: Optional[str] = Query(None, description="Filter by group name"),
    db: Session = Depends(get_db),
):
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
        logger.info("Get day: %s", d)
        return day_svc.get_day_schedule(db, d, group_name)
    except ValueError as e:
        logger.warning("Get day failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/approve",
    response_model=Dict,
    summary="Approve day plan (locks entries). Can approve whole day or a single group and record progress.",
    tags=["day_plan"],
)
def approve_day(
    day_id: int,
    group_name: Optional[str] = Query(None, description="Approve only this group within the day"),
    record_progress: bool = Query(True, description="Create SubjectProgress entries for approved pairs"),
    enforce_no_blockers: bool = Query(False, description="If true, abort approval when blockers are detected"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    try:
        logger.info("Approve day id=%s group=%s record_progress=%s", day_id, group_name, record_progress)
        if enforce_no_blockers:
            pre = day_svc.analyze_day_schedule(db, day_id, group_name=group_name)
            if pre.get("blockers_count", 0) > 0:
                raise ValueError("Approval blocked: blockers present. Request report via /schedule/day/{day_id}/report")
        result = day_svc.approve_day_schedule(db, day_id, group_name=group_name, record_progress=record_progress)
        # Attach validation report after approval for visibility
        report = day_svc.analyze_day_schedule(db, day_id, group_name=group_name)
        result["report"] = report
        return result
    except ValueError as e:
        logger.warning("Approve day failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/replace_vacant_auto",
    response_model=Dict,
    summary="Auto-replace vacant teachers by availability",
    tags=["day_plan"],
)
def replace_vacant_auto(day_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info("Replace vacant auto day_id=%s", day_id)
        return day_svc.replace_vacant_auto(db, day_id)
    except ValueError as e:
        logger.warning("Replace vacant auto failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/replace_entry_manual",
    response_model=Dict,
    summary="Manually replace entry teacher",
    tags=["day_plan"],
)
def replace_entry_manual(req: schemas.ReplaceEntryManualRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info("Replace entry manual id=%s -> teacher=%s", req.entry_id, req.teacher_name)
        return day_svc.replace_entry_manual(db, req.entry_id, req.teacher_name)
    except ValueError as e:
        logger.warning("Replace entry manual failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/day/{day_id}/report",
    response_model=schemas.DayReport,
    summary="Validation report for a day plan (stats, issues, blockers)",
    tags=["day_plan"],
)
def get_day_report(
    day_id: int,
    group_name: Optional[str] = Query(None, description="Filter report to a specific group"),
    db: Session = Depends(get_db),
):
    try:
        logger.info("Day report id=%s group=%s", day_id, group_name)
        report = day_svc.analyze_day_schedule(db, day_id, group_name=group_name)
        return schemas.DayReport.model_validate(report)
    except ValueError as e:
        logger.warning("Day report failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/update_entry_manual",
    response_model=Dict,
    summary="Manually update an entry (teacher/subject/room) with validation report",
    tags=["day_plan"],
)
def update_entry_manual(req: schemas.UpdateEntryManualRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info(
            "Update entry manual id=%s teacher=%s subject=%s room=%s",
            req.entry_id,
            req.teacher_name,
            req.subject_name,
            req.room_name,
        )
        return day_svc.update_entry_manual(
            db,
            req.entry_id,
            teacher_name=req.teacher_name,
            subject_name=req.subject_name,
            room_name=req.room_name,
        )
    except ValueError as e:
        logger.warning("Update entry manual failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/add_entry_manual",
    response_model=Dict,
    summary="Manually add a new day entry (create if day missing)",
    tags=["day_plan"],
)
def add_entry_manual(req: schemas.AddEntryManualRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info(
            "Add entry manual date=%s group=%s %s-%s subj=%s room=%s teacher=%s",
            req.date,
            req.group_name,
            req.start_time,
            req.end_time or "",
            req.subject_name,
            req.room_name,
            req.teacher_name or "",
        )
        result = day_svc.add_day_entry_manual(db, req)
        return result
    except ValueError as e:
        logger.warning("Add entry manual failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/day/entry/{entry_id}",
    response_model=schemas.DeleteEntryResponse,
    summary="Delete day entry by id",
    tags=["day_plan"],
)
def delete_entry(entry_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info("Delete day entry id=%s", entry_id)
        res = day_svc.delete_day_entry(db, entry_id)
        return schemas.DeleteEntryResponse(deleted=bool(res.get("deleted")), day_id=res.get("day_id"), date=res.get("date"))
    except ValueError as e:
        logger.warning("Delete day entry failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/autofill_min_pairs",
    response_model=schemas.DayPlanResponse,
    summary="Autofill day to ensure minimal pairs per group (incremental, no deletions)",
    tags=["day_plan"],
)
def autofill_min_pairs(req: schemas.AutofillDayRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info("Autofill day date=%s group=%s ensure=%s", req.date, req.group_name, req.ensure_pairs_per_day)
        return day_svc.autofill_day_min_pairs(db, req)
    except ValueError as e:
        logger.warning("Autofill day failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

@router.get(
    "/day/entry_lookup",
    response_model=schemas.EntryLookupResponse,
    summary="Find entries and their entry_id by date or day_id and filters",
    tags=["day_plan"],
)
def entry_lookup(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    day_id: Optional[int] = Query(None),
    group_name: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    subject_name: Optional[str] = Query(None),
    room_name: Optional[str] = Query(None),
    teacher_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        d: Optional[date] = None
        if date:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        items = day_svc.lookup_day_entries(
            db,
            date_=d,
            day_id=day_id,
            group_name=group_name,
            start_time=start_time,
            subject_name=subject_name,
            room_name=room_name,
            teacher_name=teacher_name,
        )
        return schemas.EntryLookupResponse(items=items)
    except ValueError as e:
        logger.warning("Entry lookup failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/day/{day_id}/bulk_update_strict",
    response_model=schemas.BulkUpdateStrictResponse,
    summary="Bulk update a whole day (strict: entities must exist; checks conflicts)",
    tags=["day_plan"],
)
def bulk_update_strict(day_id: int, req: schemas.BulkUpdateStrictRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        logger.info("Bulk strict update day_id=%s items=%s dry_run=%s", day_id, len(req.items), bool(req.dry_run))
        result = crud.bulk_update_day_entries_strict(db, day_id, req.items, dry_run=bool(req.dry_run))
        # Model validate to match schema
        return schemas.BulkUpdateStrictResponse(
            updated=result["updated"],
            skipped=result["skipped"],
            errors=result["errors"],
            results=[schemas.BulkUpdateStrictResultItem(**r) for r in result["results"]],
            report=schemas.DayReport.model_validate(result["report"]),
        )
    except ValueError as e:
        logger.warning("Bulk strict update failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


# --- Generated schedule fetch: placed after day routes to avoid /schedule/day shadowing ---
@router.get(
    "/{gen_id}",
    response_model=schemas.GeneratedScheduleResponse,
    summary="Get generated schedule by id",
    tags=["schedule"],
)
def get_schedule(gen_id: int, db: Session = Depends(get_db)):
    logger.info("Get schedule id=%s", gen_id)
    gen = crud.get_generated_schedule(db, gen_id)
    if not gen:
        logger.warning("Schedule id=%s not found", gen_id)
        raise HTTPException(status_code=404, detail="Schedule not found")
    return gen
