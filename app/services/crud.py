from typing import List, Set, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app import models
from app import schemas
from app.schemas import WeekType
from datetime import date, timedelta
import math
import pandas as pd
from collections import defaultdict
import random
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# Pair and hour semantics
# Academic hour (AH) is a 45-minute unit. Excel provides total/weekly in AH.
# One scheduled lesson slot ("pair") equals pair_size_ah academic hours (usually 2 AH).
PAIR_SIZE_AH = settings.pair_size_academic_hours or 2

# Store last planning debug notes keyed by DaySchedule.id
_last_plan_debug: dict[int, list[str]] = {}

# Shift 1 (1st and 3rd years)
SHIFT1_SLOTS = [
    {"start": "08:00", "end": "09:30"},
    {"start": "09:40", "end": "11:10"},
    {"start": "11:20", "end": "12:50"},
    {"start": "13:00", "end": "14:30"}
]

# Shift 2 (2nd and 4th years)
SHIFT2_SLOTS = [
    {"start": "13:25", "end": "14:55"},
    {"start": "15:05", "end": "16:35"},
    {"start": "16:50", "end": "18:20"},
    {"start": "18:30", "end": "20:00"}
]
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def get_or_create_group(db: Session, name: str):
    group = db.query(models.Group).filter(models.Group.name == name).first()
    if not group:
        group = models.Group(name=name)
        db.add(group)
        db.commit()
        db.refresh(group)
        logger.debug("Created group: %s (id=%s)", name, group.id)
    return group


def get_or_create_subject(db: Session, name: str):
    subject = db.query(models.Subject).filter(models.Subject.name == name).first()
    if not subject:
        subject = models.Subject(name=name)
        db.add(subject)
        db.commit()
        db.refresh(subject)
        logger.debug("Created subject: %s (id=%s)", name, subject.id)
    return subject


def get_or_create_teacher(db: Session, name: str):
    teacher = db.query(models.Teacher).filter(models.Teacher.name == name).first()
    if not teacher:
        teacher = models.Teacher(name=name)
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
        logger.debug("Created teacher: %s (id=%s)", name, teacher.id)
    return teacher


def get_or_create_room(db: Session, name: str):
    room = db.query(models.Room).filter(models.Room.name == name).first()
    if not room:
        room = models.Room(name=name)
        db.add(room)
        db.commit()
        db.refresh(room)
        logger.debug("Created room: %s (id=%s)", name, room.id)
    return room


def create_schedule_item(db: Session, item: schemas.ScheduleItemCreate):
    group = get_or_create_group(db, item.group_name)
    subject = get_or_create_subject(db, item.subject_name)
    teacher = get_or_create_teacher(db, item.teacher_name)
    room = get_or_create_room(db, item.room_name)

    existing = db.query(models.ScheduleItem).filter(
        and_(
            models.ScheduleItem.group_id == group.id,
            models.ScheduleItem.subject_id == subject.id
        )
    ).first()
    if existing:
        logger.debug(
            "ScheduleItem exists: group=%s subject=%s -> id=%s",
            item.group_name,
            item.subject_name,
            existing.id,
        )
        return existing

    schedule_item = models.ScheduleItem(
        group_id=group.id,
        subject_id=subject.id,
        teacher_id=teacher.id,
        room_id=room.id,
        total_hours=item.total_hours,
        weekly_hours=item.weekly_hours,
        week_type=item.week_type
    )
    db.add(schedule_item)
    db.commit()
    db.refresh(schedule_item)
    logger.info(
        "Created ScheduleItem id=%s group=%s subject=%s teacher=%s room=%s total=%.2f weekly=%.2f week_type=%s",
        schedule_item.id,
        item.group_name,
        item.subject_name,
        item.teacher_name,
        item.room_name,
        item.total_hours,
        item.weekly_hours,
        item.week_type,
    )
    return schedule_item


def parse_and_create_schedule_items(db: Session, df: pd.DataFrame):
    schedule_items = []
    current_group = None
    for _, row in df.iterrows():
        if pd.isna(row.iloc[0]) and pd.isna(row.iloc[1]):
            continue
        if not pd.isna(row.iloc[1]):
            current_group = row.iloc[1]
            logger.debug("Parsing group: %s", current_group)
        if current_group and not pd.isna(row.iloc[2]):
            subject = str(row.iloc[2]).strip()
            total = float(row.iloc[3]) if not pd.isna(row.iloc[3]) else 0.0
            weekly = float(row.iloc[4]) if not pd.isna(row.iloc[4]) else 0.0
            teacher = (str(row.iloc[5]).strip() if not pd.isna(row.iloc[5]) else 'Unknown')
            room = (str(row.iloc[6]).strip() if not pd.isna(row.iloc[6]) else 'Unknown')
            week_side = row.iloc[7] if len(row) > 7 and not pd.isna(row.iloc[7]) else None

            week_type = WeekType.balanced
            if week_side == 'правая':
                week_type = WeekType.even_priority
            elif week_side == 'левая':
                week_type = WeekType.odd_priority

            item = schemas.ScheduleItemCreate(
                group_name=str(current_group).strip(),
                subject_name=subject,
                teacher_name=teacher,
                room_name=room,
                total_hours=total,
                weekly_hours=weekly,
                week_type=week_type,
            )
            created = create_schedule_item(db, item)
            # Also establish Group-Teacher-Subject mapping for replacements if teacher is not a placeholder
            try:
                if not _is_placeholder_teacher_name(teacher):
                    link_group_teacher_subject(db, current_group, teacher, subject)
            except Exception as ex:
                logger.warning("Failed to create G-T-S link for %s / %s / %s: %s", current_group, teacher, subject, ex)
            schedule_items.append(created)
    logger.info("Parsed and created %d schedule items", len(schedule_items))
    return schedule_items


def _is_holiday(current_date: date, holidays: List[schemas.HolidayPeriod], holiday_dates: Set[date]) -> bool:
    if current_date in holiday_dates:
        return True
    for holiday in holidays or []:
        if holiday.start_date <= current_date <= holiday.end_date:
            return True
    return False


def _pairs_for_week(weekly_ah: float, week_type: str, is_even: bool, pair_size_ah: int = PAIR_SIZE_AH) -> int:
    """
    Compute number of full pairs (int) to schedule this week based on weekly academic hours
    and parity priority rules.

    - For even values (e.g., 4, 6 AH), returns weekly_ah / pair_size_ah pairs every week.
    - For odd totals (e.g., 5 AH), returns ceil(avg_pairs) on priority week and floor(avg_pairs) otherwise.
    - For 1 AH with odd/even priority, yields 1 pair on priority weeks, 0 otherwise (average 0.5 pair/week).
    """
    if weekly_ah <= 0 or pair_size_ah <= 0:
        return 0
    avg_pairs = weekly_ah / float(pair_size_ah)
    wt = WeekType(week_type)
    if wt == WeekType.balanced:
        return int(round(avg_pairs))
    # priority splitting for non-integer avg
    up = math.ceil(avg_pairs)
    down = math.floor(avg_pairs)
    if wt == WeekType.even_priority:
        return up if is_even else down
    if wt == WeekType.odd_priority:
        return down if is_even else up
    return int(round(avg_pairs))


def _distribute_hours(weekly_ah: float, week_type: str, is_even: bool, pair_size_ah: int = PAIR_SIZE_AH) -> float:
    """
    Return the number of academic hours (AH) to allocate this week based on weekly_ah
    and parity rules, aligned to whole pairs.
    """
    pairs = _pairs_for_week(weekly_ah, week_type, is_even, pair_size_ah)
    return float(pairs * pair_size_ah)


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


def _assign_daily_schedule(
    weekly_ah: float,
    week_start: date,
    week_end: date,
    is_even: bool,
    schedule_item: models.ScheduleItem,
    holiday_dates: Set[date],
    room_occupancy: defaultdict,
    occupied_teacher: Set[tuple],
    occupied_group: Set[tuple],
    gym_teachers: defaultdict,
    *,
    min_pairs_per_day: int = 0,
    max_pairs_per_day: int = 4,
    preferred_days: List[str] | None = None,
    concentrate_on_preferred_days: bool = False,
    enable_shifts: bool = True,
    pair_size_ah: int = PAIR_SIZE_AH,
) -> List[dict]:
    if weekly_ah <= 0:
        logger.debug(
            "No weekly hours for item id=%s group=%s subject=%s; skipping",
            schedule_item.id,
            schedule_item.group.name,
            schedule_item.subject.name,
        )
        return []
    max_pairs_per_day = max(1, max_pairs_per_day)
    daily_schedule = []
    remaining_ah = weekly_ah
    available_days = []
    for i in range((week_end - week_start).days + 1):
        current_date = week_start + timedelta(days=i)
        if not _is_holiday(current_date, [], holiday_dates):
            day_index = current_date.weekday()
            if day_index < len(days):
                available_days.append((days[day_index], current_date))
    # Reorder days based on preference
    if preferred_days:
        preferred_set = [d for d in days if d in set(preferred_days)]
        non_pref = [d for d in days if d not in set(preferred_days)]
        order = preferred_set + ([] if not concentrate_on_preferred_days else []) + (non_pref if not concentrate_on_preferred_days else [])
        available_days.sort(key=lambda pair: order.index(pair[0]) if pair[0] in order else 99)
    if not available_days:
        return []
    if not preferred_days:
        random.shuffle(available_days)
    pairs_needed = math.ceil(remaining_ah / float(pair_size_ah))
    base_days = len(available_days)
    if concentrate_on_preferred_days and preferred_days:
        base_days = min(len(preferred_days), base_days)
    # ALWAYS MINIMUM 3 PAIRS PER DAY
    min_pairs_per_day = max(3, min_pairs_per_day)
    pairs_per_day = min(max_pairs_per_day, max(min_pairs_per_day, math.ceil(pairs_needed / max(1, base_days))))
    group_day_counts = defaultdict(int)
    slots = _get_time_slots_for_group(schedule_item.group.name, enable_shifts)
    logger.debug(
        "Assigning daily schedule: item_id=%s group=%s subject=%s weekly_ah=%.2f is_even=%s pairs/day<=%s shifts=%s",
        schedule_item.id,
        schedule_item.group.name,
        schedule_item.subject.name,
        weekly_ah,
        is_even,
        max_pairs_per_day,
        enable_shifts,
    )
    for day_name, day_date in available_days:
        if remaining_ah <= 0:
            break
        pairs_assigned = 0
        # DO NOT SHUFFLE - always start from first lesson
        local_slots = slots.copy()
        for slot in local_slots:
            if pairs_assigned >= pairs_per_day or remaining_ah <= 0:
                break
            teacher_key = (day_date, slot["start"], schedule_item.teacher_id)
            group_key = (day_date, slot["start"], schedule_item.group_id)
            room_key = (day_date, slot["start"], schedule_item.room_id)
            capacity = 4 if "Спортзал" in schedule_item.room.name else 1
            if "Спортзал" in schedule_item.room.name:
                gym_key = (day_date, slot["start"], schedule_item.room_id)
                if schedule_item.teacher_id in gym_teachers[gym_key]:
                    logger.debug("Skip slot %s %s: gym teacher already assigned in same slot", day_name, slot["start"])
                    continue
                if room_occupancy[room_key] >= capacity:
                    logger.debug("Skip slot %s %s: gym room capacity reached", day_name, slot["start"])
                    continue
                gym_teachers[gym_key].add(schedule_item.teacher_id)
            else:
                if room_occupancy[room_key] >= capacity:
                    logger.debug("Skip slot %s %s: room occupied", day_name, slot["start"])
                    continue
            if teacher_key in occupied_teacher or group_key in occupied_group:
                logger.debug("Skip slot %s %s: teacher or group occupied", day_name, slot["start"])
                continue
            if group_day_counts[(schedule_item.group_id, day_date)] >= max_pairs_per_day:
                logger.debug("Skip slot %s %s: group reached daily max pairs", day_name, slot["start"])
                continue
            daily_schedule.append({
                "day": day_name,
                "start_time": slot["start"],
                "end_time": slot["end"],
                "subject_name": schedule_item.subject.name,
                "teacher_name": schedule_item.teacher.name,
                "room_name": schedule_item.room.name,
                "group_name": schedule_item.group.name
            })
            occupied_teacher.add(teacher_key)
            occupied_group.add(group_key)
            room_occupancy[room_key] += 1
            group_day_counts[(schedule_item.group_id, day_date)] += 1
            remaining_ah -= pair_size_ah
            pairs_assigned += 1
            logger.debug("Assigned %s %s-%s", day_name, slot["start"], slot["end"])
    return daily_schedule


def create_schedules(db: Session, request: schemas.GenerateScheduleRequest):
    if request.group_name:
        groups = db.query(models.Group).filter(models.Group.name == request.group_name).all()
    else:
        groups = db.query(models.Group).all()
    gen_schedules = []
    for group in groups:
        if not group:
            continue
        gen_sched = models.GeneratedSchedule(
            start_date=request.start_date,
            end_date=request.end_date,
            semester=request.semester,
            group_id=group.id,
            status="pending"
        )
        db.add(gen_sched)
        db.commit()
        db.refresh(gen_sched)
        gen_schedules.append(gen_sched)
    return gen_schedules


