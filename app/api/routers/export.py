import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import schemas
from app.core.database import get_db
from app.core.security import require_admin
from app.services.exporter import build_day_with_diff_excel, build_schedule_range_excel

router = APIRouter(prefix="/export", tags=["export"])
logger = logging.getLogger(__name__)


@router.post("/day", summary="Export day (POST) with plan vs actual diffs")
def export_day_post(req: schemas.ExportDayRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        buf: BytesIO = build_day_with_diff_excel(db, req.date, req.group_name, req.groups)
        groups_str = ("-".join(req.groups)[:20] if req.groups else (req.group_name or "ALL"))
        filename = f"Day_{req.date}_{groups_str}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/schedule", summary="Export schedule (POST) for range with plan/actual/diff")
def export_schedule_post(req: schemas.ExportScheduleRequest, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        from datetime import timedelta
        sd = req.start_date
        ed = req.end_date
        if (sd is None or ed is None) and req.period:
            if req.period not in ("week", "month", "semester"):
                raise ValueError("period must be week|month|semester")
            if req.period in ("week", "month"):
                if not req.anchor_date:
                    raise ValueError("anchor_date is required for period=week|month when start/end not provided")
                a = req.anchor_date
                if req.period == "week":
                    ws = a - timedelta(days=a.weekday())
                    we = ws + timedelta(days=6)
                    sd, ed = ws, we
                else:
                    first = a.replace(day=1)
                    if a.month == 12:
                        last = a.replace(day=31)
                    else:
                        # Simple next month calc
                        nm = 1 if a.month == 12 else a.month + 1
                        ny = a.year + 1 if a.month == 12 else a.year
                        next_first = a.replace(year=ny, month=nm, day=1)
                        last = next_first - timedelta(days=1)
                    sd, ed = first, last
            else:
                if not req.semester_name:
                    raise ValueError("semester_name is required for period=semester when start/end not provided")
                from app import models
                q = db.query(models.GeneratedSchedule).filter(models.GeneratedSchedule.semester == req.semester_name)
                if req.groups:
                    q = q.join(models.Group).filter(models.Group.name.in_(req.groups))
                gens = q.all()
                if not gens:
                    raise ValueError("No generated schedules found for semester_name")
                sd = min(g.start_date for g in gens)
                ed = max(g.end_date for g in gens)
        if sd is None or ed is None:
            raise ValueError("Provide start_date&end_date or period+anchor/semester_name")
        buf: BytesIO = build_schedule_range_excel(db, sd, ed, req.groups, req.view or "all", bool(req.split_by_group))
        groups_str = ("-".join(req.groups)[:20] if req.groups else "ALL")
        filename = f"Schedule_{req.view or 'all'}_{sd}_{ed}_{groups_str}.xlsx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
