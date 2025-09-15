from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.services import crud
from app import schemas
from app.core.database import get_db
from datetime import datetime, date
from typing import List, Dict

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=schemas.GeneratedScheduleResponse)
def generate_schedule_endpoint(request: schemas.GenerateScheduleRequest, db: Session = Depends(get_db)):
    try:
        gen = crud.generate_schedule(db, request)
        return crud.get_generated_schedule(db, gen.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/generate_all", response_model=List[schemas.GeneratedScheduleResponse])
def generate_all_endpoint(request: schemas.GenerateAllScheduleRequest, db: Session = Depends(get_db)):
    gen_request = schemas.GenerateScheduleRequest(
        group_name=None,
        start_date=request.start_date,
        end_date=request.end_date,
        semester=request.semester,
        holidays=request.holidays,
    )
    try:
        gens = crud.generate_schedule(db, gen_request)
        return [crud.get_generated_schedule(db, g.id) for g in gens]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{gen_id}", response_model=schemas.GeneratedScheduleResponse)
def get_schedule(gen_id: int, db: Session = Depends(get_db)):
    gen = crud.get_generated_schedule(db, gen_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return gen


@router.get("/group/{group_name}/week", response_model=List[schemas.DailySchedule])
def get_group_week(group_name: str, week_start: str = Query(...), db: Session = Depends(get_db)):
    try:
        week_start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
        return crud.get_group_week_schedule(db, group_name, week_start_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teacher/{teacher_name}/week", response_model=List[schemas.DailySchedule])
def get_teacher_week(teacher_name: str, week_start: str = Query(...), db: Session = Depends(get_db)):
    try:
        week_start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
        return crud.get_teacher_week_schedule(db, teacher_name, week_start_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/group/{group_name}/day", response_model=List[schemas.DailySchedule])
def get_group_day(group_name: str, day: str = Query(..., description="YYYY-MM-DD"), db: Session = Depends(get_db)):
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        return crud.get_group_day_schedule(db, group_name, d)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teacher/{teacher_name}/day", response_model=List[schemas.DailySchedule])
def get_teacher_day(teacher_name: str, day: str = Query(..., description="YYYY-MM-DD"), db: Session = Depends(get_db)):
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        return crud.get_teacher_day_schedule(db, teacher_name, d)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teacher/{teacher_name}/vacant", response_model=List[Dict])
def get_vacant_slots(teacher_name: str, week_start: date, db: Session = Depends(get_db)):
    try:
        vacant_slots = crud.get_vacant_slots_for_teacher(db, teacher_name, week_start)
        return vacant_slots
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedule_item/{schedule_item_id}/hours", response_model=schemas.HoursResponse)
def get_assigned_hours(schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        hours_info = crud.calculate_assigned_hours(db, schedule_item_id)
        return hours_info
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schedule_item/{schedule_item_id}/hours_extended", response_model=schemas.HoursExtendedResponse)
def get_extended_hours(schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        hours_info = crud.calculate_hours_extended(db, schedule_item_id)
        return hours_info
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/teacher/{teacher_name}/slot", response_model=Dict)
def add_teacher_slot(teacher_name: str, week_start: date, slot_data: schemas.SlotCreate, schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        dist = crud.add_teacher_slot(db, teacher_name, week_start, slot_data, schedule_item_id)
        return dist.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/teacher/{teacher_name}/slot", response_model=Dict)
def edit_teacher_slot(teacher_name: str, week_start: date, old_slot: schemas.SlotUpdate, new_slot: schemas.SlotCreate, schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        dist = crud.edit_teacher_slot(db, teacher_name, week_start, old_slot, new_slot, schedule_item_id)
        return dist.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/teacher/{teacher_name}/slot", response_model=Dict)
def delete_teacher_slot(teacher_name: str, week_start: date, slot: schemas.SlotUpdate, schedule_item_id: int, db: Session = Depends(get_db)):
    try:
        dist = crud.delete_teacher_slot(db, teacher_name, week_start, slot, schedule_item_id)
        return dist.__dict__
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teacher/{teacher_name}/schedule_items", response_model=List[schemas.ScheduleItemResponse])
def get_teacher_schedule_items(teacher_name: str, db: Session = Depends(get_db)):
    try:
        schedule_items = crud.get_teacher_schedule_items(db, teacher_name)
        return schedule_items
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