def fill_schedules(db: Session, gen_schedules: List[models.GeneratedSchedule], request: schemas.GenerateScheduleRequest):
    logger.info(
        "Filling schedules: %s -> %s, semester=%s, enable_shifts=%s, min_pairs=%s, max_pairs=%s, preferred_days=%s, concentrate=%s",
        request.start_date,
        request.end_date,
        request.semester,
        bool(request.enable_shifts),
        request.min_pairs_per_day,
        request.max_pairs_per_day,
        request.preferred_days,
        bool(request.concentrate_on_preferred_days),
    )
    holiday_dates = set()
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.start_date <= request.end_date,
        models.Holiday.end_date >= request.start_date
    ).all()
    for holiday in db_holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)
    for holiday in request.holidays or []:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)
    logger.info("Collected %d holiday dates", len(holiday_dates))

    all_items = []
    for gen_sched in gen_schedules:
        items = db.query(models.ScheduleItem).filter(models.ScheduleItem.group_id == gen_sched.group_id).all()
        if not items:
            gen_sched.status = "failed"
            db.add(gen_sched)
            continue
        all_items.extend(items)
    if not all_items:
        db.commit()
        logger.warning("No schedule items found for provided request")
        return

    # Effective total hours (in academic hours). If Excel totals are annual, halve for semester.
    divisor = 2 if (request.total_hours_is_annual if request.total_hours_is_annual is not None else settings.total_hours_is_annual) else 1
    remaining_hours = {item.id: (item.total_hours / divisor) for item in all_items}
    room_occupancy = defaultdict(int)
    occupied_teacher = set()
    occupied_group = set()
    gym_teachers = defaultdict(set)

    existing_dists = db.query(models.WeeklyDistribution).filter(
        models.WeeklyDistribution.week_start >= request.start_date - timedelta(days=7),
        models.WeeklyDistribution.week_end <= request.end_date + timedelta(days=7)
    ).all()
    logger.debug("Loaded %d existing distributions to seed occupancy", len(existing_dists))
    for dist in existing_dists:
        item = dist.schedule_item
        for slot in (dist.daily_schedule or []):
            try:
                day_idx = days.index(slot["day"])
                slot_date = dist.week_start + timedelta(days=day_idx)
                if _is_holiday(slot_date, request.holidays, holiday_dates):
                    continue
                start_time = slot["start_time"]
                room_key = (slot_date, start_time, item.room_id)
                teacher_key = (slot_date, start_time, item.teacher_id)
                group_key = (slot_date, start_time, item.group_id)
                room_occupancy[room_key] += 1
                occupied_teacher.add(teacher_key)
                occupied_group.add(group_key)
                if "Спортзал" in item.room.name:
                    gym_teachers[(slot_date, start_time, item.room_id)].add(item.teacher_id)
            except ValueError:
                continue

    current_date = request.start_date
    while current_date <= request.end_date:
        # Determine week parity base
        base_str = request.parity_base_date.isoformat() if getattr(request, 'parity_base_date', None) else (settings.parity_base_date or "2025-09-01")
        try:
            base_y, base_m, base_d = [int(x) for x in base_str.split('-')]
            base_date = date(base_y, base_m, base_d)
        except Exception:
            base_date = date(2025, 9, 1)
        week_number = (current_date - base_date).days // 7
        is_even = (week_number % 2 == 0)
        week_end = min(current_date + timedelta(days=6 - current_date.weekday()), request.end_date)
        random.shuffle(all_items)
        distributions = []
        logger.info("Planning week %s..%s (even=%s)", current_date, week_end, is_even)
        for item in all_items:
            if remaining_hours[item.id] <= 0:
                continue
            # Check if group is on practice during this week - skip if so
            # We need to check each day in the week for practice
            week_has_practice = False
            check_date = current_date
            while check_date <= week_end:
                if is_group_on_practice(db, item.group_id, check_date):
                    week_has_practice = True
                    logger.info("Group %s (id=%s) is on practice during week %s-%s, skipping",
                               item.group.name, item.group_id, current_date, week_end)
                    break
                check_date += timedelta(days=1)

            if week_has_practice:
                continue

            # Pair size may be overridden per request
            pair_size_ah = request.pair_size_academic_hours or PAIR_SIZE_AH
            weekly_ah = min(item.weekly_hours, remaining_hours[item.id])
            hours = _distribute_hours(weekly_ah, item.week_type, is_even, pair_size_ah)
            # Clamp to remaining (align to full pairs)
            if hours > remaining_hours[item.id]:
                # Reduce to the largest multiple of pair_size_ah not exceeding remaining
                max_pairs = int(remaining_hours[item.id] // pair_size_ah)
                hours = float(max_pairs * pair_size_ah)
                if hours <= 0:
                    continue
            logger.debug(
                "Item id=%s group=%s subject=%s weekly=%.2f -> hours_this_week=%.2f remaining_before=%.2f",
                item.id,
                item.group.name,
                item.subject.name,
                item.weekly_hours,
                hours,
                remaining_hours[item.id],
            )
            daily_schedule = _assign_daily_schedule(
                hours, current_date, week_end, is_even, item, holiday_dates,
                room_occupancy, occupied_teacher, occupied_group, gym_teachers,
                min_pairs_per_day=request.min_pairs_per_day or 0,
                max_pairs_per_day=request.max_pairs_per_day or 4,
                preferred_days=request.preferred_days,
                concentrate_on_preferred_days=bool(request.concentrate_on_preferred_days),
                enable_shifts=bool(request.enable_shifts),
                pair_size_ah=pair_size_ah,
            )
            if daily_schedule:
                actual_ah = len(daily_schedule) * pair_size_ah
                remaining_hours[item.id] -= actual_ah
                logger.debug(
                    "Planned %d slots (%.1f AH) for item id=%s; remaining=%.1f",
                    len(daily_schedule),
                    actual_ah,
                    item.id,
                    remaining_hours[item.id],
                )
                gen_sched = next(g for g in gen_schedules if g.group_id == item.group_id)
                dist = models.WeeklyDistribution(
                    generated_schedule_id=gen_sched.id,
                    week_start=current_date,
                    week_end=week_end,
                    is_even_week=1 if is_even else 0,
                    schedule_item_id=item.id,
                    hours_even=hours if is_even else 0,
                    hours_odd=hours if not is_even else 0,
                    daily_schedule=daily_schedule
                )
                distributions.append(dist)
        for dist in distributions:
            db.add(dist)
        db.commit()
        logger.info("Saved %d distributions for week %s", len(distributions), current_date)
        current_date = week_end + timedelta(days=1)
    for gen_sched in gen_schedules:
        gen_sched.status = "completed"
        db.add(gen_sched)
    db.commit()
    logger.info("Finished filling schedules: %d schedules marked completed", len(gen_schedules))


def generate_schedule(db: Session, request: schemas.GenerateScheduleRequest):
    gen_schedules = create_schedules(db, request)
    fill_schedules(db, gen_schedules, request)
    return gen_schedules


def get_generated_schedule(db: Session, gen_id: int):
    gen_sched = db.query(models.GeneratedSchedule).filter(models.GeneratedSchedule.id == gen_id).first()
    if not gen_sched:
        return None
    if gen_sched.status == "pending":
        return schemas.GeneratedScheduleResponse(
            id=gen_sched.id,
            start_date=gen_sched.start_date,
            end_date=gen_sched.end_date,
            semester=gen_sched.semester,
            status=gen_sched.status,
            weekly_distributions=[]
        )
    dists = db.query(models.WeeklyDistribution).filter(models.WeeklyDistribution.generated_schedule_id == gen_id).all()
    holiday_dates = set()
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.start_date <= gen_sched.end_date,
        models.Holiday.end_date >= gen_sched.start_date
    ).all()
    for holiday in db_holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)
    weekly_distributions = defaultdict(list)
    for d in dists:
        item = db.query(models.ScheduleItem).filter(models.ScheduleItem.id == d.schedule_item_id).first()
        if item:
            filtered_daily_schedule = []
            for slot in (d.daily_schedule or []):
                try:
                    day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                    slot_date = d.week_start + timedelta(days=day_idx)
                    if not _is_holiday(slot_date, [], holiday_dates):
                        filtered_daily_schedule.append(slot)
                except ValueError:
                    continue
            if not filtered_daily_schedule and d.daily_schedule:
                d.daily_schedule = _assign_daily_schedule(
                    d.hours_even if d.is_even_week else d.hours_odd,
                    d.week_start,
                    d.week_end,
                    bool(d.is_even_week),
                    item,
                    holiday_dates,
                    defaultdict(int),
                    set(),
                    set(),
                    defaultdict(set),
                    pair_size_ah=PAIR_SIZE_AH,
                )
                filtered_daily_schedule = d.daily_schedule
            if filtered_daily_schedule:
                weekly_distributions[(d.week_start, d.week_end, bool(d.is_even_week))].append({
                    "hours_even": d.hours_even,
                    "hours_odd": d.hours_odd,
                    "subject_name": item.subject.name,
                    "teacher_name": item.teacher.name,
                    "room_name": item.room.name,
                    "group_name": item.group.name,
                    "daily_schedule": [
                        {**slot, "group_name": item.group.name} for slot in filtered_daily_schedule
                    ]
                })
    response = schemas.GeneratedScheduleResponse(
        id=gen_sched.id,
        start_date=gen_sched.start_date,
        end_date=gen_sched.end_date,
        semester=gen_sched.semester,
        status=gen_sched.status,
        weekly_distributions=[
            schemas.WeeklyDistributionResponse(
                week_start=week_key[0],
                week_end=week_key[1],
                is_even_week=week_key[2],
                hours_even=dist["hours_even"],
                hours_odd=dist["hours_odd"],
                subject_name=dist["subject_name"],
                teacher_name=dist["teacher_name"],
                room_name=dist["room_name"],
                daily_schedule=[
                    schemas.DailySchedule(
                        day=slot["day"],
                        start_time=slot["start_time"],
                        end_time=slot["end_time"],
                        subject_name=slot["subject_name"],
                        teacher_name=slot["teacher_name"],
                        room_name=slot["room_name"],
                        group_name=slot.get("group_name")
                    )
                    for slot in dist["daily_schedule"]
                ]
            )
            for week_key, distributions in sorted(weekly_distributions.items(), key=lambda x: x[0][0])
            for dist in distributions
        ]
    )
    return response


def get_group_week_schedule(db: Session, group_name: str, week_start: date):
    group = db.query(models.Group).filter(models.Group.name == group_name).first()
    if not group:
        raise ValueError("Group not found")
    dists = db.query(models.WeeklyDistribution).join(models.ScheduleItem).filter(
        models.WeeklyDistribution.week_start == week_start,
        models.ScheduleItem.group_id == group.id
    ).all()
    holiday_dates = set()
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.start_date <= week_start + timedelta(days=6),
        models.Holiday.end_date >= week_start
    ).all()
    for holiday in db_holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)
    slots = []
    for d in dists:
        item = d.schedule_item
        for slot in (d.daily_schedule or []):
            try:
                day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                slot_date = d.week_start + timedelta(days=day_idx)
                if _is_holiday(slot_date, [], holiday_dates):
                    continue
                slots.append(schemas.DailySchedule(
                    day=slot["day"],
                    start_time=slot["start_time"],
                    end_time=slot["end_time"],
                    subject_name=item.subject.name,
                    teacher_name=item.teacher.name,
                    room_name=item.room.name,
                    group_name=group.name
                ))
            except ValueError:
                continue
    day_order = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4}
    slots.sort(key=lambda s: (day_order.get(s.day, 5), s.start_time))
    return slots


def get_teacher_week_schedule(db: Session, teacher_name: str, week_start: date):
    teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
    if not teacher:
        raise ValueError("Teacher not found")
    dists = db.query(models.WeeklyDistribution).join(models.ScheduleItem).filter(
        models.WeeklyDistribution.week_start == week_start,
        models.ScheduleItem.teacher_id == teacher.id
    ).all()
    holiday_dates = set()
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.start_date <= week_start + timedelta(days=6),
        models.Holiday.end_date >= week_start
    ).all()
    for holiday in db_holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)
    slots = []
    for d in dists:
        item = d.schedule_item
        for slot in (d.daily_schedule or []):
            try:
                day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                slot_date = d.week_start + timedelta(days=day_idx)
                if _is_holiday(slot_date, [], holiday_dates):
                    continue
                slots.append(schemas.DailySchedule(
                    day=slot["day"],
                    start_time=slot["start_time"],
                    end_time=slot["end_time"],
                    subject_name=item.subject.name,
                    teacher_name=item.teacher.name,
                    room_name=item.room.name,
                    group_name=item.group.name
                ))
            except ValueError:
                continue
    day_order = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4}
    slots.sort(key=lambda s: (day_order.get(s.day, 5), s.start_time))
    return slots


# ---- Hours tracking helpers ----
def calculate_assigned_hours(db: Session, schedule_item_id: int) -> schemas.HoursResponse:
    item = db.query(models.ScheduleItem).filter(models.ScheduleItem.id == schedule_item_id).first()
    if not item:
        raise ValueError("Schedule item not found")
    dists = db.query(models.WeeklyDistribution).filter(models.WeeklyDistribution.schedule_item_id == schedule_item_id).all()
    assigned_pairs = sum(len(d.daily_schedule or []) for d in dists)
    assigned_hours = assigned_pairs * PAIR_SIZE_AH
    total_hours = item.total_hours
    remaining = max(0.0, total_hours - assigned_hours)
    return schemas.HoursResponse(assigned_hours=assigned_hours, total_hours=total_hours, remaining_hours=remaining)


def calculate_hours_extended(db: Session, schedule_item_id: int) -> schemas.HoursExtendedResponse:
    base = calculate_assigned_hours(db, schedule_item_id)
    manual_entries = db.query(models.SubjectProgress).filter(models.SubjectProgress.schedule_item_id == schedule_item_id).all()
    manual_completed = sum(e.hours for e in manual_entries)
    effective = min(base.total_hours, base.assigned_hours + manual_completed)
    remaining = max(0.0, base.total_hours - effective)
    return schemas.HoursExtendedResponse(
        assigned_hours=base.assigned_hours,
        manual_completed_hours=manual_completed,
        effective_completed_hours=effective,
        total_hours=base.total_hours,
        remaining_hours=remaining,
    )


