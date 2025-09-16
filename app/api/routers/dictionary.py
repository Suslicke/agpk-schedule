from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Dict
from app.core.database import get_db
from app import models
from app import schemas
from app.services import crud
from app.core.security import require_admin
from sqlalchemy import func

router = APIRouter(prefix="/dict", tags=["dictionary"])


@router.get("/groups", response_model=List[Dict], summary="List groups", tags=["dictionary"])
def list_groups(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Group)
    if q:
        query = query.filter(func.lower(models.Group.name).like(f"%{q.lower()}%"))
    groups = query.order_by(models.Group.name.asc()).all()
    return [{"id": g.id, "name": g.name} for g in groups]


@router.get("/subjects", response_model=List[Dict], summary="List subjects", tags=["dictionary"])
def list_subjects(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Subject)
    if q:
        query = query.filter(func.lower(models.Subject.name).like(f"%{q.lower()}%"))
    items = query.order_by(models.Subject.name.asc()).all()
    return [{"id": s.id, "name": s.name} for s in items]


@router.get("/teachers", response_model=List[Dict], summary="List teachers", tags=["dictionary"])
def list_teachers(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Teacher)
    if q:
        query = query.filter(func.lower(models.Teacher.name).like(f"%{q.lower()}%"))
    items = query.order_by(models.Teacher.name.asc()).all()
    return [{"id": t.id, "name": t.name} for t in items]


@router.get("/rooms", response_model=List[Dict], summary="List rooms", tags=["dictionary"])
def list_rooms(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Room)
    if q:
        query = query.filter(func.lower(models.Room.name).like(f"%{q.lower()}%"))
    items = query.order_by(models.Room.name.asc()).all()
    return [{"id": r.id, "name": r.name} for r in items]


@router.get(
    "/group_teacher_subjects",
    response_model=List[schemas.GroupTeacherSubjectResponse],
    summary="List Group-Teacher-Subject mappings",
    tags=["dictionary"],
)
def list_group_teacher_subjects(db: Session = Depends(get_db)):
    links = crud.list_group_teacher_subjects(db)
    return [
        schemas.GroupTeacherSubjectResponse(
            id=l["id"], group_name=l["group_name"], teacher_name=l["teacher_name"], subject_name=l["subject_name"]
        )
        for l in links
    ]


@router.post(
    "/group_teacher_subjects",
    response_model=schemas.GroupTeacherSubjectResponse,
    summary="Create Group-Teacher-Subject mapping",
    tags=["dictionary"],
)
def create_group_teacher_subject(
    link: schemas.GroupTeacherSubjectCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    l = crud.link_group_teacher_subject(db, link.group_name, link.teacher_name, link.subject_name)
    group = db.query(models.Group).get(l.group_id)
    teacher = db.query(models.Teacher).get(l.teacher_id)
    subject = db.query(models.Subject).get(l.subject_id)
    return schemas.GroupTeacherSubjectResponse(id=l.id, group_name=group.name, teacher_name=teacher.name, subject_name=subject.name)
