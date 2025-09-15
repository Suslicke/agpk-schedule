from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.services import crud
from app import schemas
from app.core.database import get_db

router = APIRouter(prefix="/progress", tags=["progress"])


@router.post("/entry", response_model=schemas.ProgressEntryResponse)
def add_progress_entry(entry: schemas.ProgressEntryCreate, db: Session = Depends(get_db)):
    try:
        p = crud.add_progress_entry(db, entry)
        return schemas.ProgressEntryResponse.model_validate(p)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedule_item/{schedule_item_id}", response_model=List[schemas.ProgressEntryResponse])
def list_progress(schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        entries = crud.list_progress_entries(db, schedule_item_id)
        return [schemas.ProgressEntryResponse.model_validate(e) for e in entries]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