# ---- Teacher schedule items listing ----
def get_teacher_schedule_items(db: Session, teacher_name: str) -> List[schemas.ScheduleItemResponse]:
    teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
    if not teacher:
        raise ValueError("Teacher not found")
    items = (
        db.query(models.ScheduleItem)
        .filter(models.ScheduleItem.teacher_id == teacher.id)
        .all()
    )
    result = []
    for it in items:
        result.append(
            schemas.ScheduleItemResponse(
                id=it.id,
                subject_name=it.subject.name,
                group_name=it.group.name,
                room_name=it.room.name,
                total_hours=it.total_hours,
                weekly_hours=it.weekly_hours,
                week_type=it.week_type,
            )
        )
    return result


# ---- Teacher vacant slots (basic) ----
def _occupied_slots_for_teacher_week(db: Session, teacher_id: int, week_start: date) -> Dict[str, set]:
    occupied: Dict[str, set] = {d: set() for d in days}
    dists = (
        db.query(models.WeeklyDistribution)
        .join(models.ScheduleItem)
        .filter(models.WeeklyDistribution.week_start == week_start)
        .filter(models.ScheduleItem.teacher_id == teacher_id)
        .all()
    )
    for d in dists:
        for slot in d.daily_schedule or []:
            occupied[slot["day"]].add(slot["start_time"])
    # Also include DaySchedule entries if any for that date range
    for i in range(5):
        dt = week_start + timedelta(days=i)
        ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == dt).first()
        if not ds:
            continue
        for e in ds.entries:
            if e.teacher_id == teacher_id:
                day_name = days[i]
                occupied[day_name].add(e.start_time)
    return occupied


def get_vacant_slots_for_teacher(db: Session, teacher_name: str, week_start: date) -> List[Dict]:
    teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
    if not teacher:
        raise ValueError("Teacher not found")
    occ = _occupied_slots_for_teacher_week(db, teacher.id, week_start)
    result = []
    for i, dname in enumerate(days):
        # use both shifts time slots conservatively
        all_slots = {s["start"]: s for s in (SHIFT1_SLOTS + SHIFT2_SLOTS)}
        for start, slot in all_slots.items():
            if start not in occ[dname]:
                result.append({"day": dname, "start_time": slot["start"], "end_time": slot["end"]})
    return result


def add_teacher_slot(db: Session, teacher_name: str, week_start: date, slot_data: schemas.SlotCreate, schedule_item_id: int):
    teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
    if not teacher:
        raise ValueError("Teacher not found")
    dist = (
        db.query(models.WeeklyDistribution)
        .filter(models.WeeklyDistribution.week_start == week_start)
        .filter(models.WeeklyDistribution.schedule_item_id == schedule_item_id)
        .first()
    )
    if not dist:
        raise ValueError("Weekly distribution not found for provided schedule item and week_start")
    daily = dist.daily_schedule or []
    daily.append(
        {
            "day": slot_data.day,
            "start_time": slot_data.start_time,
            "end_time": slot_data.end_time,
            "subject_name": slot_data.subject_name,
            "teacher_name": teacher_name,
            "room_name": slot_data.room_name,
            "group_name": slot_data.group_name,
        }
    )
    dist.daily_schedule = daily
    db.add(dist)
    db.commit()
    db.refresh(dist)
    return dist


def edit_teacher_slot(db: Session, teacher_name: str, week_start: date, old_slot: schemas.SlotUpdate, new_slot: schemas.SlotCreate, schedule_item_id: int):
    dist = (
        db.query(models.WeeklyDistribution)
        .filter(models.WeeklyDistribution.week_start == week_start)
        .filter(models.WeeklyDistribution.schedule_item_id == schedule_item_id)
        .first()
    )
    if not dist:
        raise ValueError("Weekly distribution not found")
    daily = dist.daily_schedule or []
    found = False
    for s in daily:
        if s.get("day") == old_slot.day and s.get("start_time") == old_slot.start_time and s.get("group_name") == old_slot.group_name:
            s.update(
                {
                    "day": new_slot.day,
                    "start_time": new_slot.start_time,
                    "end_time": new_slot.end_time,
                    "subject_name": new_slot.subject_name,
                    "teacher_name": teacher_name,
                    "room_name": new_slot.room_name,
                    "group_name": new_slot.group_name,
                }
            )
            found = True
            break
    if not found:
        raise ValueError("Original slot not found")
    dist.daily_schedule = daily
    db.add(dist)
    db.commit()
    db.refresh(dist)
    return dist


def delete_teacher_slot(db: Session, teacher_name: str, week_start: date, slot: schemas.SlotUpdate, schedule_item_id: int):
    dist = (
        db.query(models.WeeklyDistribution)
        .filter(models.WeeklyDistribution.week_start == week_start)
        .filter(models.WeeklyDistribution.schedule_item_id == schedule_item_id)
        .first()
    )
    if not dist:
        raise ValueError("Weekly distribution not found")
    daily = dist.daily_schedule or []
    new_daily = [s for s in daily if not (s.get("day") == slot.day and s.get("start_time") == slot.start_time and s.get("group_name") == slot.group_name)]
    dist.daily_schedule = new_daily
    db.add(dist)
    db.commit()
    db.refresh(dist)
    return dist


# ---- Group-Teacher-Subject mapping ----
def link_group_teacher_subject(db: Session, group_name: str, teacher_name: str, subject_name: str) -> models.GroupTeacherSubject:
    group = get_or_create_group(db, group_name)
    teacher = get_or_create_teacher(db, teacher_name)
    subject = get_or_create_subject(db, subject_name)
    existing = (
        db.query(models.GroupTeacherSubject)
        .filter(
            models.GroupTeacherSubject.group_id == group.id,
            models.GroupTeacherSubject.teacher_id == teacher.id,
            models.GroupTeacherSubject.subject_id == subject.id,
        )
        .first()
    )
    if existing:
        return existing
    link = models.GroupTeacherSubject(group_id=group.id, teacher_id=teacher.id, subject_id=subject.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def list_group_teacher_subjects(db: Session) -> List[Dict]:
    links = db.query(models.GroupTeacherSubject).all()
    result = []
    for l in links:
        group = db.query(models.Group).get(l.group_id)
        teacher = db.query(models.Teacher).get(l.teacher_id)
        subject = db.query(models.Subject).get(l.subject_id)
        result.append({"id": l.id, "group_name": group.name, "teacher_name": teacher.name, "subject_name": subject.name})
    return result


# ---- Day plan scheduling with approvals ----
def _get_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def plan_day_schedule(db: Session, request: schemas.DayPlanCreateRequest) -> models.DaySchedule:
    logger.info("Plan day schedule: date=%s group=%s from_plan=%s", request.date, request.group_name, request.from_plan)
    # Find or create DaySchedule for the date
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == request.date).first()
    if not ds:
        ds = models.DaySchedule(date=request.date, status="pending")
        db.add(ds)
        db.commit()
        db.refresh(ds)
    else:
        # If the whole day is approved, do not allow any rebuilds
        if ds.status == "approved":
            raise ValueError("Day schedule is already approved for this date and cannot be modified")

    target_groups = None
    if request.group_name:
        g = db.query(models.Group).filter(models.Group.name == request.group_name).first()
        if not g:
            raise ValueError("Group not found")
        # Check if group is on practice
        if is_group_on_practice(db, g.id, request.date):
            logger.info("Group %s is on practice on %s, skipping schedule creation", g.name, request.date)
            raise ValueError(f"Group {g.name} is on practice on {request.date}")
        target_groups = {g.id}

    # Rebuild behavior: if group filter is provided, wipe all existing entries for this group; otherwise wipe all entries for the date
    if target_groups:
        # If this group's entries were approved earlier, do not allow overriding them
        approved_for_group = (
            db.query(models.DayScheduleEntry)
            .filter(models.DayScheduleEntry.day_schedule_id == ds.id)
            .filter(models.DayScheduleEntry.group_id.in_(target_groups))
            .filter(models.DayScheduleEntry.status == "approved")
            .first()
        )
        if approved_for_group:
            raise ValueError("Day plan for this group on this date is approved and cannot be modified")
        to_delete = (
            db.query(models.DayScheduleEntry)
            .filter(models.DayScheduleEntry.day_schedule_id == ds.id)
            .filter(models.DayScheduleEntry.group_id.in_(target_groups))
            .all()
        )
    else:
        to_delete = (
            db.query(models.DayScheduleEntry)
            .filter(models.DayScheduleEntry.day_schedule_id == ds.id)
            .all()
        )
    if to_delete:
        for e in to_delete:
            db.delete(e)
        # reset day status to pending on rebuild
        ds.status = "pending"
        db.add(ds)
        db.commit()
        db.refresh(ds)

    # Build entries
    debug_notes: list[str] = []
    if request.from_plan:
        week_start = _get_week_start(request.date)
        week_distributions = (
            db.query(models.WeeklyDistribution)
            .filter(models.WeeklyDistribution.week_start == week_start)
            .all()
        )
        dow = days[request.date.weekday()]
        for dist in week_distributions:
            item = dist.schedule_item
            if target_groups and item.group_id not in target_groups:
                continue
            # Check if group is on practice - skip if so
            if is_group_on_practice(db, item.group_id, request.date):
                group = db.query(models.Group).get(item.group_id)
                group_name = group.name if group else str(item.group_id)
                logger.info("Group %s (id=%s) is on practice on %s, skipping from plan", group_name, item.group_id, request.date)
                debug_notes.append(f"Группа {group_name} на практике, пары из недельного плана не добавляются")
                continue
            for slot in dist.daily_schedule or []:
                if slot.get("day") != dow:
                    continue
                # Avoid duplicates
                exists = (
                    db.query(models.DayScheduleEntry)
                    .filter(models.DayScheduleEntry.day_schedule_id == ds.id)
                    .filter(models.DayScheduleEntry.group_id == item.group_id)
                    .filter(models.DayScheduleEntry.start_time == slot["start_time"])  # per group per start time
                    .first()
                )
                if exists:
                    debug_notes.append(
                        f"Пропущено: у группы {db.query(models.Group).get(item.group_id).name} уже есть пара в {slot['start_time']}"
                    )
                    continue
                # Check teacher availability within this day's plan only (ignore weekly by default)
                if not _teacher_is_free(db, item.teacher_id, request.date, slot["start_time"], slot["end_time"], ignore_weekly=True):
                    tname = db.query(models.Teacher).get(item.teacher_id).name
                    debug_notes.append(
                        f"Пропущено: преподаватель занят в дневном плане {tname} на {slot['start_time']}"
                    )
                    continue
                entry = models.DayScheduleEntry(
                    day_schedule_id=ds.id,
                    group_id=item.group_id,
                    subject_id=item.subject_id,
                    teacher_id=item.teacher_id,
                    room_id=item.room_id,
                    start_time=slot["start_time"],
                    end_time=slot["end_time"],
                    status="pending",
                    schedule_item_id=item.id,
                )
                db.add(entry)
                debug_notes.append(
                    f"Добавлено из недельного плана: {db.query(models.Group).get(item.group_id).name} — {db.query(models.Subject).get(item.subject_id).name} ({db.query(models.Teacher).get(item.teacher_id).name}) {db.query(models.Room).get(item.room_id).name} {slot['start_time']}-{slot['end_time']}"
                )
        db.commit()
        # Enforce no-gaps and optional cap for every group present in the day (or only target groups if set)
        cap = request.max_pairs_per_day or 0
        if bool(request.enforce_no_gaps):
            group_ids = (
                {gid for (gid,) in db.query(models.DayScheduleEntry.group_id).filter(models.DayScheduleEntry.day_schedule_id == ds.id).distinct()}
                if not target_groups else target_groups
            )
            for gid in group_ids:
                q = (
                    db.query(models.DayScheduleEntry)
                    .filter(models.DayScheduleEntry.day_schedule_id == ds.id, models.DayScheduleEntry.group_id == gid)
                )
                entries = q.all()
                if not entries:
                    continue
                # Sort by time and keep longest prefix without gaps according to group's shift slots
                group = db.query(models.Group).get(gid)
                slots = _get_time_slots_for_group(group.name, enable_shifts=True)
                index_by_start = {s["start"]: i for i, s in enumerate(slots)}
                ordered = sorted(entries, key=lambda e: e.start_time)
                keep_seq: list[models.DayScheduleEntry] = []
                last_idx: int | None = None
                for e in ordered:
                    idx = index_by_start.get(e.start_time)
                    if idx is None:
                        continue
                    if last_idx is None or idx == last_idx + 1:
                        keep_seq.append(e)
                        last_idx = idx
                    else:
                        # gap encountered -> stop to ensure consecutive block
                        break
                # Apply cap if needed
                if cap and len(keep_seq) > cap:
                    keep_seq = keep_seq[:cap]
                    _last_plan_debug.setdefault(ds.id, []).append(
                        f"Группа {group.name}: ограничено {cap} парами (max_pairs_per_day)"
                    )
                keep_ids = {e.id for e in keep_seq}
                # Delete others with detailed reasons
                removed = 0
                for e in entries:
                    if e.id not in keep_ids:
                        subj = db.query(models.Subject).get(e.subject_id)
                        t = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
                        room = db.query(models.Room).get(e.room_id)
                        _last_plan_debug.setdefault(ds.id, []).append(
                            f"Удалено для непрерывности: {group.name} — {subj.name if subj else e.subject_id} ({t.name if t else '-'}) {room.name if room else e.room_id} {e.start_time}-{e.end_time}"
                        )
                        db.delete(e)
                        removed += 1
                db.commit()
        # If debug requested and no notes yet, add a friendly message
        if request.debug and not debug_notes:
            debug_notes.append("Сгенерировано по недельному плану: конфликтов в пределах дня не обнаружено")
    else:
        # Generate feasible pairs for the requested week/day without using existing daily_schedule
        week_start = _get_week_start(request.date)
        week_end = week_start + timedelta(days=4)
        dow = days[request.date.weekday()]
        # Collect holidays within this business week
        holiday_dates = set()
        db_holidays = db.query(models.Holiday).filter(
            models.Holiday.start_date <= week_end,
            models.Holiday.end_date >= week_start,
        ).all()
        for h in db_holidays:
            cur = h.start_date
            while cur <= h.end_date:
                holiday_dates.add(cur)
                cur += timedelta(days=1)

        # Try to use weekly distributions for this week; if none exist fall back to raw schedule items
        q = db.query(models.WeeklyDistribution).join(models.ScheduleItem).filter(
            models.WeeklyDistribution.week_start == week_start
        )
        if target_groups:
            q = q.filter(models.ScheduleItem.group_id.in_(target_groups))
        dists = q.all()

        occupied_teacher: set[tuple] = set()
        occupied_group: set[tuple] = set()
        room_occupancy: defaultdict = defaultdict(int)
        gym_teachers: defaultdict = defaultdict(set)
        # Cap total pairs per group for this day to keep variety
        per_group_daily_cap = max(1, int(request.max_pairs_per_day or 3))

        # Build candidate items with weekly hours for this week
        is_even_week = (week_start.isocalendar().week % 2 == 0)
        items_by_group: dict[int, list[tuple[models.ScheduleItem, float]]] = {}
        if dists:
            for d in dists:
                it = d.schedule_item
                if target_groups and it.group_id not in target_groups:
                    continue
                wh = d.hours_even if d.is_even_week else d.hours_odd
                if wh and wh > 0:
                    items_by_group.setdefault(it.group_id, []).append((it, wh))
        else:
            items_q = db.query(models.ScheduleItem)
            if target_groups:
                items_q = items_q.filter(models.ScheduleItem.group_id.in_(target_groups))
            for it in items_q.all():
                wh = _distribute_hours(it.weekly_hours, it.week_type, is_even_week)
                if wh and wh > 0:
                    items_by_group.setdefault(it.group_id, []).append((it, wh))

        # For each group, fill earliest slots consecutively without gaps if possible
        for gid, candidates in items_by_group.items():
            if not candidates:
                continue
            group = db.query(models.Group).get(gid)
            if not group:
                continue
            # Check if group is on practice - skip if so
            if is_group_on_practice(db, gid, request.date):
                logger.info("Group %s (id=%s) is on practice on %s, skipping", group.name, gid, request.date)
                debug_notes.append(f"Группа {group.name} на практике, расписание не создается")
                continue
            # Subject repeat control per day
            subj_repeat: defaultdict = defaultdict(int)
            # Slots ordered by time для смены группы, или обе смены при запросе
            if bool(request.use_both_shifts):
                slots = SHIFT1_SLOTS + SHIFT2_SLOTS
            else:
                slots = _get_time_slots_for_group(group.name, enable_shifts=True)
            # Поддержка отладочного сообщения ниже (переменная на кириллице, чтобы избежать NameError в f-строке)
            слотов = slots
            # We'll try to fill slots in order
            # MINIMUM 3 PAIRS PER GROUP (starting from first lesson)
            min_pairs = 3
            target_pairs = max(min_pairs, per_group_daily_cap)
            total_added = 0
            started = False
            for slot in slots:
                if total_added >= target_pairs:
                    break
                start = slot["start"]
                end = slot["end"]
                # Skip if group is already occupied at this time (shouldn't happen within this loop but keep safety)
                if (request.date, start, gid) in occupied_group:
                    continue
                # If группа занята по дневному/недельному плану — фиксируем причину и прекращаем, чтобы не создавать окно
                is_free_group, gb = _group_is_free(db, gid, request.date, start, end, ignore_weekly=bool(request.ignore_weekly_conflicts))
                if not is_free_group:
                    subj_name = db.query(models.Subject).get(gb.get("subject_id")).name if gb and gb.get("subject_id") else ""
                    teacher_name = db.query(models.Teacher).get(gb.get("teacher_id")).name if gb and gb.get("teacher_id") else ""
                    room_name = db.query(models.Room).get(gb.get("room_id")).name if gb and gb.get("room_id") else ""
                    src = "дневному плану" if gb and gb.get("source") == "day" else "недельному плану"
                    msg = f"Группа {group.name} уже занята по {src} в {start}: {subj_name} ({teacher_name}) {room_name}"
                    debug_notes.append(msg)
                    if started:
                        break
                    else:
                        continue
                # Choose a candidate item whose teacher/room is free and subject repeat within cap
                picked_item: models.ScheduleItem | None = None
                random.shuffle(candidates)
                reasons_for_slot: list[str] = []
                for it, wh in candidates:
                    # Subject repeat cap
                    if bool(request.allow_repeated_subjects):
                        subject_repeat_cap = max(1, int(request.max_repeats_per_subject or 2))
                    else:
                        subject_repeat_cap = 1
                    if subj_repeat[it.subject_id] >= subject_repeat_cap:
                        subj_name = db.query(models.Subject).get(it.subject_id).name
                        reasons_for_slot.append(f"Достигнут лимит повторов предмета: {subj_name}")
                        continue
                    # Check room capacity and occupancy
                    room = db.query(models.Room).get(it.room_id)
                    capacity = 4 if (room and "Спортзал" in room.name) else 1
                    room_key = (request.date, start, it.room_id)
                    gym_key = (request.date, start, it.room_id)
                    if room_occupancy[room_key] >= capacity:
                        room_name = room.name if room else str(it.room_id)
                        reasons_for_slot.append(f"Аудитория заполнена: {room_name}")
                        continue
                    # Teacher availability
                    if not _teacher_is_free(db, it.teacher_id, request.date, start, end, ignore_weekly=bool(request.ignore_weekly_conflicts)):
                        teacher_name = db.query(models.Teacher).get(it.teacher_id).name
                        reasons_for_slot.append(f"Преподаватель занят: {teacher_name}")
                        continue
                    # If sports hall, avoid assigning same teacher multiple classes in same slot
                    if room and "Спортзал" in room.name and it.teacher_id in gym_teachers[gym_key]:
                        teacher_name = db.query(models.Teacher).get(it.teacher_id).name
                        reasons_for_slot.append(f"Спортзал: преподаватель уже назначен в этом слоте: {teacher_name}")
                        continue
                    picked_item = it
                    break
                if not picked_item:
                    # If already started assigning for this group, stop to avoid a gap (window)
                    if started:
                        if reasons_for_slot:
                            debug_notes.append(
                                f"Группа {group.name}: остановились на {start} — нет доступных кандидатов. Причины: {', '.join(sorted(set(reasons_for_slot)))}"
                            )
                        else:
                            debug_notes.append(f"Группа {group.name}: остановились на {start} — нет кандидатов")
                        break
                    # Not started yet: try next slot (we will start later, which is not an internal window)
                    continue
                # Create entry
                e = models.DayScheduleEntry(
                    day_schedule_id=ds.id,
                    group_id=gid,
                    subject_id=picked_item.subject_id,
                    teacher_id=picked_item.teacher_id,
                    room_id=picked_item.room_id,
                    start_time=start,
                    end_time=end,
                    status="pending",
                    schedule_item_id=picked_item.id,
                )
                db.add(e)
                # Update occupancies
                teacher_key = (request.date, start, picked_item.teacher_id)
                group_key = (request.date, start, gid)
                room_key = (request.date, start, picked_item.room_id)
                occupied_teacher.add(teacher_key)
                occupied_group.add(group_key)
                room_occupancy[room_key] += 1
                if room and "Спортзал" in room.name:
                    gym_teachers[(request.date, start, picked_item.room_id)].add(picked_item.teacher_id)
                total_added += 1
                subj_repeat[picked_item.subject_id] += 1
                started = True
            # If we filled fewer than cap and ran out of slots, note that
            if total_added < target_pairs and len(slots) < target_pairs:
                debug_notes.append(
                    f"Группа {group.name}: всего {len(слотов)} слотов в смене; требуется минимум {min_pairs}. Включите use_both_shifts или расширьте сетку слотов."
                )
            # Warn if minimum not met
            elif total_added < min_pairs:
                debug_notes.append(
                    f"Группа {group.name}: удалось создать только {total_added} пар(ы), минимум - {min_pairs}"
                )
        db.commit()
    # Save debug notes for this day
    _last_plan_debug[ds.id] = debug_notes
    db.refresh(ds)
    logger.info("Day plan id=%s has %d entries", ds.id, len(ds.entries))
    return ds


