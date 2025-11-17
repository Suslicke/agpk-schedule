from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List, Set

from app import models
from app.core.config import settings
from app.schemas import WeekType

# Public constants reused across services
PAIR_SIZE_AH = settings.pair_size_academic_hours or 2

SHIFT1_SLOTS = [
    {"start": "08:00", "end": "09:30"},
    {"start": "09:40", "end": "11:10"},
    {"start": "11:20", "end": "12:50"},
    {"start": "13:00", "end": "14:30"},
]

SHIFT2_SLOTS = [
    {"start": "13:25", "end": "14:55"},
    {"start": "15:05", "end": "16:35"},
    {"start": "16:50", "end": "18:20"},
    {"start": "18:30", "end": "20:00"},
]

days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_course_from_group(name: str) -> int | None:
    try:
        if '-' in name:
            tail = name.split('-', 1)[1]
            for ch in tail:
                if ch.isdigit():
                    return int(ch)
    except Exception:
        return None
    return None


def _get_time_slots_for_group(group_name: str, enable_shifts: bool) -> List[Dict[str, str]]:
    if not enable_shifts:
        return SHIFT1_SLOTS
    course = _parse_course_from_group(group_name) or 1
    if course in (1, 3):
        return SHIFT1_SLOTS
    return SHIFT2_SLOTS


def _is_holiday(current_date: date, holidays: List, holiday_dates: Set[date]) -> bool:
    if current_date in holiday_dates:
        return True
    for holiday in holidays or []:
        if holiday.start_date <= current_date <= holiday.end_date:
            return True
    return False


def _pairs_for_week(weekly_ah: float, week_type: str, is_even: bool, pair_size_ah: int = PAIR_SIZE_AH) -> int:
    if weekly_ah <= 0 or pair_size_ah <= 0:
        return 0
    avg_pairs = weekly_ah / float(pair_size_ah)
    wt = WeekType(week_type)
    if wt == WeekType.balanced:
        return int(round(avg_pairs))
    up = math.ceil(avg_pairs)
    down = math.floor(avg_pairs)
    if wt == WeekType.even_priority:
        return up if is_even else down
    if wt == WeekType.odd_priority:
        return down if is_even else up
    return int(round(avg_pairs))


def _distribute_hours(weekly_ah: float, week_type: str, is_even: bool, pair_size_ah: int = PAIR_SIZE_AH) -> float:
    pairs = _pairs_for_week(weekly_ah, week_type, is_even, pair_size_ah)
    return float(pairs * pair_size_ah)


def _teacher_is_free(
    db,
    teacher_id: int,
    date_: date,
    start_time: str,
    end_time: str,
    exclude_entry_id: int | None = None,
    *,
    ignore_weekly: bool = False,
) -> bool:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if ds:
        q = db.query(models.DayScheduleEntry).filter(
            models.DayScheduleEntry.day_schedule_id == ds.id,
            models.DayScheduleEntry.teacher_id == teacher_id,
            models.DayScheduleEntry.start_time == start_time,
        )
        if exclude_entry_id:
            q = q.filter(models.DayScheduleEntry.id != exclude_entry_id)
        if q.first():
            return False
    if ignore_weekly:
        return True
    week_start = _get_week_start(date_)
    dname = days[date_.weekday()]
    dists = (
        db.query(models.WeeklyDistribution)
        .join(models.ScheduleItem)
        .filter(models.WeeklyDistribution.week_start == week_start, models.ScheduleItem.teacher_id == teacher_id)
        .all()
    )
    for d in dists:
        for slot in d.daily_schedule or []:
            if slot.get("day") == dname and slot.get("start_time") == start_time:
                return False
    return True


def _room_has_capacity(db, date_: date, start_time: str, room_id: int, exclude_entry_id: int | None = None) -> bool:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if not ds:
        return True
    q = (
        db.query(models.DayScheduleEntry)
        .filter(
            models.DayScheduleEntry.day_schedule_id == ds.id,
            models.DayScheduleEntry.room_id == room_id,
            models.DayScheduleEntry.start_time == start_time,
        )
    )
    if exclude_entry_id:
        q = q.filter(models.DayScheduleEntry.id != exclude_entry_id)
    count = q.count()
    room = db.query(models.Room).get(room_id)
    capacity = 4 if (room and "Спортзал" in room.name) else 1
    return count < capacity

