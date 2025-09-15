from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Dict
from app.core.database import get_db
from app import models

router = APIRouter(prefix="/dict", tags=["dictionary"])


@router.get("/groups", response_model=List[Dict])
def list_groups(db: Session = Depends(get_db)):
    groups = db.query(models.Group).order_by(models.Group.name.asc()).all()
    return [{"id": g.id, "name": g.name} for g in groups]


@router.get("/subjects", response_model=List[Dict])
def list_subjects(db: Session = Depends(get_db)):
    items = db.query(models.Subject).order_by(models.Subject.name.asc()).all()
    return [{"id": s.id, "name": s.name} for s in items]


@router.get("/teachers", response_model=List[Dict])
def list_teachers(db: Session = Depends(get_db)):
    items = db.query(models.Teacher).order_by(models.Teacher.name.asc()).all()
    return [{"id": t.id, "name": t.name} for t in items]


@router.get("/rooms", response_model=List[Dict])
def list_rooms(db: Session = Depends(get_db)):
    items = db.query(models.Room).order_by(models.Room.name.asc()).all()
    return [{"id": r.id, "name": r.name} for r in items]