def _teacher_is_free(
    db: Session,
    teacher_id: int,
    date_: date,
    start_time: str,
    end_time: str,
    exclude_entry_id: int | None = None,
    *,
    ignore_weekly: bool = False,
) -> bool:
    # Check DaySchedule on that date
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if ds:
        q = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.day_schedule_id == ds.id, models.DayScheduleEntry.teacher_id == teacher_id, models.DayScheduleEntry.start_time == start_time)
        if exclude_entry_id:
            q = q.filter(models.DayScheduleEntry.id != exclude_entry_id)
        if q.first():
            return False
    # Optionally skip weekly plan conflicts
    if ignore_weekly:
        return True
    # Check weekly plan
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


def _group_is_free(
    db: Session,
    group_id: int,
    date_: date,
    start_time: str,
    end_time: str,
    *,
    ignore_weekly: bool = False,
) -> tuple[bool, dict | None]:
    # Check DaySchedule on that date
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if ds:
        e = (
            db.query(models.DayScheduleEntry)
            .filter(
                models.DayScheduleEntry.day_schedule_id == ds.id,
                models.DayScheduleEntry.group_id == group_id,
                models.DayScheduleEntry.start_time == start_time,
            )
            .first()
        )
        if e:
            return False, {
                "source": "day",
                "subject_id": e.subject_id,
                "teacher_id": e.teacher_id,
                "room_id": e.room_id,
            }
    # Optionally skip weekly plan conflicts
    if ignore_weekly:
        return True, None
    # Check weekly plan
    week_start = _get_week_start(date_)
    dname = days[date_.weekday()]
    dists = (
        db.query(models.WeeklyDistribution)
        .join(models.ScheduleItem)
        .filter(models.WeeklyDistribution.week_start == week_start, models.ScheduleItem.group_id == group_id)
        .all()
    )
    for d in dists:
        for slot in d.daily_schedule or []:
            if slot.get("day") == dname and slot.get("start_time") == start_time:
                it = d.schedule_item
                return False, {
                    "source": "weekly",
                    "subject_id": it.subject_id,
                    "teacher_id": it.teacher_id,
                    "room_id": it.room_id,
                }
    return True, None


def _is_placeholder_teacher_name(name: str | None) -> bool:
    """Treat teacher names like 'Vacant', 'Вакант', 'Unknown' (any case) as placeholders.
    Also handles common substrings in RU/EN to be robust to dataset variations.
    """
    if not name:
        return True
    n = name.strip().casefold()
    placeholders = {"vacant", "unknown", "вакант", "вакансия"}
    if n in placeholders:
        return True
    # Heuristic substring match to catch variations like 'вакант.', 'неизвестно', etc.
    for sub in ("vacan", "unknown", "неизвест", "вакан"):
        if sub in n:
            return True
    return False


def _is_placeholder_room_name(name: str | None) -> bool:
    """Treat room names like 'Без аудитории', 'Empty', 'None', '—' as placeholders.
    This allows representing an intentionally cleared room without NULLs.
    """
    if name is None:
        return True
    n = name.strip().casefold()
    if n in {"без аудитории", "empty", "none", "-", "—", "(пусто)", "пусто"}:
        return True
    # Heuristic to catch variations
    for sub in ("без ауд", "empty", "none", "пуст"):
        if sub in n:
            return True
    return False


