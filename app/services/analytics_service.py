from typing import List, Dict
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.helpers import PAIR_SIZE_AH, SHIFT1_SLOTS, SHIFT2_SLOTS
from app.services.schedule_service import query_schedule as query_schedule_service


def _in_or_all(val: str, allowed: List[str] | None) -> bool:
    return True if not allowed else (val in allowed)


def _collect_entries(
    db: Session,
    start_date: date,
    end_date: date,
    filters: schemas.AnalyticsFilter,
) -> list[schemas.ScheduleQueryEntry]:
    items = query_schedule_service(db, start_date=start_date, end_date=end_date)
    result = [
        it for it in items
        if _in_or_all(it.group_name, filters.groups)
        and _in_or_all(it.teacher_name, filters.teachers)
        and _in_or_all(it.subject_name, filters.subjects)
        and _in_or_all(it.room_name, filters.rooms)
    ]
    if bool(filters.only_approved):
        result = [it for it in result if it.origin == "day_plan" and (it.approval_status == "approved")]
    return result


def teacher_summary(db: Session, req: schemas.AnalyticsFilter) -> List[schemas.TeacherSummaryItem]:
    items = _collect_entries(db, req.start_date, req.end_date, req)
    bucket: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"planned": 0, "actual": 0})
    for it in items:
        key = (it.teacher_name, it.group_name, it.subject_name)
        bucket[key]["planned"] += 1
        if it.origin == "day_plan":
            bucket[key]["actual"] += 1
    total_map: dict[tuple[str, str, str], float] = defaultdict(float)
    q = db.query(models.ScheduleItem).join(models.Group).join(models.Subject).join(models.Teacher)
    if req.groups:
        q = q.filter(models.Group.name.in_(req.groups))
    if req.teachers:
        q = q.filter(models.Teacher.name.in_(req.teachers))
    if req.subjects:
        q = q.filter(models.Subject.name.in_(req.subjects))
    for si in q.all():
        key = (si.teacher.name, si.group.name, si.subject.name)
        total_map[key] += float(si.total_hours)
    # Manual progress aggregation
    manual_map: dict[tuple[str, str, str], float] = defaultdict(float)
    q_prog = db.query(models.SubjectProgress).join(models.ScheduleItem).join(models.Group).join(models.Subject).join(models.Teacher)
    q_prog = q_prog.filter(models.SubjectProgress.date >= req.start_date, models.SubjectProgress.date <= req.end_date)
    if req.groups:
        q_prog = q_prog.filter(models.Group.name.in_(req.groups))
    if req.teachers:
        q_prog = q_prog.filter(models.Teacher.name.in_(req.teachers))
    if req.subjects:
        q_prog = q_prog.filter(models.Subject.name.in_(req.subjects))
    for p, si, g, s, t in q_prog.with_entities(models.SubjectProgress, models.ScheduleItem, models.Group, models.Subject, models.Teacher).all():
        key = (t.name, g.name, s.name)
        manual_map[key] += float(p.hours or 0.0)
    result: List[schemas.TeacherSummaryItem] = []
    for (tname, gname, sname), vals in bucket.items():
        planned_pairs = vals["planned"]
        actual_pairs = vals["actual"]
        planned_h = planned_pairs * PAIR_SIZE_AH
        actual_h = actual_pairs * PAIR_SIZE_AH
        total_h = total_map.get((tname, gname, sname), 0.0)
        percent_assigned = (planned_h / total_h * 100.0) if total_h > 0 else 0.0
        percent_actual = (actual_h / total_h * 100.0) if total_h > 0 else 0.0
        manual_h = manual_map.get((tname, gname, sname), 0.0)
        effective_h = min(total_h, actual_h + manual_h)
        percent_effective = (effective_h / total_h * 100.0) if total_h > 0 else 0.0
        result.append(
            schemas.TeacherSummaryItem(
                teacher_name=tname,
                group_name=gname,
                subject_name=sname,
                planned_pairs=planned_pairs,
                planned_hours_AH=planned_h,
                actual_pairs=actual_pairs,
                actual_hours_AH=actual_h,
                total_plan_hours_AH=total_h,
                percent_assigned=percent_assigned,
                percent_actual=percent_actual,
                manual_completed_hours_AH=manual_h,
                effective_hours_AH=effective_h,
                percent_effective=percent_effective,
            )
        )
    result.sort(key=lambda r: (r.teacher_name, r.group_name, r.subject_name))
    return result


