"""Dictionary helpers service layer.

Thin wrappers around legacy functions in app.services.crud.
"""
from sqlalchemy.orm import Session
from app.services import crud


def link_group_teacher_subject(db: Session, group_name: str, teacher_name: str, subject_name: str):
    return crud.link_group_teacher_subject(db, group_name, teacher_name, subject_name)


def list_group_teacher_subjects(db: Session):
    return crud.list_group_teacher_subjects(db)

