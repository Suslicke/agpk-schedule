from typing import List, Set, Dict
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

pair_duration = 1.5
time_slots = [
    {"start": "08:00", "end": "09:30"},
    {"start": "09:40", "end": "11:10"},
    {"start": "11:20", "end": "12:50"},
    {"start": "13:00", "end": "14:30"}
]
days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def get_or_create_group(db: Session, name: str):
    group = db.query(models.Group).filter(models.Group.name == name).first()
    if not group:
        group = models.Group(name=name)
        db.add(group)
        db.commit()
        db.refresh(group)
    return group


def get_or_create_subject(db: Session, name: str):
    subject = db.query(models.Subject).filter(models.Subject.name == name).first()
    if not subject:
        subject = models.Subject(name=name)
        db.add(subject)
        db.commit()
        db.refresh(subject)
    return subject


def get_or_create_teacher(db: Session, name: str):
    teacher = db.query(models.Teacher).filter(models.Teacher.name == name).first()
    if not teacher:
        teacher = models.Teacher(name=name)
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
    return teacher


def get_or_create_room(db: Session, name: str):
    room = db.query(models.Room).filter(models.Room.name == name).first()
    if not room:
        room = models.Room(name=name)
        db.add(room)
        db.commit()
        db.refresh(room)
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
    return schedule_item


def parse_and_create_schedule_items(db: Session, df: pd.DataFrame):
    schedule_items = []
    current_group = None
    for _, row in df.iterrows():
        if pd.isna(row.iloc[0]) and pd.isna(row.iloc[1]):
            continue
        if not pd.isna(row.iloc[1]):
            current_group = row.iloc[1]
        if current_group and not pd.isna(row.iloc[2]):
            subject = row.iloc[2]
            total = float(row.iloc[3]) if not pd.isna(row.iloc[3]) else 0.0
            weekly = float(row.iloc[4]) if not pd.isna(row.iloc[4]) else 0.0
            teacher = row.iloc[5] if not pd.isna(row.iloc[5]) else 'Unknown'
            room = row.iloc[6] if not pd.isna(row.iloc[6]) else 'Unknown'
            week_side = row.iloc[7] if len(row) > 7 and not pd.isna(row.iloc[7]) else None

            week_type = WeekType.balanced
            if week_side == 'правая':
                week_type = WeekType.even_priority
            elif week_side == 'левая':
                week_type = WeekType.odd_priority

            item = schemas.ScheduleItemCreate(
                group_name=current_group,
                subject_name=subject,
                teacher_name=teacher,
                room_name=room,
                total_hours=total,
                weekly_hours=weekly,
                week_type=week_type,
            )
            created = create_schedule_item(db, item)
            schedule_items.append(created)
    return schedule_items


def _is_holiday(current_date: date, holidays: List[schemas.HolidayPeriod], holiday_dates: Set[date]) -> bool:
    if current_date in holiday_dates:
        return True
    for holiday in holidays or []:
        if holiday.start_date <= current_date <= holiday.end_date:
            return True
    return False


def _distribute_hours(weekly_hours: float, week_type: str, is_even: bool) -> float:
    if weekly_hours == 0:
        return 0.0
    half = weekly_hours / 2
    week_type_enum = WeekType(week_type)
    if week_type_enum == WeekType.balanced:
        return weekly_hours
    elif week_type_enum == WeekType.even_priority:
        return max(half, weekly_hours - math.floor(half)) if is_even else math.floor(half)
    elif week_type_enum == WeekType.odd_priority:
        return math.floor(half) if is_even else max(half, weekly_hours - math.floor(half))
    return weekly_hours


