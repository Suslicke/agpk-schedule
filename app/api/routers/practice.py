import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.services import crud
from app import schemas
from app.core.database import get_db
from datetime import date
from typing import Optional
from app.core.security import require_admin

router = APIRouter(prefix="/practice", tags=["practice"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=schemas.PracticeResponse,
    summary="Create practice period for a group",
    tags=["practice"],
)
def create_practice(request: schemas.PracticeCreate, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    """
    Create a practice period for a group.

    During the practice period, the group will not be scheduled for regular classes.
    """
    try:
        logger.info("Create practice: group=%s from %s to %s", request.group_name, request.start_date, request.end_date)
        practice = crud.create_practice(db, request)
        # Convert to response
        group = db.query(crud.models.Group).get(practice.group_id)
        return schemas.PracticeResponse(
            id=practice.id,
            group_name=group.name if group else str(practice.group_id),
            start_date=practice.start_date,
            end_date=practice.end_date,
            name=practice.name
        )
    except ValueError as e:
        logger.warning("Create practice failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "",
    response_model=schemas.PracticeListResponse,
    summary="Get practice periods",
    tags=["practice"],
)
def get_practices(
    group_name: Optional[str] = Query(None, description="Filter by group name"),
    active_on: Optional[str] = Query(None, description="Filter by active date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
):
    """
    Get practice periods, optionally filtered by group or active date.
    """
    try:
        active_date = None
        if active_on:
            from datetime import datetime
            active_date = datetime.strptime(active_on, "%Y-%m-%d").date()

        logger.info("Get practices: group=%s active_on=%s", group_name, active_date)
        practices = crud.get_practices(db, group_name=group_name, active_on=active_date)

        # Convert to response
        items = []
        for practice in practices:
            group = db.query(crud.models.Group).get(practice.group_id)
            items.append(schemas.PracticeResponse(
                id=practice.id,
                group_name=group.name if group else str(practice.group_id),
                start_date=practice.start_date,
                end_date=practice.end_date,
                name=practice.name
            ))

        return schemas.PracticeListResponse(items=items)
    except ValueError as e:
        logger.warning("Get practices failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{practice_id}",
    summary="Delete practice period",
    tags=["practice"],
)
def delete_practice(practice_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    """
    Delete a practice period by id.
    """
    try:
        logger.info("Delete practice id=%s", practice_id)
        crud.delete_practice(db, practice_id)
        return {"deleted": True, "practice_id": practice_id}
    except ValueError as e:
        logger.warning("Delete practice failed: %s", e)
        raise HTTPException(status_code=404, detail=str(e))