def group_summary(db: Session, req: schemas.AnalyticsFilter) -> List[schemas.GroupSubjectSummaryItem]:
    items = _collect_entries(db, req.start_date, req.end_date, req)
    bucket: dict[tuple[str, str], dict] = defaultdict(lambda: {"planned": 0, "actual": 0})
    for it in items:
        key = (it.group_name, it.subject_name)
        bucket[key]["planned"] += 1
        if it.origin == "day_plan":
            bucket[key]["actual"] += 1
    total_map: dict[tuple[str, str], float] = defaultdict(float)
    q = db.query(models.ScheduleItem).join(models.Group).join(models.Subject)
    if req.groups:
        q = q.filter(models.Group.name.in_(req.groups))
    if req.subjects:
        q = q.filter(models.Subject.name.in_(req.subjects))
    for si in q.all():
        key = (si.group.name, si.subject.name)
        total_map[key] += float(si.total_hours)
    manual_map: dict[tuple[str, str], float] = defaultdict(float)
    q_prog = db.query(models.SubjectProgress).join(models.ScheduleItem).join(models.Group).join(models.Subject)
    q_prog = q_prog.filter(models.SubjectProgress.date >= req.start_date, models.SubjectProgress.date <= req.end_date)
    if req.groups:
        q_prog = q_prog.filter(models.Group.name.in_(req.groups))
    if req.subjects:
        q_prog = q_prog.filter(models.Subject.name.in_(req.subjects))
    for p, si, g, s in q_prog.with_entities(models.SubjectProgress, models.ScheduleItem, models.Group, models.Subject).all():
        key = (g.name, s.name)
        manual_map[key] += float(p.hours or 0.0)
    result: List[schemas.GroupSubjectSummaryItem] = []
    for (gname, sname), vals in bucket.items():
        planned_pairs = vals["planned"]
        actual_pairs = vals["actual"]
        planned_h = planned_pairs * PAIR_SIZE_AH
        actual_h = actual_pairs * PAIR_SIZE_AH
        total_h = total_map.get((gname, sname), 0.0)
        manual_h = manual_map.get((gname, sname), 0.0)
        effective_h = min(total_h, actual_h + manual_h)
        result.append(
            schemas.GroupSubjectSummaryItem(
                group_name=gname,
                subject_name=sname,
                planned_pairs=planned_pairs,
                planned_hours_AH=planned_h,
                actual_pairs=actual_pairs,
                actual_hours_AH=actual_h,
                total_plan_hours_AH=total_h,
                percent_assigned=(planned_h / total_h * 100.0) if total_h > 0 else 0.0,
                percent_actual=(actual_h / total_h * 100.0) if total_h > 0 else 0.0,
                manual_completed_hours_AH=manual_h,
                effective_hours_AH=effective_h,
                percent_effective=(effective_h / total_h * 100.0) if total_h > 0 else 0.0,
            )
        )
    result.sort(key=lambda r: (r.group_name, r.subject_name))
    return result


def room_summary(db: Session, req: schemas.AnalyticsFilter) -> List[schemas.RoomSummaryItem]:
    items = _collect_entries(db, req.start_date, req.end_date, req)
    bucket: dict[str, dict] = defaultdict(lambda: {"planned": 0, "actual": 0})
    for it in items:
        bucket[it.room_name]["planned"] += 1
        if it.origin == "day_plan":
            bucket[it.room_name]["actual"] += 1
    result: List[schemas.RoomSummaryItem] = []
    for rname, vals in bucket.items():
        pp = vals["planned"]
        ap = vals["actual"]
        result.append(
            schemas.RoomSummaryItem(
                room_name=rname,
                planned_pairs=pp,
                actual_pairs=ap,
                planned_hours_AH=pp * PAIR_SIZE_AH,
                actual_hours_AH=ap * PAIR_SIZE_AH,
            )
        )
    result.sort(key=lambda r: (r.actual_pairs, r.planned_pairs), reverse=True)
    return result