def _assign_daily_schedule(
    weekly_hours: float,
    week_start: date,
    week_end: date,
    is_even: bool,
    schedule_item: models.ScheduleItem,
    holiday_dates: Set[date],
    room_occupancy: defaultdict,
    occupied_teacher: Set[tuple],
    occupied_group: Set[tuple],
    gym_teachers: defaultdict
) -> List[dict]:
    if weekly_hours == 0:
        return []
    max_pairs_per_day = 4
    daily_schedule = []
    remaining_hours = weekly_hours
    available_days = []
    for i in range((week_end - week_start).days + 1):
        current_date = week_start + timedelta(days=i)
        if not _is_holiday(current_date, [], holiday_dates):
            day_index = current_date.weekday()
            if day_index < len(days):
                available_days.append((days[day_index], current_date))
    if not available_days:
        return []
    random.shuffle(available_days)
    pairs_needed = math.ceil(remaining_hours / pair_duration)
    pairs_per_day = min(max_pairs_per_day, max(1, math.ceil(pairs_needed / max(1, len(available_days)))))
    group_day_counts = defaultdict(int)
    for day_name, day_date in available_days:
        if remaining_hours <= 0:
            break
        pairs_assigned = 0
        random.shuffle(time_slots)
        for slot in time_slots:
            if pairs_assigned >= pairs_per_day or remaining_hours <= 0:
                break
            teacher_key = (day_date, slot["start"], schedule_item.teacher_id)
            group_key = (day_date, slot["start"], schedule_item.group_id)
            room_key = (day_date, slot["start"], schedule_item.room_id)
            capacity = 4 if "Спортзал" in schedule_item.room.name else 1
            if "Спортзал" in schedule_item.room.name:
                gym_key = (day_date, slot["start"], schedule_item.room_id)
                if schedule_item.teacher_id in gym_teachers[gym_key]:
                    continue
                if room_occupancy[room_key] >= capacity:
                    continue
                gym_teachers[gym_key].add(schedule_item.teacher_id)
            else:
                if room_occupancy[room_key] >= capacity:
                    continue
            if teacher_key in occupied_teacher or group_key in occupied_group:
                continue
            if group_day_counts[(schedule_item.group_id, day_date)] >= max_pairs_per_day:
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
            remaining_hours -= pair_duration
            pairs_assigned += 1
    return daily_schedule


def create_schedules(db: Session, request: schemas.GenerateScheduleRequest):
    if request.group_name:
        groups = [db.query(models.Group).filter(models.Group.name == request.group_name).first()]
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
        return

    remaining_hours = {item.id: item.total_hours for item in all_items}
    room_occupancy = defaultdict(int)
    occupied_teacher = set()
    occupied_group = set()
    gym_teachers = defaultdict(set)

    existing_dists = db.query(models.WeeklyDistribution).filter(
        models.WeeklyDistribution.week_start >= request.start_date - timedelta(days=7),
        models.WeeklyDistribution.week_end <= request.end_date + timedelta(days=7)
    ).all()
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
        week_number = (current_date - date(2025, 9, 1)).days // 7
        is_even = (week_number % 2 == 0)
        week_end = min(current_date + timedelta(days=6 - current_date.weekday()), request.end_date)
        random.shuffle(all_items)
        distributions = []
        for item in all_items:
            if remaining_hours[item.id] <= 0:
                continue
            weekly_hours = min(item.weekly_hours, remaining_hours[item.id])
            hours = _distribute_hours(weekly_hours, item.week_type, is_even)
            daily_schedule = _assign_daily_schedule(
                hours, current_date, week_end, is_even, item, holiday_dates,
                room_occupancy, occupied_teacher, occupied_group, gym_teachers
            )
            if daily_schedule:
                actual_hours = len(daily_schedule) * pair_duration
                remaining_hours[item.id] -= actual_hours
                gen_sched = next(g for g in gen_schedules if g.group_id == item.group_id)
                dist = models.WeeklyDistribution(
                    generated_schedule_id=gen_sched.id,
                    week_start=current_date,
                    week_end=week_end,
                    is_even_week=1 if is_even else 0,
                    schedule_item_id=item.id,
                    hours_even=weekly_hours if is_even else 0,
                    hours_odd=weekly_hours if not is_even else 0,
                    daily_schedule=daily_schedule
                )
                distributions.append(dist)
        for dist in distributions:
            db.add(dist)
        db.commit()
        current_date = week_end + timedelta(days=1)
    for gen_sched in gen_schedules:
        gen_sched.status = "completed"
        db.add(gen_sched)
    db.commit()


def generate_schedule(db: Session, request: schemas.GenerateScheduleRequest):
    gen_schedules = create_schedules(db, request)
    fill_schedules(db, gen_schedules, request)
    if request.group_name and gen_schedules:
        return gen_schedules[0]
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
                    defaultdict(set)
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