def get_or_create_empty_room(db: Session) -> models.Room:
    """Return a dedicated placeholder room used to mark 'no room'."""
    name = "Без аудитории"
    r = db.query(models.Room).filter(models.Room.name == name).first()
    if r:
        return r
    r = models.Room(name=name)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def replace_vacant_auto(db: Session, day_schedule_id: int) -> Dict:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.id == day_schedule_id).first()
    if not ds:
        raise ValueError("Day schedule not found")
    replaced = 0
    logger.info("[VACANT] Start auto-replace for day_id=%s, date=%s", ds.id, ds.date)
    for e in list(ds.entries):
        # Teacher considered vacant if teacher is None or has a placeholder name (case-insensitive, RU/EN)
        teacher = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
        if teacher and not _is_placeholder_teacher_name(teacher.name):
            continue
        grp = db.query(models.Group).get(e.group_id)
        subj = db.query(models.Subject).get(e.subject_id)
        logger.info("[VACANT] Entry id=%s %s %s-%s group=%s subject=%s teacher=%s -> searching candidates", e.id, ds.date, e.start_time, e.end_time, grp.name if grp else e.group_id, subj.name if subj else e.subject_id, teacher.name if teacher else None)
        # Find candidates linked to this group
        links_all = db.query(models.GroupTeacherSubject).filter(models.GroupTeacherSubject.group_id == e.group_id).all()
        # Prefer links matching the same subject; fallback to any link for the group
        preferred = [l for l in links_all if l.subject_id == e.subject_id]
        others = [l for l in links_all if l.subject_id != e.subject_id]
        candidates = preferred if preferred else others
        random.shuffle(candidates)
        logger.info("[VACANT] Candidates: preferred=%d others=%d", len(preferred), len(others))
        picked = None
        for l in candidates:
            cand_teacher = db.query(models.Teacher).get(l.teacher_id)
            cand_subject = db.query(models.Subject).get(l.subject_id)
            if not cand_teacher:
                logger.info("[VACANT] Skip candidate: teacher not found id=%s", l.teacher_id)
                continue
            if not _teacher_is_free(db, l.teacher_id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
                logger.info("[VACANT] Busy: %s at %s-%s", cand_teacher.name, e.start_time, e.end_time)
                continue
            # Assign teacher and subject from mapping
            e.teacher_id = l.teacher_id
            e.subject_id = l.subject_id
            e.status = "replaced_auto"
            db.add(e)
            replaced += 1
            picked = (cand_teacher.name, cand_subject.name if cand_subject else None)
            logger.info("[VACANT] Replaced entry id=%s -> teacher=%s subject=%s", e.id, picked[0], picked[1])
            break
        if not picked:
            logger.info("[VACANT] No available candidates for entry id=%s", e.id)
    db.commit()
    logger.info("[VACANT] Auto-replace completed: replaced=%d", replaced)
    return {"replaced": replaced}


def replace_entry_manual(db: Session, entry_id: int, teacher_name: str) -> Dict:
    e = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.id == entry_id).first()
    if not e:
        raise ValueError("Entry not found")
    teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
    if not teacher:
        raise ValueError("Teacher not found")
    # Choose subject according to mapping if available; otherwise keep existing subject
    link = (
        db.query(models.GroupTeacherSubject)
        .filter(models.GroupTeacherSubject.group_id == e.group_id, models.GroupTeacherSubject.teacher_id == teacher.id)
        .first()
    )
    new_subject_id = link.subject_id if link else e.subject_id
    # Verify availability
    ds = db.query(models.DaySchedule).get(e.day_schedule_id)
    if not _teacher_is_free(db, teacher.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
        raise ValueError("Teacher is not available at this time")
    # Keep previous snapshot for reporting
    prev_teacher = db.query(models.Teacher).get(e.teacher_id).name if e.teacher_id else None
    prev_subject = db.query(models.Subject).get(e.subject_id).name if e.subject_id else None
    e.teacher_id = teacher.id
    e.subject_id = new_subject_id
    e.status = "replaced_manual"
    db.add(e)
    db.commit()
    # Compose detailed response with validation snapshot for the group
    report = analyze_day_schedule(db, e.day_schedule_id, group_name=db.query(models.Group).get(e.group_id).name)
    return {
        "entry_id": e.id,
        "old": {"teacher_name": prev_teacher, "subject_name": prev_subject},
        "new": {
            "teacher_name": teacher.name,
            "subject_name": db.query(models.Subject).get(new_subject_id).name if new_subject_id else None,
        },
        "status": e.status,
        "report": report,
    }


def _room_has_capacity(db: Session, date_: date, start_time: str, room_id: int, exclude_entry_id: int | None = None) -> bool:
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


def update_entry_manual(
    db: Session,
    entry_id: int,
    *,
    teacher_name: str | None = None,
    subject_name: str | None = None,
    room_name: str | None = None,
) -> Dict:
    e = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.id == entry_id).first()
    if not e:
        raise ValueError("Entry not found")
    ds = db.query(models.DaySchedule).get(e.day_schedule_id)
    if not ds:
        raise ValueError("Day schedule not found")
    updates: Dict[str, str] = {}
    prev = {
        "teacher_name": (db.query(models.Teacher).get(e.teacher_id).name if e.teacher_id else None),
        "subject_name": (db.query(models.Subject).get(e.subject_id).name if e.subject_id else None),
        "room_name": (db.query(models.Room).get(e.room_id).name if e.room_id else None),
    }
    # Teacher update
    if teacher_name:
        teacher = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
        if not teacher:
            raise ValueError("Teacher not found")
        if not _teacher_is_free(db, teacher.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
            raise ValueError("Teacher is not available at this time")
        e.teacher_id = teacher.id
        updates["teacher_name"] = teacher.name
        # If subject not explicitly provided, try to align subject via mapping
        if not subject_name:
            link = (
                db.query(models.GroupTeacherSubject)
                .filter(models.GroupTeacherSubject.group_id == e.group_id, models.GroupTeacherSubject.teacher_id == teacher.id)
                .first()
            )
            if link:
                e.subject_id = link.subject_id
    # Subject update
    if subject_name:
        subj = db.query(models.Subject).filter(models.Subject.name == subject_name).first()
        if not subj:
            subj = get_or_create_subject(db, subject_name)
        e.subject_id = subj.id
        updates["subject_name"] = subj.name
    # Room update
    if room_name:
        room = db.query(models.Room).filter(models.Room.name == room_name).first()
        if not room:
            room = get_or_create_room(db, room_name)
        if not _room_has_capacity(db, ds.date, e.start_time, room.id, exclude_entry_id=e.id):
            raise ValueError("Room is not available at this time")
        e.room_id = room.id
        updates["room_name"] = room.name
    if not updates:
        raise ValueError("No changes provided")
    e.status = "replaced_manual"
    db.add(e)
    db.commit()
    new = {
        "teacher_name": (db.query(models.Teacher).get(e.teacher_id).name if e.teacher_id else None),
        "subject_name": (db.query(models.Subject).get(e.subject_id).name if e.subject_id else None),
        "room_name": (db.query(models.Room).get(e.room_id).name if e.room_id else None),
    }
    report = analyze_day_schedule(db, e.day_schedule_id, group_name=db.query(models.Group).get(e.group_id).name)
    return {"entry_id": e.id, "old": prev, "new": new, "status": e.status, "report": report}


def get_entry_replacement_options(
    db: Session,
    entry_id: int,
    *,
    limit_teachers: int | None = 20,
    limit_rooms: int | None = 20,
) -> Dict:
    e = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.id == entry_id).first()
    if not e:
        raise ValueError("Entry not found")
    ds = db.query(models.DaySchedule).get(e.day_schedule_id)
    if not ds:
        raise ValueError("Day schedule not found")
    group = db.query(models.Group).get(e.group_id)
    subject = db.query(models.Subject).get(e.subject_id)
    # Teachers: priority by mapping for (group, subject) -> (group, any subject) -> any free
    teacher_opts: list[dict] = []
    seen_teachers: set[int] = set()
    # 1) Group-Subject mapping
    mapped_same = (
        db.query(models.GroupTeacherSubject)
        .filter(models.GroupTeacherSubject.group_id == e.group_id, models.GroupTeacherSubject.subject_id == e.subject_id)
        .all()
    )
    for l in mapped_same:
        t = db.query(models.Teacher).get(l.teacher_id)
        if not t or t.id in seen_teachers:
            continue
        if _teacher_is_free(db, t.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
            teacher_opts.append({"teacher_name": t.name, "source": "group_subject_mapping"})
            seen_teachers.add(t.id)
            if limit_teachers and len(teacher_opts) >= limit_teachers:
                break
    # 2) Group-any mapping
    if not limit_teachers or len(teacher_opts) < limit_teachers:
        mapped_any = (
            db.query(models.GroupTeacherSubject)
            .filter(models.GroupTeacherSubject.group_id == e.group_id)
            .all()
        )
        for l in mapped_any:
            if l.teacher_id in seen_teachers:
                continue
            t = db.query(models.Teacher).get(l.teacher_id)
            if not t:
                continue
            if _teacher_is_free(db, t.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
                teacher_opts.append({"teacher_name": t.name, "source": "group_mapping"})
                seen_teachers.add(t.id)
                if limit_teachers and len(teacher_opts) >= limit_teachers:
                    break
    # 3) Any free teacher
    if not limit_teachers or len(teacher_opts) < limit_teachers:
        all_teachers = db.query(models.Teacher).all()
        for t in all_teachers:
            if t.id in seen_teachers:
                continue
            if _teacher_is_free(db, t.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
                teacher_opts.append({"teacher_name": t.name, "source": "free"})
                seen_teachers.add(t.id)
                if limit_teachers and len(teacher_opts) >= limit_teachers:
                    break

    # Rooms: any room with available capacity
    room_opts: list[dict] = []
    all_rooms = db.query(models.Room).all()
    for r in all_rooms:
        if _room_has_capacity(db, ds.date, e.start_time, r.id, exclude_entry_id=e.id):
            cap = 4 if (r and "Спортзал" in r.name) else 1
            room_opts.append({"room_name": r.name, "capacity": cap})
            if limit_rooms and len(room_opts) >= limit_rooms:
                break

    return {
        "entry_id": e.id,
        "date": ds.date,
        "group_name": group.name if group else str(e.group_id),
        "subject_name": subject.name if subject else str(e.subject_id),
        "start_time": e.start_time,
        "end_time": e.end_time,
        "teachers": teacher_opts,
        "rooms": room_opts,
    }


def _get_room_by_name(db: Session, room_name: str):
    return db.query(models.Room).filter(models.Room.name == room_name).first()


def _list_conflicts_for_room(db: Session, date_: date, start_time: str, room_id: int, *, exclude_entry_id: int | None = None) -> list[models.DayScheduleEntry]:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if not ds:
        return []
    q = (
        db.query(models.DayScheduleEntry)
        .filter(models.DayScheduleEntry.day_schedule_id == ds.id)
        .filter(models.DayScheduleEntry.room_id == room_id)
        .filter(models.DayScheduleEntry.start_time == start_time)
    )
    if exclude_entry_id:
        q = q.filter(models.DayScheduleEntry.id != exclude_entry_id)
    return q.all()


def propose_room_swap(
    db: Session,
    entry_id: int,
    desired_room_name: str,
    *,
    limit_alternatives: int | None = 5,
) -> schemas.RoomSwapPlanResponse:
    e = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.id == entry_id).first()
    if not e:
        raise ValueError("Entry not found")
    ds = db.query(models.DaySchedule).get(e.day_schedule_id)
    room = _get_room_by_name(db, desired_room_name)
    if not room:
        raise ValueError("Room not found")
    # If room has capacity -> no conflicts
    if _room_has_capacity(db, ds.date, e.start_time, room.id, exclude_entry_id=e.id):
        return schemas.RoomSwapPlanResponse(
            entry_id=e.id,
            date=ds.date,
            start_time=e.start_time,
            end_time=e.end_time,
            desired_room_name=room.name,
            is_free=True,
            conflicts=[],
            can_auto_resolve=True,
        )
    # Otherwise find conflicts and alternatives for each
    conflicts = _list_conflicts_for_room(db, ds.date, e.start_time, room.id, exclude_entry_id=e.id)
    conflict_items: list[schemas.RoomSwapConflictItem] = []
    can_auto = True
    for c in conflicts:
        g = db.query(models.Group).get(c.group_id)
        s = db.query(models.Subject).get(c.subject_id)
        t = db.query(models.Teacher).get(c.teacher_id) if c.teacher_id else None
        # Alternatives: any room with capacity for c's slot (excluding c itself)
        alt_rooms: list[str] = []
        for r in db.query(models.Room).all():
            if r.id == room.id:
                continue
            if _room_has_capacity(db, ds.date, c.start_time, r.id, exclude_entry_id=c.id):
                alt_rooms.append(r.name)
                if limit_alternatives and len(alt_rooms) >= limit_alternatives:
                    break
        if not alt_rooms:
            can_auto = False
        conflict_items.append(
            schemas.RoomSwapConflictItem(
                entry_id=c.id,
                group_name=g.name if g else str(c.group_id),
                subject_name=s.name if s else str(c.subject_id),
                teacher_name=(t.name if t else None),
                room_name=db.query(models.Room).get(c.room_id).name if c.room_id else "",
                alternatives=alt_rooms,
            )
        )
    return schemas.RoomSwapPlanResponse(
        entry_id=e.id,
        date=ds.date,
        start_time=e.start_time,
        end_time=e.end_time,
        desired_room_name=room.name,
        is_free=False,
        conflicts=conflict_items,
        can_auto_resolve=can_auto,
    )


def execute_room_swap(
    db: Session,
    entry_id: int,
    desired_room_name: str,
    *,
    choices: list[schemas.RoomSwapChoice] | None = None,
    dry_run: bool = False,
) -> Dict:
    plan = propose_room_swap(db, entry_id, desired_room_name)
    e = db.query(models.DayScheduleEntry).get(entry_id)
    ds = db.query(models.DaySchedule).get(e.day_schedule_id)
    desired_room = _get_room_by_name(db, desired_room_name)
    if plan.is_free:
        if dry_run:
            return {"changed": [{"entry_id": e.id, "old_room": db.query(models.Room).get(e.room_id).name, "new_room": desired_room.name}], "dry_run": True}
        old_room_name = db.query(models.Room).get(e.room_id).name if e.room_id else None
        e.room_id = desired_room.id
        e.status = "replaced_manual"
        db.add(e)
        db.commit()
        report = analyze_day_schedule(db, ds.id, group_name=db.query(models.Group).get(e.group_id).name)
        return {"changed": [{"entry_id": e.id, "old_room": old_room_name, "new_room": desired_room.name}], "report": report}
    # Need to reassign conflicts
    # Build mapping from conflict entry to new room
    mapping: dict[int, str] = {}
    if choices:
        for ch in choices:
            mapping[ch.entry_id] = ch.room_name
    changes: list[dict] = []
    # Resolve each conflict
    for c in plan.conflicts:
        new_room_name = mapping.get(c.entry_id)
        if not new_room_name:
            if not c.alternatives:
                raise ValueError(f"No alternative room for entry {c.entry_id}")
            new_room_name = c.alternatives[0]
        new_room = _get_room_by_name(db, new_room_name)
        if not new_room:
            raise ValueError(f"Room not found: {new_room_name}")
        # Validate capacity still available
        if not _room_has_capacity(db, ds.date, e.start_time, new_room.id, exclude_entry_id=c.entry_id):
            raise ValueError(f"Room not available now: {new_room_name}")
        if dry_run:
            changes.append({"entry_id": c.entry_id, "old_room": c.room_name, "new_room": new_room.name})
        else:
            ce = db.query(models.DayScheduleEntry).get(c.entry_id)
            ce.room_id = new_room.id
            ce.status = "replaced_manual"
            db.add(ce)
            changes.append({"entry_id": ce.id, "old_room": c.room_name, "new_room": new_room.name})
    # After conflicts resolved, assign desired room to main entry
    if dry_run:
        changes.append({"entry_id": e.id, "old_room": db.query(models.Room).get(e.room_id).name if e.room_id else None, "new_room": desired_room.name})
        return {"changed": changes, "dry_run": True}
    old_room_name = db.query(models.Room).get(e.room_id).name if e.room_id else None
    e.room_id = desired_room.id
    e.status = "replaced_manual"
    db.add(e)
    changes.append({"entry_id": e.id, "old_room": old_room_name, "new_room": desired_room.name})
    db.commit()
    report = analyze_day_schedule(db, ds.id)
    return {"changed": changes, "report": report}


def analyze_day_schedule(db: Session, day_schedule_id: int, group_name: str | None = None) -> Dict:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.id == day_schedule_id).first()
    if not ds:
        raise ValueError("Day schedule not found")
    target_group_ids: set[int] | None = None
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if not g:
            raise ValueError("Group not found")
        target_group_ids = {g.id}

    # Aggregations
    teacher_slots: dict[tuple[str, int], list[models.DayScheduleEntry]] = defaultdict(list)
    room_slots: dict[tuple[str, int], list[models.DayScheduleEntry]] = defaultdict(list)
    group_slots: dict[tuple[int, str], list[models.DayScheduleEntry]] = defaultdict(list)
    per_group_entries: dict[int, list[models.DayScheduleEntry]] = defaultdict(list)
    issues: list[dict] = []
    unknown_teacher_count: dict[int, int] = defaultdict(int)

    for e in ds.entries:
        if target_group_ids and e.group_id not in target_group_ids:
            continue
        teacher = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
        room = db.query(models.Room).get(e.room_id)
        grp = db.query(models.Group).get(e.group_id)
        key_t = (e.start_time, e.teacher_id or -1)
        key_r = (e.start_time, e.room_id)
        key_g = (e.group_id, e.start_time)
        teacher_slots[key_t].append(e)
        room_slots[key_r].append(e)
        group_slots[key_g].append(e)
        per_group_entries[e.group_id].append(e)
        # Placeholder/unknown teacher warning
        if (teacher is None) or _is_placeholder_teacher_name(teacher.name if teacher else None):
            unknown_teacher_count[e.group_id] += 1
            issues.append({
                "code": "unknown_teacher",
                "severity": "warning",
                "message": f"Группа {grp.name}: не назначен преподаватель для {e.start_time}",
                "entry_ids": [e.id],
                "group_name": grp.name,
                "teacher_name": (teacher.name if teacher else None),
            })

    # Conflicts: teacher double-booking
    for (start_time, teacher_id), entries in teacher_slots.items():
        if teacher_id == -1:
            continue
        if len(entries) > 1:
            t = db.query(models.Teacher).get(teacher_id)
            entry_ids = [e.id for e in entries]
            groups = [db.query(models.Group).get(e.group_id).name for e in entries]
            issues.append({
                "code": "teacher_conflict",
                "severity": "blocker",
                "message": f"Преподаватель {t.name if t else teacher_id} имеет {len(entries)} пар(ы) одновременно в {start_time} (группы: {', '.join(groups)})",
                "entry_ids": entry_ids,
                "teacher_name": (t.name if t else None),
            })

    # Conflicts: room capacity
    for (start_time, room_id), entries in room_slots.items():
        room = db.query(models.Room).get(room_id)
        capacity = 4 if (room and "Спортзал" in room.name) else 1
        if len(entries) > capacity:
            entry_ids = [e.id for e in entries]
            issues.append({
                "code": "room_capacity",
                "severity": "blocker",
                "message": f"Аудитория {room.name if room else room_id} перегружена в {start_time}: {len(entries)} / {capacity}",
                "entry_ids": entry_ids,
                "room_name": (room.name if room else None),
            })

    # Conflicts: group duplicate slot
    for (group_id, start_time), entries in group_slots.items():
        if len(entries) > 1:
            grp = db.query(models.Group).get(group_id)
            entry_ids = [e.id for e in entries]
            issues.append({
                "code": "group_duplicate_slot",
                "severity": "blocker",
                "message": f"Группа {grp.name} имеет несколько пар в {start_time}",
                "entry_ids": entry_ids,
                "group_name": grp.name,
            })

    # Windows (gaps) per group
    groups_report: list[dict] = []
    for gid, entries in per_group_entries.items():
        grp = db.query(models.Group).get(gid)
        # Determine slots order for this group's shift
        slots = _get_time_slots_for_group(grp.name, enable_shifts=True)
        order = {s["start"]: idx for idx, s in enumerate(slots)}
        ordered_entries = sorted([e for e in entries if e.start_time in order], key=lambda e: order[e.start_time])
        windows = 0
        duplicates = 0
        for (gk, st), ent in group_slots.items():
            if gk == gid and len(ent) > 1:
                duplicates += 1
        for i in range(1, len(ordered_entries)):
            prev_idx = order[ordered_entries[i - 1].start_time]
            cur_idx = order[ordered_entries[i].start_time]
            if cur_idx != prev_idx + 1:
                windows += 1
        planned_pairs = len(entries)
        approved_pairs = sum(1 for e in entries if e.status != "pending")
        pending_pairs = planned_pairs - approved_pairs
        groups_report.append({
            "group_name": grp.name,
            "planned_pairs": planned_pairs,
            "approved_pairs": approved_pairs,
            "pending_pairs": pending_pairs,
            "windows": windows,
            "duplicates": duplicates,
            "unknown_teachers": unknown_teacher_count.get(gid, 0),
        })
        if windows > 0:
            issues.append({
                "code": "group_windows",
                "severity": "warning",
                "message": f"Группа {grp.name}: обнаружены окна ({windows})",
                "group_name": grp.name,
            })

    blockers_count = sum(1 for i in issues if i.get("severity") == "blocker")
    warnings_count = sum(1 for i in issues if i.get("severity") == "warning")
    can_approve = blockers_count == 0
    report = {
        "day_id": ds.id,
        "date": ds.date,
        "can_approve": can_approve,
        "blockers_count": blockers_count,
        "warnings_count": warnings_count,
        "groups": groups_report,
        "issues": issues,
    }
    return report


def get_day_schedule(db: Session, date_: date, group_name: str | None = None, reasons: list[str] | None = None) -> schemas.DayPlanResponse:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if not ds:
        raise ValueError("Day schedule not found")
    # Build response
    entries = []
    planned_pairs = 0
    approved_pairs = 0
    planned_hours = 0.0
    approved_hours = 0.0
    for e in ds.entries:
        group = db.query(models.Group).get(e.group_id)
        if group_name and group.name != group_name:
            continue
        subject = db.query(models.Subject).get(e.subject_id)
        room = db.query(models.Room).get(e.room_id)
        teacher_name = None
        if e.teacher_id:
            t = db.query(models.Teacher).get(e.teacher_id)
            teacher_name = t.name if t else None
        entries.append(
            schemas.DayPlanEntry(
                id=e.id,
                group_name=group.name,
                subject_name=subject.name,
                teacher_name=teacher_name,
                room_name=room.name,
                start_time=e.start_time,
                end_time=e.end_time,
                status=e.status,
            )
        )
        planned_pairs += 1
        planned_hours += PAIR_SIZE_AH
        if e.status != "pending":
            approved_pairs += 1
            approved_hours += PAIR_SIZE_AH
    # Compute diffs vs weekly plan
    plan_entries, diffs, counters = compute_day_plan_diff(db, ds.date, group_name)
    group_summary, subject_summary = compute_day_summaries(db, ds.date, group_name)
    return schemas.DayPlanResponse(
        id=ds.id,
        date=ds.date,
        status=ds.status,
        entries=entries,
        planned_pairs=planned_pairs,
        approved_pairs=approved_pairs,
        planned_hours=planned_hours,
        approved_hours=approved_hours,
        reasons=(reasons if reasons is not None else None),
        plan_entries=plan_entries,
        differences=diffs,
        diff_counters=counters,
        group_hours_summary=group_summary,
        subject_hours_summary=subject_summary,
    )


def get_last_plan_debug(day_id: int, clear: bool = True) -> list[str]:
    notes = _last_plan_debug.get(day_id, [])
    if clear and day_id in _last_plan_debug:
        del _last_plan_debug[day_id]
    return notes


def _collect_day_actual_min(db: Session, date_: date, group_id_filter: int | None = None) -> dict[tuple[int, str], dict]:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    res: dict[tuple[int, str], dict] = {}
    if not ds:
        return res
    for e in ds.entries:
        if group_id_filter and e.group_id != group_id_filter:
            continue
        g = db.query(models.Group).get(e.group_id)
        s = db.query(models.Subject).get(e.subject_id)
        r = db.query(models.Room).get(e.room_id)
        t = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
        res[(e.group_id, e.start_time)] = {
            "group_name": g.name if g else str(e.group_id),
            "start_time": e.start_time,
            "end_time": e.end_time,
            "subject_name": s.name if s else str(e.subject_id),
            "teacher_name": t.name if t else None,
            "room_name": r.name if r else str(e.room_id),
            "status": e.status,
        }
    return res


def _collect_day_weekly_plan_min(db: Session, date_: date, group_id_filter: int | None = None) -> dict[tuple[int, str], dict]:
    week_start = _get_week_start(date_)
    dow = days[date_.weekday()]
    res: dict[tuple[int, str], dict] = {}
    dists = db.query(models.WeeklyDistribution).filter(models.WeeklyDistribution.week_start == week_start).all()
    for d in dists:
        it = d.schedule_item
        if group_id_filter and it.group_id != group_id_filter:
            continue
        for slot in d.daily_schedule or []:
            if slot.get("day") != dow:
                continue
            res[(it.group_id, slot["start_time"])] = {
                "group_name": it.group.name,
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "subject_name": it.subject.name,
                "teacher_name": it.teacher.name,
                "room_name": it.room.name,
            }
    return res


def compute_day_plan_diff(db: Session, date_: date, group_name: str | None = None) -> tuple[list[schemas.DayPlanEntry], list[dict], dict]:
    group_id: int | None = None
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if g:
            group_id = g.id
    actual = _collect_day_actual_min(db, date_, group_id)
    plan = _collect_day_weekly_plan_min(db, date_, group_id)
    # Build plan entries for response
    plan_entries: list[schemas.DayPlanEntry] = []
    for v in sorted(plan.values(), key=lambda x: (x["group_name"], x["start_time"])):
        plan_entries.append(
            schemas.DayPlanEntry(
                id=0,
                group_name=v["group_name"],
                subject_name=v["subject_name"],
                teacher_name=v["teacher_name"],
                room_name=v["room_name"],
                start_time=v["start_time"],
                end_time=v["end_time"],
                status="planned",
            )
        )
    # Differences
    keys = set(actual.keys()) | set(plan.keys())
    diff_rows: list[dict] = []
    counters: dict[str, int] = {"added": 0, "removed": 0, "changed": 0, "same": 0}
    for k in sorted(keys, key=lambda x: (x[0], x[1])):
        a = actual.get(k)
        p = plan.get(k)
        group_name_v = a["group_name"] if a else (p["group_name"] if p else "")
        start_time = a["start_time"] if a else (p["start_time"] if p else "")
        if a and not p:
            dtype = "added"
        elif p and not a:
            dtype = "removed"
        else:
            changed = any([
                a.get("subject_name") != p.get("subject_name"),
                a.get("teacher_name") != p.get("teacher_name"),
                a.get("room_name") != p.get("room_name"),
            ])
            dtype = "changed" if changed else "same"
        counters[dtype] = counters.get(dtype, 0) + 1
        diff_rows.append(
            {
                "group_name": group_name_v,
                "start_time": start_time,
                "type": dtype,
                "plan_subject": (p.get("subject_name") if p else None),
                "plan_teacher": (p.get("teacher_name") if p else None),
                "plan_room": (p.get("room_name") if p else None),
                "actual_subject": (a.get("subject_name") if a else None),
                "actual_teacher": (a.get("teacher_name") if a else None),
                "actual_room": (a.get("room_name") if a else None),
            }
        )
    return plan_entries, diff_rows, counters


def compute_day_summaries(db: Session, date_: date, group_name: str | None = None) -> tuple[list[dict], list[dict]]:
    """Compute per-group and per-subject plan vs actual summaries for the date.
    Returns (group_summary, subject_summary).
    """
    # Build minimal maps
    group_id: int | None = None
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if g:
            group_id = g.id
    actual = _collect_day_actual_min(db, date_, group_id)
    plan = _collect_day_weekly_plan_min(db, date_, group_id)
    # Per-group aggregation
    groups = sorted({v["group_name"] for v in (list(actual.values()) + list(plan.values()))})
    group_rows: list[dict] = []
    for gname in groups:
        ap = sum(1 for (_gid, st), v in actual.items() if v["group_name"] == gname)
        pp = sum(1 for (_gid, st), v in plan.items() if v["group_name"] == gname)
        group_rows.append({
            "group_name": gname,
            "actual_pairs": ap,
            "plan_pairs": pp,
            "delta_pairs": ap - pp,
            "actual_hours_AH": ap * PAIR_SIZE_AH,
            "plan_hours_AH": pp * PAIR_SIZE_AH,
            "delta_hours_AH": (ap - pp) * PAIR_SIZE_AH,
        })
    # Per-subject aggregation per group
    subject_key = []
    for v in actual.values():
        subject_key.append((v["group_name"], v["subject_name"]))
    for v in plan.values():
        subject_key.append((v["group_name"], v["subject_name"]))
    subject_pairs = sorted(set(subject_key))
    subject_rows: list[dict] = []
    for gname, sname in subject_pairs:
        ap = sum(1 for (_gid, st), v in actual.items() if v["group_name"] == gname and v["subject_name"] == sname)
        pp = sum(1 for (_gid, st), v in plan.items() if v["group_name"] == gname and v["subject_name"] == sname)
        subject_rows.append({
            "group_name": gname,
            "subject_name": sname,
            "actual_pairs": ap,
            "plan_pairs": pp,
            "delta_pairs": ap - pp,
            "actual_hours_AH": ap * PAIR_SIZE_AH,
            "plan_hours_AH": pp * PAIR_SIZE_AH,
            "delta_hours_AH": (ap - pp) * PAIR_SIZE_AH,
        })
    # Sort for stable output
    group_rows.sort(key=lambda r: r["group_name"])
    subject_rows.sort(key=lambda r: (r["group_name"], r["subject_name"]))
    return group_rows, subject_rows


def approve_day_schedule(db: Session, day_schedule_id: int, group_name: str | None = None, record_progress: bool = True) -> Dict:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.id == day_schedule_id).first()
    if not ds:
        raise ValueError("Day schedule not found")
    approved = 0
    created_progress = 0
    # Determine set of groups to approve
    target_group_ids: set[int] | None = None
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if not g:
            raise ValueError("Group not found")
        target_group_ids = {g.id}
    for e in ds.entries:
        if target_group_ids and e.group_id not in target_group_ids:
            continue
        if e.status != "approved":
            e.status = "approved"
            db.add(e)
            approved += 1
        # Record progress once per entry if requested
        if record_progress and e.schedule_item_id:
            note = f"day_entry:{e.id}"
            exists = (
                db.query(models.SubjectProgress)
                .filter(models.SubjectProgress.schedule_item_id == e.schedule_item_id)
                .filter(models.SubjectProgress.note == note)
                .first()
            )
            if not exists:
                p = models.SubjectProgress(
                    schedule_item_id=e.schedule_item_id,
                    date=ds.date,
                    hours=PAIR_SIZE_AH,
                    note=note,
                )
                db.add(p)
                created_progress += 1
    # Update overall day status only if all entries approved
    if all(e.status == "approved" for e in ds.entries):
        ds.status = "approved"
    db.add(ds)
    db.commit()
    remaining_pending = sum(1 for e in ds.entries if e.status == "pending")
    # Attach fresh diff after approval
    plan_entries, diffs, counters = compute_day_plan_diff(db, ds.date, group_name)
    return {
        "status": ds.status,
        "approved_entries": approved,
        "created_progress_entries": created_progress,
        "remaining_pending": remaining_pending,
        "plan_entries": [pe.model_dump() for pe in plan_entries],
        "differences": diffs,
        "diff_counters": counters,
    }


