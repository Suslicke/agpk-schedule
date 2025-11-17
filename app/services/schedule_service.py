"""Semester/week schedule generation and queries service layer.

Thin wrappers around legacy functions in app.services.crud.
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app import schemas
from app.services import crud


def generate_schedule(db: Session, request: schemas.GenerateScheduleRequest):
    return crud.generate_schedule(db, request)


def get_generated_schedule(db: Session, gen_id: int):
    return crud.get_generated_schedule(db, gen_id)


def get_group_week_schedule(db: Session, group_name: str, week_start: date):
    return crud.get_group_week_schedule(db, group_name, week_start)


def get_teacher_week_schedule(db: Session, teacher_name: str, week_start: date):
    return crud.get_teacher_week_schedule(db, teacher_name, week_start)


def query_schedule(db: Session, *, date_: date | None = None, start_date: date | None = None, end_date: date | None = None, group_name: Optional[str] = None, teacher_name: Optional[str] = None):
    return crud.query_schedule(db, date_=date_, start_date=start_date, end_date=end_date, group_name=group_name, teacher_name=teacher_name)

