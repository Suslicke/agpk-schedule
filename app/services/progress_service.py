"""Progress and hours service layer.

Thin wrappers around legacy functions in app.services.crud.
"""
from typing import List

from sqlalchemy.orm import Session

from app import schemas
from app.services import crud


def add_progress_entry(db: Session, entry: schemas.ProgressEntryCreate):
    return crud.add_progress_entry(db, entry)


def list_progress_entries(db: Session, schedule_item_id: int):
    return crud.list_progress_entries(db, schedule_item_id)


def progress_summary(db: Session, group_name: str | None = None, subject_name: str | None = None) -> List[schemas.ProgressSummaryItem]:
    return crud.progress_summary(db, group_name=group_name, subject_name=subject_name)


def progress_timeseries(db: Session, group_name: str | None = None, subject_name: str | None = None, teacher_name: str | None = None, start_date=None, end_date=None):
    return crud.progress_timeseries(db, group_name=group_name, subject_name=subject_name, teacher_name=teacher_name, start_date=start_date, end_date=end_date)

