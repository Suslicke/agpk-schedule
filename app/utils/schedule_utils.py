from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
from io import BytesIO
import random
import json
from fastapi import HTTPException
from models.database import SessionLocal
from models.schema import Schedule, GroupLoad
import logging

logger = logging.getLogger(__name__)

def get_nums(h: int, side: Optional[str]) -> tuple[int, int]:
    """Calculate lessons for left/right week."""
    if side is None:
        nl = h // 2
        nr = h // 2
    elif side == "левая":
        nl = (h + 1) // 2
        nr = h // 2
        if nr == 0 and h == 1:
            nl = 1
            nr = 1
    elif side == "правая":
        nl = h // 2
        nr = (h + 1) // 2
        if nl == 0 and h == 1:
            nl = 1
            nr = 1
    else:
        nl = h // 2
        nr = h // 2
    logger.debug(f"Calculated lessons for hours={h}, side={side}: left={nl}, right={nr}")
    return nl, nr

def parse_data_from_string(data_str: str) -> Dict[str, Dict[str, tuple]]:
    """Parse lesson data from string."""
    data = defaultdict(dict)
    lines = [line.strip() for line in data_str.split("\n") if line.strip()]
    logger.info(f"Parsing {len(lines)} lines from data_str")
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            logger.warning(f"Invalid line format: {line}")
            continue
        group, subject, hours_str = parts[:3]
        teacher = parts[3] if len(parts) > 3 else ""
        room = parts[4] if len(parts) > 4 else ""
        side = parts[5] if len(parts) > 5 else None
        try:
            hours = int(float(hours_str))  # Поддержка дробных чисел
            if hours <= 0:
                logger.warning(f"Invalid hours for {group}/{subject}: {hours_str}")
                continue
        except ValueError:
            logger.warning(f"Invalid hours format for {group}/{subject}: {hours_str}")
            continue
        if not group or not subject or "пән" in subject.lower() or "модуль" in subject.lower():
            logger.warning(f"Skipping row with group={group}, subject={subject}: invalid or header")
            continue
        data[group][subject] = (hours, teacher, room, side)
        logger.debug(f"Parsed lesson: group={group}, subject={subject}, hours={hours}, teacher={teacher}, room={room}, side={side}")
    if not data:
        logger.error("No valid lesson data parsed from data_str")
        raise HTTPException(status_code=400, detail="No valid lesson data parsed")
    logger.info(f"Parsed {len(data)} groups from data_str: {list(data.keys())}")
    return dict(data)

def parse_data_from_excel(file_content: bytes) -> Dict[str, Dict[str, tuple]]:
    """Parse lesson data from Excel with flexible error handling."""
    try:
        df = pd.read_excel(BytesIO(file_content), sheet_name="Нагрузка ООД", header=None, skiprows=0)
        data = defaultdict(dict)
        logger.info(f"Parsing Excel with {len(df)} rows")
        for idx, row in df.iterrows():
            if len(row) < 3 or pd.isna(row[1]) or pd.isna(row[2]):
                logger.warning(f"Skipping row {idx}: missing group or subject")
                continue
            group = str(row[1]).strip()
            subject = str(row[2]).strip()
            hours_str = str(row[3]).strip() if len(row) > 3 and not pd.isna(row[3]) else "1"  # Дефолт 1 час
            teacher = str(row[4]).strip() if len(row) > 4 and not pd.isna(row[4]) else ""
            room = str(row[5]).strip() if len(row) > 5 and not pd.isna(row[5]) else ""
            side = str(row[6]).strip() if len(row) > 6 and not pd.isna(row[6]) else None
            if hours_str.lower() in ["nan", "", "0"]:
                hours_str = "1"  # Дефолт 1 час
            try:
                hours = int(float(hours_str))
                if hours <= 0:
                    logger.warning(f"Skipping row {idx} for {group}/{subject}: invalid hours {hours_str}")
                    continue
            except ValueError:
                logger.warning(f"Invalid hours format for {group}/{subject}: {hours_str}")
                continue
            if not group or not subject or "пән" in subject.lower() or "модуль" in subject.lower():
                logger.warning(f"Skipping row {idx}: invalid group={group} or subject={subject} (possible header)")
                continue
            data[group][subject] = (hours, teacher, room, side)
            logger.debug(f"Parsed lesson: group={group}, subject={subject}, hours={hours}, teacher={teacher}, room={room}, side={side}")
        if not data:
            logger.error("No valid lesson data in Excel")
            raise HTTPException(status_code=400, detail="No valid lesson data in Excel")
        logger.info(f"Parsed {len(data)} groups from Excel: {list(data.keys())}")
        return dict(data)
    except Exception as e:
        logger.error(f"Excel parsing error: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Excel parsing error: {str(e)}")