def heatmap(db: Session, dimension: str, name: str, req: schemas.AnalyticsFilter) -> schemas.HeatmapResponse:
    dim = dimension.lower()
    filters = schemas.AnalyticsFilter(**req.model_dump())
    if dim == "teacher":
        filters.teachers = [name]
    elif dim == "group":
        filters.groups = [name]
    elif dim == "room":
        filters.rooms = [name]
    else:
        raise ValueError("dimension must be teacher|group|room")
    items = _collect_entries(db, req.start_date, req.end_date, filters)
    dnames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    slots = [s["start"] for s in (SHIFT1_SLOTS + SHIFT2_SLOTS)]
    idx_d = {d: i for i, d in enumerate(dnames)}
    idx_s = {s: i for i, s in enumerate(slots)}
    matrix = [[0 for _ in slots] for __ in dnames]
    for it in items:
        di = idx_d.get(it.day)
        si = idx_s.get(it.start_time)
        if di is not None and si is not None:
            matrix[di][si] += 1
    totals_by_day = [sum(row) for row in matrix]
    totals_by_slot = [sum(matrix[r][c] for r in range(len(dnames))) for c in range(len(slots))]
    return schemas.HeatmapResponse(days=dnames, slots=slots, matrix=matrix, totals_by_day=totals_by_day, totals_by_slot=totals_by_slot)


def distribution(db: Session, dimension: str, req: schemas.AnalyticsFilter) -> List[schemas.DistributionItem]:
    items = _collect_entries(db, req.start_date, req.end_date, req)
    key_fn = {
        "teacher": lambda it: it.teacher_name,
        "group": lambda it: it.group_name,
        "subject": lambda it: it.subject_name,
        "room": lambda it: it.room_name,
    }.get(dimension.lower())
    if not key_fn:
        raise ValueError("dimension must be teacher|group|subject|room")
    bucket: dict[str, dict] = defaultdict(lambda: {"planned": 0, "actual": 0})
    for it in items:
        k = key_fn(it)
        bucket[k]["planned"] += 1
        if it.origin == "day_plan":
            bucket[k]["actual"] += 1
    result: List[schemas.DistributionItem] = []
    for nm, vals in bucket.items():
        pp = vals["planned"]
        ap = vals["actual"]
        result.append(
            schemas.DistributionItem(
                name=nm,
                planned_pairs=pp,
                actual_pairs=ap,
                planned_hours_AH=pp * PAIR_SIZE_AH,
                actual_hours_AH=ap * PAIR_SIZE_AH,
            )
        )
    result.sort(key=lambda r: (r.actual_pairs, r.planned_pairs), reverse=True)
    return result


def schedule_timeseries(db: Session, req: schemas.AnalyticsFilter) -> List[schemas.ScheduleTimeseriesPoint]:
    items = _collect_entries(db, req.start_date, req.end_date, req)
    cur = req.start_date
    buckets: dict[date, dict] = {}
    while cur <= req.end_date:
        buckets[cur] = {"planned": 0, "actual": 0}
        cur += timedelta(days=1)
    for it in items:
        d = it.date
        if d in buckets:
            buckets[d]["planned"] += 1
            if it.origin == "day_plan":
                buckets[d]["actual"] += 1
    points: List[schemas.ScheduleTimeseriesPoint] = []
    for d in sorted(buckets.keys()):
        pp = buckets[d]["planned"]
        ap = buckets[d]["actual"]
        points.append(
            schemas.ScheduleTimeseriesPoint(
                date=d,
                planned_pairs=pp,
                actual_pairs=ap,
                planned_hours_AH=pp * PAIR_SIZE_AH,
                actual_hours_AH=ap * PAIR_SIZE_AH,
            )
        )
    return points