# ---- Progress entries ----
def add_progress_entry(db: Session, entry: schemas.ProgressEntryCreate):
    item = db.query(models.ScheduleItem).filter(models.ScheduleItem.id == entry.schedule_item_id).first()
    if not item:
        raise ValueError("Schedule item not found")
    date_ = entry.date or date.today()
    p = models.SubjectProgress(schedule_item_id=item.id, date=date_, hours=entry.hours, note=entry.note)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def list_progress_entries(db: Session, schedule_item_id: int):
    item = db.query(models.ScheduleItem).filter(models.ScheduleItem.id == schedule_item_id).first()
    if not item:
        raise ValueError("Schedule item not found")
    return db.query(models.SubjectProgress).filter(models.SubjectProgress.schedule_item_id == schedule_item_id).order_by(models.SubjectProgress.date.asc()).all()


# ---- Progress summary (by group/subject) ----
def progress_summary(db: Session, group_name: str | None = None, subject_name: str | None = None) -> List[schemas.ProgressSummaryItem]:
    q = db.query(models.ScheduleItem)
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if not g:
            return []
        q = q.filter(models.ScheduleItem.group_id == g.id)
    if subject_name:
        s = db.query(models.Subject).filter(models.Subject.name == subject_name).first()
        if not s:
            return []
        q = q.filter(models.ScheduleItem.subject_id == s.id)
    items = q.all()
    result: List[schemas.ProgressSummaryItem] = []
    for it in items:
        ext = calculate_hours_extended(db, it.id)
        result.append(
            schemas.ProgressSummaryItem(
                group_name=db.query(models.Group).get(it.group_id).name,
                subject_name=db.query(models.Subject).get(it.subject_id).name,
                assigned_hours=ext.assigned_hours,
                manual_completed_hours=ext.manual_completed_hours,
                effective_completed_hours=ext.effective_completed_hours,
                total_hours=ext.total_hours,
                remaining_hours=ext.remaining_hours,
            )
        )
    # Order by group then subject for readability
    result.sort(key=lambda r: (r.group_name, r.subject_name))
    return result