def generate_calendar(start_even_date_str: str, end_year_date_str: str, holidays: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """Generate academic calendar, ignoring weekends, respecting holidays."""
    try:
        start_even_date = datetime.strptime(start_even_date_str, "%d.%m.%Y")
        end_date = datetime.strptime(end_year_date_str, "%d.%m.%Y")
        holiday_ranges = []
        holiday_strings = []
        if holidays:
            for holiday in holidays:
                if isinstance(holiday, dict):
                    start_str = holiday["start"]
                    end_str = holiday["end"]
                else:
                    start_str, end_str = holiday.split("-") if "-" in holiday else (holiday, holiday)
                holiday_start = datetime.strptime(start_str, "%d.%m.%Y")
                holiday_end = datetime.strptime(end_str, "%d.%m.%Y")
                holiday_ranges.append((holiday_start, holiday_end))
                holiday_strings.append(f"{start_str}-{end_str}")
        weeks = []
        current_monday = start_even_date - timedelta(days=start_even_date.weekday())  # Находим ближайший понедельник
        week_type = "правая" if start_even_date.weekday() == 0 else "левая"
        while current_monday <= end_date:
            week_end = min(current_monday + timedelta(days=4), end_date)  # Пятница
            available_days = []
            for day in range(5):  # Только будни
                current_day = current_monday + timedelta(days=day)
                if current_day > end_date:
                    break
                is_holiday = False
                for h_start, h_end in holiday_ranges:
                    if h_start <= current_day <= h_end:
                        is_holiday = True
                        break
                if not is_holiday:
                    available_days.append(day)
            start_str = current_monday.strftime("%d.%m.%Y")
            end_str = week_end.strftime("%d.%m.%Y")
            weeks.append({
                "start": start_str,
                "end": end_str,
                "type": week_type,
                "holidays": holiday_strings,
                "available_days": len(available_days)
            })
            logger.debug(f"Week {start_str}: {len(available_days)} available days, holidays={holiday_strings}")
            current_monday += timedelta(days=7)
            week_type = "левая" if week_type == "правая" else "правая"
        logger.info(f"Generated {len(weeks)} weeks")
        return weeks
    except ValueError as e:
        logger.error(f"Invalid date format: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")

def generate_schedule(
    week_type: str,
    data: Dict[str, Dict[str, tuple]],
    week_start: datetime,
    holidays: Optional[List[tuple[datetime, datetime]]] = None,
    force_available_days: Optional[Dict[str, int]] = None
) -> Dict[str, Any]:
    """Generate schedule with at least 1 lesson per day per group, ignoring weekends."""
    logger.info(f"Generating schedule for {week_type} week starting {week_start.strftime('%d.%m.%Y')}, data: {data}")
    available_days = list(range(5))  # Понедельник–Пятница
    week_start_str = week_start.strftime("%d.%m.%Y")
    if force_available_days and week_start_str in force_available_days:
        num_days = force_available_days[week_start_str]
        available_days = list(range(min(num_days, 5)))
        logger.debug(f"Forced {num_days} available days for week {week_start_str}: {available_days}")
    else:
        for day in range(5):
            current_day = week_start + timedelta(days=day)
            is_holiday = False
            if holidays:
                for h_start, h_end in holidays:
                    if h_start <= current_day <= h_end:
                        is_holiday = True
                        break
            if is_holiday:
                available_days.remove(day) if day in available_days else None
    logger.debug(f"Available days for week {week_start.strftime('%d.%m.%Y')}: {available_days}")
    if not available_days:
        logger.info(f"Week {week_start.strftime('%d.%m.%Y')} has no available days")
        return {"timetable": {group: {} for group in data.keys()}, "available_days": 0}

    group_lessons = defaultdict(list)
    for group, subs in data.items():
        for subject, (h, t, r, s) in subs.items():
            num = get_nums(h, s)[0] if week_type == "левая" else get_nums(h, s)[1]
            num = max(num, len(available_days))  # Гарантируем минимум 1 урок в день
            for _ in range(num):
                group_lessons[group].append({"subject": subject, "teacher": t, "room": r})
        logger.info(f"Group {group}: {len(group_lessons[group])} lessons for {week_type} week")

    max_pairs_per_day = 4
    groups = list(group_lessons.keys())
    if not groups:
        logger.error("No groups to schedule")
        return {"timetable": {}, "available_days": 0, "error": "No groups provided"}

    # Простое распределение: 1 урок в день для каждой группы
    timetable = defaultdict(lambda: defaultdict(dict))
    unscheduled = defaultdict(list)
    for g in groups:
        lessons_g = group_lessons[g][:]
        random.shuffle(lessons_g)
        lessons_per_day = [[] for _ in range(5)]
        # Сначала заполняем по 1 уроку на каждый доступный день
        for i, day in enumerate(available_days):
            if lessons_g:
                lessons_per_day[day].append(lessons_g.pop(0))
        # Распределяем оставшиеся уроки
        for lesson in lessons_g:
            available_days_for_group = [i for i in available_days if len(lessons_per_day[i]) < max_pairs_per_day]
            if available_days_for_group:
                day = random.choice(available_days_for_group)
                lessons_per_day[day].append(lesson)
            else:
                unscheduled[g].append(lesson["subject"])
        for day_idx, lessons in enumerate(lessons_per_day):
            if day_idx not in available_days:
                continue
            for pair, lesson in enumerate(lessons, 1):
                timetable[g][str(day_idx + 1)][str(pair)] = f"{lesson['subject']} | {lesson['teacher']} | {lesson['room']}"

    logger.info(f"Schedule generated for {week_type} week: {dict(timetable)}")
    if unscheduled:
        logger.warning(f"Unscheduled lessons: {dict(unscheduled)}")
    return {
        "timetable": dict(timetable),
        "available_days": len(available_days),
        "unscheduled": {g: lessons for g, lessons in unscheduled.items()}
    }

def save_to_db(data: Dict[str, Dict[str, tuple]], calendar: List[Dict[str, Any]], force_available_days: Optional[Dict[str, int]] = None):
    """Save schedule and group load to database."""
    db = SessionLocal()
    try:
        logger.info("Clearing existing schedules and group loads")
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        if not inspector.has_table("schedules") or not inspector.has_table("group_loads"):
            logger.info("Creating tables schedules and group_loads")
            from models.schema import Base
            Base.metadata.create_all(bind=db.bind)

        db.query(Schedule).delete()
        db.query(GroupLoad).delete()
        unscheduled_lessons = {}
        for week in calendar:
            week_type = week["type"]
            week_start = datetime.strptime(week["start"], "%d.%m.%Y")
            holiday_strings = week.get("holidays", [])
            holiday_ranges = []
            for holiday in holiday_strings:
                start_str, end_str = holiday.split("-") if "-" in holiday else (holiday, holiday)
                holiday_ranges.append((
                    datetime.strptime(start_str, "%d.%m.%Y"),
                    datetime.strptime(end_str, "%d.%m.%Y")
                ))
            result = generate_schedule(week_type, data, week_start, holiday_ranges, force_available_days)
            timetable = result.get("timetable", {})
            if not timetable:
                logger.warning(f"No timetable generated for week {week['start']}. Input data: {data}")
                for group in data.keys():
                    db.add(Schedule(
                        group=group,
                        week_start=week_start,
                        week_type=week_type,
                        timetable=json.dumps({}, ensure_ascii=False)
                    ))
                    logger.debug(f"Saved empty schedule for group {group} on week {week['start']}")
                continue
            if "unscheduled" in result and result["unscheduled"]:
                unscheduled_lessons[week["start"]] = result["unscheduled"]
                logger.warning(f"Unscheduled lessons for week {week['start']}: {result['unscheduled']}")
            for group, group_timetable in timetable.items():
                db.add(Schedule(
                    group=group,
                    week_start=week_start,
                    week_type=week_type,
                    timetable=json.dumps(group_timetable, ensure_ascii=False)
                ))
                logger.debug(f"Saved schedule for group {group} on week {week['start']}, timetable: {group_timetable}")
        for group, load in data.items():
            db.add(GroupLoad(group=group, load=json.dumps(load, ensure_ascii=False)))
            logger.debug(f"Saved group load for {group}")
        db.commit()
        logger.info("Schedule saved to database")
        return unscheduled_lessons
    except Exception as e:
        db.rollback()
        logger.error(f"Database save error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        db.close()