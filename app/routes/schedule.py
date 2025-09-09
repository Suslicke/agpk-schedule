from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Query
from fastapi.responses import PlainTextResponse
from models.pydantic_models import ScheduleRequest
from utils.schedule_utils import parse_data_from_excel, parse_data_from_string, generate_calendar, generate_schedule, save_to_db
from models.database import SessionLocal
from models.schema import Schedule, GroupLoad
import json
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/schedule",
    tags=["Schedule"]
)

@router.post(
    "/generate/",
    summary="Generate and save schedule",
    description="Generates schedule with at least 1 lesson per day per group, ignores weekends."
)
async def generate_schedule_endpoint(
    start_even_week: str = Query("01.09.2025", description="Start date of even week (DD.MM.YYYY)"),
    end_year_date: str = Query("31.12.2025", description="End date of the year (DD.MM.YYYY)"),
    holidays: str = Query("22.12.2025-05.01.2026", description="Comma-separated list of holidays (DD.MM.YYYY or ranges DD.MM.YYYY-DD.MM.YYYY)"),
    force_available_days: str | None = Query(None, description="Force available days for weeks, e.g., '22.12.2025:3' for 3 days"),
    data_str: str | None = Query(None, description="Raw schedule data as string"),
    file: UploadFile | None = File(None)
):
    """Generate and save schedule."""
    try:
        logger.info("Processing POST /generate_schedule/")
        if not isinstance(holidays, str):
            logger.error(f"Expected string for holidays, got {type(holidays)}: {holidays}")
            raise HTTPException(status_code=400, detail=f"Holidays must be a comma-separated string, got {type(holidays)}: {holidays}")

        holidays_list = [h.strip() for h in holidays.split(",") if h.strip()]
        logger.info(f"Parsed holidays: {holidays_list}")
        schedule_request = ScheduleRequest(
            start_even_week=start_even_week,
            end_year_date=end_year_date,
            holidays=holidays_list,
            data_str=data_str
        )

        if file:
            content = await file.read()
            data_dict = parse_data_from_excel(content)
            logger.info(f"Parsed Excel file, found {len(data_dict)} groups: {list(data_dict.keys())}")
        elif schedule_request.data_str:
            data_dict = parse_data_from_string(schedule_request.data_str)
            logger.info(f"Parsed data_str, found {len(data_dict)} groups: {list(data_dict.keys())}")
        else:
            logger.error("No Excel file or data_str provided")
            raise HTTPException(status_code=400, detail="Provide either an Excel file or data_str")

        parsed_holidays = []
        for h in holidays_list:
            if isinstance(h, str) and "-" in h:
                start, end = h.split("-", 1)
                parsed_holidays.append({"start": start.strip(), "end": end.strip()})
            else:
                parsed_holidays.append(h)

        force_available_days_dict = {}
        if force_available_days:
            for entry in force_available_days.split(","):
                if ":" in entry:
                    week_start, days = entry.split(":")
                    try:
                        days = int(days)
                        if days < 0 or days > 5:
                            raise ValueError(f"Invalid number of days for {week_start}: {days}")
                        force_available_days_dict[week_start.strip()] = days
                    except ValueError as e:
                        logger.error(f"Invalid force_available_days format: {entry}")
                        raise HTTPException(status_code=400, detail=f"Invalid force_available_days format: {entry}")

        calendar = generate_calendar(
            schedule_request.start_even_week,
            schedule_request.end_year_date,
            parsed_holidays
        )
        logger.info(f"Generated calendar with {len(calendar)} weeks")
        unscheduled = save_to_db(data_dict, calendar, force_available_days_dict)
        
        response = f"Расписание сгенерировано успешно.\nГруппы: {', '.join(data_dict.keys())}\nНедели: {len(calendar)}\nНераспределенные уроки: {unscheduled}"
        logger.info("Schedule generation completed successfully")
        return PlainTextResponse(content=response)
    except HTTPException as e:
        logger.error(f"HTTP error: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in generate_schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@router.get(
    "/{group}/day",
    summary="Get group schedule for a specific day and remaining week",
    description="Returns schedule for a group for the specified day and the rest of the week (until Friday). Date format: DD.MM.YYYY."
)
async def get_group_schedule_day(
    group: str = Path(..., description="Group name, e.g., Т25-1"),
    date: str = Query(..., description="Specific date (DD.MM.YYYY)", pattern=r"^\d{2}\.\d{2}\.\d{4}$")
):
    """Get schedule for a group and specific day, including remaining week."""
    db = SessionLocal()
    try:
        logger.info(f"Fetching schedule for group {group} on date {date}")
        input_date = datetime.strptime(date, "%d.%m.%Y")
        week_start_date = input_date - timedelta(days=input_date.weekday())
        schedule = db.query(Schedule).filter(
            Schedule.group == group,
            Schedule.week_start == week_start_date
        ).first()
        
        if not schedule:
            logger.warning(f"No schedule found for group {group} on week starting {week_start_date.strftime('%d.%m.%Y')}")
            return PlainTextResponse(
                content=f"Расписание для группы {group} на неделю с {week_start_date.strftime('%d.%m.%Y')} не найдено. Сгенерируйте через POST /generate_schedule/."
            )
        
        day_of_week = input_date.weekday() + 1  # 1=Понедельник, ..., 5=Пятница
        if day_of_week > 5:
            return PlainTextResponse(content=f"Дата {date} — выходной день (суббота или воскресенье). Выберите будний день.")

        timetable = json.loads(schedule.timetable)
        response = f"Расписание для группы {group} на {date} (тип недели: {schedule.week_type}):\n"
        day_schedule = timetable.get(str(day_of_week), {})
        if day_schedule:
            response += f"День {date}:\n"
            for pair, lesson in sorted(day_schedule.items(), key=lambda x: int(x[0])):
                response += f"Пара {pair}: {lesson}\n"
        else:
            response += f"День {date}: нет занятий\n"

        response += f"\nОстаток недели (до пятницы):\n"
        for day in range(day_of_week + 1, 6):
            day_schedule = timetable.get(str(day), {})
            day_date = (week_start_date + timedelta(days=day-1)).strftime("%d.%m.%Y")
            response += f"День {day_date}:\n"
            if day_schedule:
                for pair, lesson in sorted(day_schedule.items(), key=lambda x: int(x[0])):
                    response += f"Пара {pair}: {lesson}\n"
            else:
                response += "Нет занятий\n"

        logger.info(f"Retrieved schedule for group {group} on {date}")
        return PlainTextResponse(content=response)
    except ValueError:
        logger.error(f"Invalid date format: {date}")
        raise HTTPException(status_code=400, detail="Неверный формат даты: DD.MM.YYYY")
    except Exception as e:
        logger.error(f"Error in get_schedule_day: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        db.close()

@router.get(
    "/{group}",
    summary="Get group schedule for a week",
    description="Returns schedule for a group for the specified week (Monday start, DD.MM.YYYY)."
)
async def get_group_schedule(
    group: str = Path(..., description="Group name, e.g., Т25-1"),
    week_start: str = Query(..., description="Week start (Monday, DD.MM.YYYY)", pattern=r"^\d{2}\.\d{2}\.\d{4}$")
):
    """Get schedule for a group and week."""
    db = SessionLocal()
    try:
        logger.info(f"Fetching schedule for group {group} on week {week_start}")
        week_start_date = datetime.strptime(week_start, "%d.%m.%Y")
        schedule = db.query(Schedule).filter(
            Schedule.group == group,
            Schedule.week_start == week_start_date
        ).first()
        
        if not schedule:
            logger.warning(f"No schedule found for group {group} on {week_start}")
            return PlainTextResponse(
                content=f"Расписание для группы {group} на {week_start} не найдено. Сгенерируйте через POST /generate_schedule/."
            )
        
        timetable = json.loads(schedule.timetable)
        full_timetable = {str(i): timetable.get(str(i), {}) for i in range(1, 6)}  # Только будни
        response = f"Расписание для группы {group} на неделю с {week_start} (тип недели: {schedule.week_type}):\n"
        for day, day_schedule in full_timetable.items():
            day_date = (week_start_date + timedelta(days=int(day)-1)).strftime("%d.%m.%Y")
            response += f"День {day_date} (день {day}):\n"
            if day_schedule:
                for pair, lesson in sorted(day_schedule.items(), key=lambda x: int(x[0])):
                    response += f"Пара {pair}: {lesson}\n"
            else:
                response += "Нет занятий\n"
        logger.info(f"Retrieved schedule for group {group} on {week_start}, week_type: {schedule.week_type}")
        return PlainTextResponse(content=response)
    except ValueError:
        logger.error(f"Invalid date format: {week_start}")
        raise HTTPException(status_code=400, detail="Неверный формат даты: DD.MM.YYYY")
    except Exception as e:
        logger.error(f"Error in get_schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")
    finally:
        db.close()