# ---- Generic schedule query (date / range, filters) ----
def query_schedule(
    db: Session,
    *,
    date_: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    group_name: str | None = None,
    teacher_name: str | None = None,
) -> List[schemas.ScheduleQueryEntry]:
    # Determine target range
    if date_ and (start_date or end_date):
        raise ValueError("Provide either 'date' or 'start_date'/'end_date', not both")
    if date_:
        range_start, range_end = date_, date_
    else:
        if start_date and end_date:
            range_start, range_end = start_date, end_date
        elif start_date and not end_date:
            range_start, range_end = start_date, start_date
        elif end_date and not start_date:
            range_start, range_end = end_date, end_date
        else:
            # No dates provided: use full range from existing distributions
            dists_all = db.query(models.WeeklyDistribution).all()
            if not dists_all:
                return []
            range_start = min(d.week_start for d in dists_all)
            range_end = max(d.week_end for d in dists_all)

    # Resolve optional filters
    group_id = None
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if not g:
            return []
        group_id = g.id
    teacher_id = None
    if teacher_name:
        t = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
        if not t:
            return []
        teacher_id = t.id

    # Base distributions intersecting range + filters
    q = (
        db.query(models.WeeklyDistribution)
        .join(models.ScheduleItem)
        .filter(models.WeeklyDistribution.week_start <= range_end)
        .filter(models.WeeklyDistribution.week_end >= range_start)
    )
    if group_id is not None:
        q = q.filter(models.ScheduleItem.group_id == group_id)
    if teacher_id is not None:
        q = q.filter(models.ScheduleItem.teacher_id == teacher_id)
    dists = q.all()

    # Collect holidays across the queried range
    holiday_dates: Set[date] = set()
    db_holidays = db.query(models.Holiday).filter(
        models.Holiday.start_date <= range_end,
        models.Holiday.end_date >= range_start,
    ).all()
    for holiday in db_holidays:
        current = holiday.start_date
        while current <= holiday.end_date:
            holiday_dates.add(current)
            current += timedelta(days=1)

    # DaySchedule overrides: prefer approved entries and non-pending manual replacements
    overrides_index: set[tuple[date, int, str]] = set()  # (date, group_id, start_time)
    items: List[schemas.ScheduleQueryEntry] = []

    day_plans = (
        db.query(models.DaySchedule)
        .filter(models.DaySchedule.date >= range_start)
        .filter(models.DaySchedule.date <= range_end)
        .all()
    )
    for ds in day_plans:
        for e in ds.entries:
            if not (ds.status == "approved" or e.status != "pending"):
                continue
            g = db.query(models.Group).get(e.group_id)
            if group_name and (not g or g.name != group_name):
                continue
            t = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
            if teacher_name and ((not t) or t.name != teacher_name):
                continue
            s = db.query(models.Subject).get(e.subject_id)
            r = db.query(models.Room).get(e.room_id) if e.room_id else None
            day_str = days[ds.date.weekday()] if 0 <= ds.date.weekday() < len(days) else str(ds.date.weekday())
            overrides_index.add((ds.date, e.group_id, e.start_time))
            # Convert placeholder room to empty string for UI
            room_name_out = ""
            if r and not _is_placeholder_room_name(r.name):
                room_name_out = r.name
            items.append(
                schemas.ScheduleQueryEntry(
                    date=ds.date,
                    day=day_str,
                    start_time=e.start_time,
                    end_time=e.end_time,
                    subject_name=s.name if s else str(e.subject_id),
                    teacher_name=(t.name if t else ""),
                    room_name=room_name_out,
                    group_name=g.name if g else str(e.group_id),
                    origin="day_plan",
                    approval_status=e.status,
                    is_override=True,
                    day_id=ds.id,
                    entry_id=e.id,
                )
            )

    # If no weekly data but day overrides exist, return them
    if not dists and items:
        items.sort(key=lambda x: (x.date, x.start_time, x.group_name))
        return items

    for d in dists:
        item = d.schedule_item
        # Get or synthesize daily schedule for this week
        weekly_hours = d.hours_even if d.is_even_week else d.hours_odd
        daily = d.daily_schedule or []
        if (not daily) and weekly_hours:
            # Fallback to assign within the week
            daily = _assign_daily_schedule(
                weekly_hours,
                d.week_start,
                d.week_end,
                bool(d.is_even_week),
                item,
                holiday_dates,
                defaultdict(int),
                set(),
                set(),
                defaultdict(set),
                pair_size_ah=PAIR_SIZE_AH,
            )
        if not daily:
            continue
        for slot in daily:
            try:
                day_idx = days.index(slot["day"])
            except ValueError:
                continue
            slot_date = d.week_start + timedelta(days=day_idx)
            if slot_date < range_start or slot_date > range_end:
                continue
            if _is_holiday(slot_date, [], holiday_dates):
                continue
            # Skip if overridden by an approved day plan/manual replacement
            if (slot_date, item.group_id, slot["start_time"]) in overrides_index:
                continue
            items.append(
                schemas.ScheduleQueryEntry(
                    date=slot_date,
                    day=slot["day"],
                    start_time=slot["start_time"],
                    end_time=slot["end_time"],
                    subject_name=item.subject.name,
                    teacher_name=item.teacher.name,
                    room_name=item.room.name,
                    group_name=item.group.name,
                    origin="weekly",
                    approval_status="planned",
                    is_override=False,
                    day_id=None,
                    entry_id=None,
                )
            )

    items.sort(key=lambda x: (x.date, x.start_time, x.group_name))
    return items


# ---- Entry lookup and strict bulk update ----
def lookup_day_entries(
    db: Session,
    *,
    date_: date | None = None,
    day_id: int | None = None,
    group_name: str | None = None,
    start_time: str | None = None,
    subject_name: str | None = None,
    room_name: str | None = None,
    teacher_name: str | None = None,
) -> list[schemas.EntryLookupItem]:
    if not date_ and not day_id:
        raise ValueError("Provide either date or day_id")
    if day_id:
        ds = db.query(models.DaySchedule).filter(models.DaySchedule.id == day_id).first()
    else:
        ds = db.query(models.DaySchedule).filter(models.DaySchedule.date == date_).first()
    if not ds:
        raise ValueError("Day schedule not found")
    result: list[schemas.EntryLookupItem] = []
    for e in ds.entries:
        g = db.query(models.Group).get(e.group_id)
        s = db.query(models.Subject).get(e.subject_id)
        r = db.query(models.Room).get(e.room_id)
        t = db.query(models.Teacher).get(e.teacher_id) if e.teacher_id else None
        if group_name and (not g or g.name != group_name):
            continue
        if start_time and e.start_time != start_time:
            continue
        if subject_name and (not s or s.name != subject_name):
            continue
        if room_name and (not r or r.name != room_name):
            continue
        if teacher_name and ((not t) or t.name != teacher_name):
            continue
        result.append(
            schemas.EntryLookupItem(
                day_id=ds.id,
                date=ds.date,
                entry_id=e.id,
                group_name=g.name if g else str(e.group_id),
                subject_name=s.name if s else str(e.subject_id),
                teacher_name=(t.name if t else None),
                room_name=r.name if r else str(e.room_id),
                start_time=e.start_time,
                end_time=e.end_time,
                status=e.status,
            )
        )
    return result


