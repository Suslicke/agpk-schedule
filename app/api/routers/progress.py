import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas
from app.core.database import get_db
from app.services import crud

router = APIRouter(prefix="/progress", tags=["progress"])
logger = logging.getLogger(__name__)


@router.post(
    "/entry",
    response_model=schemas.ProgressEntryResponse,
    summary="Add manual progress entry (hours done)",
    tags=["progress"],
)
def add_progress_entry(entry: schemas.ProgressEntryCreate, db: Session = Depends(get_db)):
    try:
        logger.info("Add progress entry for schedule_item_id=%s, hours=%s", entry.schedule_item_id, entry.hours)
        p = crud.add_progress_entry(db, entry)
        return schemas.ProgressEntryResponse.model_validate(p)
    except ValueError as e:
        logger.warning("Add progress failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/schedule_item/{schedule_item_id}",
    response_model=List[schemas.ProgressEntryResponse],
    summary="List manual progress entries for a schedule item",
    tags=["progress"],
)
def list_progress(schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        logger.info("List progress for schedule_item_id=%s", schedule_item_id)
        entries = crud.list_progress_entries(db, schedule_item_id)
        return [schemas.ProgressEntryResponse.model_validate(e) for e in entries]
    except ValueError as e:
        logger.warning("List progress failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
@router.get(
    "/summary",
    response_model=schemas.ProgressSummaryResponse,
    summary="Progress summary: completed vs plan by group/subject",
    tags=["progress"],
)
def get_progress_summary(
    group_name: str | None = None,
    subject_name: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        items = crud.progress_summary(db, group_name=group_name, subject_name=subject_name)
        return schemas.ProgressSummaryResponse(items=items)
    except ValueError as e:
        logger.warning("Progress summary failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/timeseries",
    response_model=schemas.ProgressTimeseriesResponse,
    summary="Timeseries of completed hours grouped by date (for charts)",
    tags=["progress"],
)
def get_progress_timeseries(
    group_name: str | None = Query(None),
    subject_name: str | None = Query(None),
    teacher_name: str | None = Query(None),
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    from datetime import datetime as _dt
    try:
        sd = _dt.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        ed = _dt.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        points = crud.progress_timeseries(
            db,
            group_name=group_name,
            subject_name=subject_name,
            teacher_name=teacher_name,
            start_date=sd,
            end_date=ed,
        )
        return schemas.ProgressTimeseriesResponse(points=points)
    except ValueError as e:
        logger.warning("Progress timeseries failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
