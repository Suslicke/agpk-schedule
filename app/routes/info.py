from fastapi import APIRouter
from fastapi.responses import JSONResponse
from models.database import SessionLocal
from models.schema import Schedule, GroupLoad
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="",
    tags=["Info"]
)

@router.get(
    "/groups/",
    summary="List all groups",
    description="Returns a list of all groups with saved lesson loads."
)
async def get_groups():
    """List all groups."""
    db = SessionLocal()
    try:
        logger.info("Fetching all groups")
        groups = db.query(GroupLoad.group).distinct().all()
        group_list = [g[0] for g in groups]
        logger.info(f"Found {len(group_list)} groups: {group_list}")
        return JSONResponse(content={
            "status": "success",
            "message": "List of groups",
            "data": {"groups": group_list}
        })
    except Exception as e:
        logger.error(f"Error in get_groups: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
    finally:
        db.close()

@router.get(
    "/debug/db/",
    summary="Debug database contents",
    description="Returns contents of schedules and group_load tables for debugging."
)
async def debug_db():
    """Debug database contents."""
    db = SessionLocal()
    try:
        logger.info("Fetching database contents for debugging")
        schedules = db.query(Schedule).all()
        group_loads = db.query(GroupLoad).all()
        response = {
            "status": "success",
            "message": "Database contents",
            "data": {
                "schedules": [
                    {
                        "id": s.id,
                        "group": s.group,
                        "week_start": s.week_start.strftime("%d.%m.%Y"),
                        "week_type": s.week_type,
                        "timetable": json.loads(s.timetable)
                    } for s in schedules
                ],
                "group_load": [
                    {
                        "group": g.group,
                        "load": json.loads(g.load)
                    } for g in group_loads
                ]
            }
        }
        logger.info(f"Retrieved {len(schedules)} schedules and {len(group_loads)} group loads")
        return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Error in debug_db: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
    finally:
        db.close()