def bulk_update_day_entries_strict(
    db: Session,
    day_id: int,
    items: list[schemas.BulkUpdateEntryStrict],
    *,
    dry_run: bool = False,
) -> dict:
    ds = db.query(models.DaySchedule).filter(models.DaySchedule.id == day_id).first()
    if not ds:
        raise ValueError("Day schedule not found")
    updated = 0
    skipped = 0
    errors = 0
    results: list[dict] = []
    for it in items:
        # Find target entry(s)
        candidates: list[models.DayScheduleEntry] = []
        error: str | None = None
        if it.entry_id is not None:
            e = db.query(models.DayScheduleEntry).filter(models.DayScheduleEntry.id == it.entry_id, models.DayScheduleEntry.day_schedule_id == ds.id).first()
            if e:
                candidates = [e]
            else:
                error = "Entry not found for this day"
        else:
            # Match by group_name + start_time [+ subject]
            if not it.group_name or not it.start_time:
                error = "Provide entry_id or (group_name and start_time)"
            else:
                g = db.query(models.Group).filter(models.Group.name == it.group_name).first()
                if not g:
                    error = "Group not found"
                else:
                    q = db.query(models.DayScheduleEntry).filter(
                        models.DayScheduleEntry.day_schedule_id == ds.id,
                        models.DayScheduleEntry.group_id == g.id,
                        models.DayScheduleEntry.start_time == it.start_time,
                    )
                    if it.subject_name:
                        subj = db.query(models.Subject).filter(models.Subject.name == it.subject_name).first()
                        if subj:
                            q = q.filter(models.DayScheduleEntry.subject_id == subj.id)
                        else:
                            error = "Subject not found (for matching)"
                    if not error:
                        candidates = q.all()
        # Resolve candidates
        if error:
            errors += 1
            results.append({
                "entry_id": it.entry_id,
                "matched_count": 0,
                "status": "error",
                "error": error,
            })
            continue
        if len(candidates) == 0:
            errors += 1
            results.append({
                "entry_id": it.entry_id,
                "matched_count": 0,
                "status": "error",
                "error": "No entries matched criteria",
            })
            continue
        if len(candidates) > 1:
            errors += 1
            results.append({
                "entry_id": it.entry_id,
                "matched_count": len(candidates),
                "status": "error",
                "error": "Matched multiple entries; specify subject_name or use entry_id",
            })
            continue
        e = candidates[0]
        # Prepare strict updates
        old = {
            "teacher_name": (db.query(models.Teacher).get(e.teacher_id).name if e.teacher_id else None),
            "subject_name": (db.query(models.Subject).get(e.subject_id).name if e.subject_id else None),
            "room_name": (db.query(models.Room).get(e.room_id).name if e.room_id else None),
        }
        new_teacher_id = e.teacher_id
        new_subject_id = e.subject_id
        new_room_id = e.room_id
        # teacher
        if it.update_teacher_name is not None:
            t = db.query(models.Teacher).filter(models.Teacher.name == it.update_teacher_name).first()
            if not t:
                errors += 1
                results.append({
                    "entry_id": e.id,
                    "matched_count": 1,
                    "status": "error",
                    "error": "Teacher not found",
                })
                continue
            if not _teacher_is_free(db, t.id, ds.date, e.start_time, e.end_time, exclude_entry_id=e.id):
                errors += 1
                results.append({
                    "entry_id": e.id,
                    "matched_count": 1,
                    "status": "error",
                    "error": "Teacher is not available at this time",
                })
                continue
            new_teacher_id = t.id
        # subject
        if it.update_subject_name is not None:
            s = db.query(models.Subject).filter(models.Subject.name == it.update_subject_name).first()
            if not s:
                errors += 1
                results.append({
                    "entry_id": e.id,
                    "matched_count": 1,
                    "status": "error",
                    "error": "Subject not found",
                })
                continue
            new_subject_id = s.id
        # room
        if it.update_room_name is not None:
            r = db.query(models.Room).filter(models.Room.name == it.update_room_name).first()
            if not r:
                errors += 1
                results.append({
                    "entry_id": e.id,
                    "matched_count": 1,
                    "status": "error",
                    "error": "Room not found",
                })
                continue
            if not _room_has_capacity(db, ds.date, e.start_time, r.id, exclude_entry_id=e.id):
                errors += 1
                results.append({
                    "entry_id": e.id,
                    "matched_count": 1,
                    "status": "error",
                    "error": "Room is not available at this time",
                })
                continue
            new_room_id = r.id

        if dry_run:
            skipped += 1
            new = {
                "teacher_name": (db.query(models.Teacher).get(new_teacher_id).name if new_teacher_id else None),
                "subject_name": (db.query(models.Subject).get(new_subject_id).name if new_subject_id else None),
                "room_name": (db.query(models.Room).get(new_room_id).name if new_room_id else None),
            }
            results.append({
                "entry_id": e.id,
                "matched_count": 1,
                "status": "skipped",
                "old": old,
                "new": new,
            })
            continue

        # Apply
        e.teacher_id = new_teacher_id
        e.subject_id = new_subject_id
        e.room_id = new_room_id
        e.status = "replaced_manual"
        db.add(e)
        updated += 1
        new = {
            "teacher_name": (db.query(models.Teacher).get(e.teacher_id).name if e.teacher_id else None),
            "subject_name": (db.query(models.Subject).get(e.subject_id).name if e.subject_id else None),
            "room_name": (db.query(models.Room).get(e.room_id).name if e.room_id else None),
        }
        results.append({
            "entry_id": e.id,
            "matched_count": 1,
            "status": "updated",
            "old": old,
            "new": new,
        })

    db.commit()
    # Attach day report
    report = analyze_day_schedule(db, ds.id)
    return {"updated": updated, "skipped": skipped, "errors": errors, "results": results, "report": report}


# ---- Progress timeseries ----
def progress_timeseries(
    db: Session,
    *,
    group_name: str | None = None,
    subject_name: str | None = None,
    teacher_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    # Resolve filters to schedule_item ids
    q_items = db.query(models.ScheduleItem)
    if group_name:
        g = db.query(models.Group).filter(models.Group.name == group_name).first()
        if not g:
            return []
        q_items = q_items.filter(models.ScheduleItem.group_id == g.id)
    if subject_name:
        s = db.query(models.Subject).filter(models.Subject.name == subject_name).first()
        if not s:
            return []
        q_items = q_items.filter(models.ScheduleItem.subject_id == s.id)
    if teacher_name:
        t = db.query(models.Teacher).filter(models.Teacher.name == teacher_name).first()
        if not t:
            return []
        q_items = q_items.filter(models.ScheduleItem.teacher_id == t.id)
    items = q_items.all()
    if not items:
        return []
    item_ids = [it.id for it in items]
    # Collect SubjectProgress entries in range
    q = db.query(models.SubjectProgress).filter(models.SubjectProgress.schedule_item_id.in_(item_ids))
    if start_date:
        q = q.filter(models.SubjectProgress.date >= start_date)
    if end_date:
        q = q.filter(models.SubjectProgress.date <= end_date)
    entries = q.all()
    # Group by date
    by_date: dict[date, float] = defaultdict(float)
    for e in entries:
        by_date[e.date] += float(e.hours or 0.0)
    # Build ordered points with cumulative sum
    points = []
    total = 0.0
    for d in sorted(by_date.keys()):
        daily = by_date[d]
        total += daily
        points.append(schemas.ProgressTimeseriesPoint(date=d, hours=daily, cumulative_hours=total))
    return points

# ---- Day planning: delegate to service layer (override legacy defs) ----
from app.services import day_planning_service as _day


def plan_day_schedule(db: Session, request: schemas.DayPlanCreateRequest) -> models.DaySchedule:  # type: ignore[override]
    return _day.plan_day_schedule(db, request)


def analyze_day_schedule(db: Session, day_schedule_id: int, group_name: str | None = None) -> Dict:  # type: ignore[override]
    return _day.analyze_day_schedule(db, day_schedule_id, group_name)


def get_day_schedule(db: Session, date_: date, group_name: str | None = None, reasons: list[str] | None = None) -> schemas.DayPlanResponse:  # type: ignore[override]
    return _day.get_day_schedule(db, date_, group_name, reasons)


def get_entry_replacement_options(
    db: Session,
    entry_id: int,
    *,
    limit_teachers: int | None = 20,
    limit_rooms: int | None = 20,
) -> Dict:  # type: ignore[override]
    return _day.get_entry_replacement_options(db, entry_id, limit_teachers=limit_teachers or 20, limit_rooms=limit_rooms or 20)


def propose_room_swap(
    db: Session,
    entry_id: int,
    desired_room_name: str,
    *,
    limit_alternatives: int | None = 5,
):  # type: ignore[override]
    return _day.propose_room_swap(db, entry_id, desired_room_name, limit_alternatives=limit_alternatives or 5)


def execute_room_swap(
    db: Session,
    entry_id: int,
    desired_room_name: str,
    *,
    choices: list[schemas.RoomSwapChoice] | None = None,
    dry_run: bool = False,
) -> Dict:  # type: ignore[override]
    return _day.execute_room_swap(db, entry_id, desired_room_name, choices=choices or [], dry_run=dry_run)


def replace_vacant_auto(db: Session, day_schedule_id: int) -> Dict:  # type: ignore[override]
    return _day.replace_vacant_auto(db, day_schedule_id)


def replace_entry_manual(db: Session, entry_id: int, teacher_name: str) -> Dict:  # type: ignore[override]
    return _day.replace_entry_manual(db, entry_id, teacher_name)


def update_entry_manual(
    db: Session,
    entry_id: int,
    *,
    teacher_name: str | None = None,
    subject_name: str | None = None,
    room_name: str | None = None,
) -> Dict:  # type: ignore[override]
    return _day.update_entry_manual(db, entry_id, teacher_name=teacher_name, subject_name=subject_name, room_name=room_name)


def lookup_day_entries(
    db: Session,
    *,
    date_: date | None = None,
    day_id: int | None = None,
    group_name: str | None = None,
    start_time: str | None = None,
    subject_name: str | None = None,
    room_name: str | None = None,
    teacher_name: str | None = None,
) -> list[schemas.EntryLookupItem]:  # type: ignore[override]
    return _day.lookup_day_entries(
        db,
        date_=date_,
        day_id=day_id,
        group_name=group_name,
        start_time=start_time,
        subject_name=subject_name,
        room_name=room_name,
        teacher_name=teacher_name,
    )


def bulk_update_day_entries_strict(
    db: Session,
    day_id: int,
    items: list[schemas.BulkUpdateEntryStrict],
    *,
    dry_run: bool = False,
) -> dict:  # type: ignore[override]
    return _day.bulk_update_day_entries_strict(db, day_id, items, dry_run=dry_run)


# ---- Analytics helpers ----
def _analytics_collect_entries(
    db: Session,
    start_date: date,
    end_date: date,
    filters: schemas.AnalyticsFilter,
) -> list[schemas.ScheduleQueryEntry]:
    items = query_schedule(db, start_date=start_date, end_date=end_date)
    # Apply name-based filters
    def _in_or_all(val: str, allowed: list[str] | None):
        return True if not allowed else (val in allowed)
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


def analytics_teacher_summary(db: Session, req: schemas.AnalyticsFilter) -> list[schemas.TeacherSummaryItem]:
    items = _analytics_collect_entries(db, req.start_date, req.end_date, req)
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
    # Manual progress (SubjectProgress) aggregated per (teacher, group, subject)
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

    result: list[schemas.TeacherSummaryItem] = []
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


def analytics_group_summary(db: Session, req: schemas.AnalyticsFilter) -> list[schemas.GroupSubjectSummaryItem]:
    items = _analytics_collect_entries(db, req.start_date, req.end_date, req)
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
    # Manual progress aggregated per (group, subject)
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

    result: list[schemas.GroupSubjectSummaryItem] = []
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


def analytics_room_summary(db: Session, req: schemas.AnalyticsFilter) -> list[schemas.RoomSummaryItem]:
    items = _analytics_collect_entries(db, req.start_date, req.end_date, req)
    bucket: dict[str, dict] = defaultdict(lambda: {"planned": 0, "actual": 0})
    for it in items:
        bucket[it.room_name]["planned"] += 1
        if it.origin == "day_plan":
            bucket[it.room_name]["actual"] += 1
    result: list[schemas.RoomSummaryItem] = []
    for rname, vals in bucket.items():
        planned_pairs = vals["planned"]
        actual_pairs = vals["actual"]
        result.append(
            schemas.RoomSummaryItem(
                room_name=rname,
                planned_pairs=planned_pairs,
                actual_pairs=actual_pairs,
                planned_hours_AH=planned_pairs * PAIR_SIZE_AH,
                actual_hours_AH=actual_pairs * PAIR_SIZE_AH,
            )
        )
    result.sort(key=lambda r: (r.actual_pairs, r.planned_pairs), reverse=True)
    return result


def analytics_heatmap(db: Session, dimension: str, name: str, req: schemas.AnalyticsFilter) -> schemas.HeatmapResponse:
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
    items = _analytics_collect_entries(db, req.start_date, req.end_date, filters)
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


def analytics_distribution(db: Session, dimension: str, req: schemas.AnalyticsFilter) -> list[schemas.DistributionItem]:
    items = _analytics_collect_entries(db, req.start_date, req.end_date, req)
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
    result: list[schemas.DistributionItem] = []
    for name, vals in bucket.items():
        pp = vals["planned"]
        ap = vals["actual"]
        result.append(
            schemas.DistributionItem(
                name=name,
                planned_pairs=pp,
                actual_pairs=ap,
                planned_hours_AH=pp * PAIR_SIZE_AH,
                actual_hours_AH=ap * PAIR_SIZE_AH,
            )
        )
    result.sort(key=lambda r: (r.actual_pairs, r.planned_pairs), reverse=True)
    return result


def analytics_schedule_timeseries(db: Session, req: schemas.AnalyticsFilter) -> list[schemas.ScheduleTimeseriesPoint]:
    items = _analytics_collect_entries(db, req.start_date, req.end_date, req)
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
    points: list[schemas.ScheduleTimeseriesPoint] = []
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


# ---- Practice periods CRUD ----
def create_practice(db: Session, practice: schemas.PracticeCreate) -> models.Practice:
    """Create a practice period for a group."""
    logger.info("Creating practice for group=%s from %s to %s", practice.group_name, practice.start_date, practice.end_date)

    # Validate dates
    if practice.end_date < practice.start_date:
        raise ValueError("end_date must be >= start_date")

    # Find group
    group = db.query(models.Group).filter(models.Group.name == practice.group_name).first()
    if not group:
        raise ValueError(f"Group not found: {practice.group_name}")

    # Check for overlapping practices
    overlapping = db.query(models.Practice).filter(
        models.Practice.group_id == group.id,
        models.Practice.start_date <= practice.end_date,
        models.Practice.end_date >= practice.start_date
    ).first()

    if overlapping:
        raise ValueError(f"Practice period overlaps with existing practice from {overlapping.start_date} to {overlapping.end_date}")

    # Create practice
    db_practice = models.Practice(
        group_id=group.id,
        start_date=practice.start_date,
        end_date=practice.end_date,
        name=practice.name
    )
    db.add(db_practice)
    db.commit()
    db.refresh(db_practice)
    logger.info("Created practice id=%s for group=%s", db_practice.id, practice.group_name)
    return db_practice


def get_practices(db: Session, group_name: Optional[str] = None, active_on: Optional[date] = None) -> List[models.Practice]:
    """Get practice periods, optionally filtered by group or active date."""
    query = db.query(models.Practice)

    if group_name:
        group = db.query(models.Group).filter(models.Group.name == group_name).first()
        if group:
            query = query.filter(models.Practice.group_id == group.id)
        else:
            return []

    if active_on:
        query = query.filter(
            models.Practice.start_date <= active_on,
            models.Practice.end_date >= active_on
        )

    return query.all()


def delete_practice(db: Session, practice_id: int) -> bool:
    """Delete a practice period."""
    practice = db.query(models.Practice).filter(models.Practice.id == practice_id).first()
    if not practice:
        raise ValueError("Practice not found")

    logger.info("Deleting practice id=%s", practice_id)
    db.delete(practice)
    db.commit()
    return True


def is_group_on_practice(db: Session, group_id: int, date_: date) -> bool:
    """Check if a group is on practice on a specific date."""
    practice = db.query(models.Practice).filter(
        models.Practice.group_id == group_id,
        models.Practice.start_date <= date_,
        models.Practice.end_date >= date_
    ).first()
    return practice is not None
