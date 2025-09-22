import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_admin
from app import schemas
from app.services import analytics_service as analytics

router = APIRouter(prefix="/analytics", tags=["analytics"]) 
logger = logging.getLogger(__name__)


@router.post("/teacher/summary", response_model=schemas.TeacherSummaryResponse, summary="Teacher workload and progress summary")
def teacher_summary(req: schemas.AnalyticsFilter, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        items = analytics.teacher_summary(db, req)
        return schemas.TeacherSummaryResponse(items=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/group/summary", response_model=schemas.GroupSummaryResponse, summary="Group subjects progress summary")
def group_summary(req: schemas.AnalyticsFilter, db: Session = Depends(get_db)):
    try:
        items = analytics.group_summary(db, req)
        return schemas.GroupSummaryResponse(items=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/room/summary", response_model=schemas.RoomSummaryResponse, summary="Room utilization summary (busiest rooms)")
def room_summary(req: schemas.AnalyticsFilter, db: Session = Depends(get_db)):
    try:
        items = analytics.room_summary(db, req)
        return schemas.RoomSummaryResponse(items=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/heatmap", response_model=schemas.HeatmapResponse, summary="Heatmap by day x slot for teacher/group/room")
def heatmap(
    dimension: str,
    name: str,
    req: schemas.AnalyticsFilter,
    db: Session = Depends(get_db),
):
    try:
        return analytics.heatmap(db, dimension, name, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/distribution", response_model=schemas.DistributionResponse, summary="Distribution across a dimension (for bar charts)")
def distribution(dimension: str, req: schemas.AnalyticsFilter, db: Session = Depends(get_db)):
    try:
        items = analytics.distribution(db, dimension, req)
        return schemas.DistributionResponse(items=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/timeseries", response_model=schemas.ScheduleTimeseriesResponse, summary="Daily timeseries of planned vs actual pairs/hours")
def schedule_timeseries(req: schemas.AnalyticsFilter, db: Session = Depends(get_db)):
    try:
        points = analytics.schedule_timeseries(db, req)
        return schemas.ScheduleTimeseriesResponse(points=points)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
