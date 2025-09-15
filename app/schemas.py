from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from datetime import date


class WeekType(str, Enum):
    even_priority = "even_priority"
    odd_priority = "odd_priority"
    balanced = "balanced"


class ScheduleItemBase(BaseModel):
    group_name: str
    subject_name: str
    teacher_name: str
    room_name: str
    total_hours: float
    weekly_hours: float
    week_type: Optional[WeekType] = WeekType.balanced


class ScheduleItemCreate(ScheduleItemBase):
    pass


class ScheduleItem(ScheduleItemBase):
    id: int
    group_id: int
    subject_id: int
    teacher_id: int
    room_id: int

    class Config:
        from_attributes = True


class HolidayPeriod(BaseModel):
    start_date: date
    end_date: date
    name: Optional[str] = None


class GenerateScheduleRequest(BaseModel):
    group_name: Optional[str] = None
    start_date: date
    end_date: date
    semester: str
    holidays: Optional[List[HolidayPeriod]] = None


class GenerateAllScheduleRequest(BaseModel):
    start_date: date
    end_date: date
    semester: str
    holidays: Optional[List[HolidayPeriod]] = None


class DailySchedule(BaseModel):
    day: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    room_name: str
    group_name: Optional[str] = None

    class Config:
        from_attributes = True


class WeeklyDistributionResponse(BaseModel):
    week_start: date
    week_end: date
    is_even_week: bool
    hours_even: float
    hours_odd: float
    subject_name: str
    teacher_name: str
    room_name: str
    daily_schedule: List[DailySchedule]

    class Config:
        from_attributes = True


class GeneratedScheduleResponse(BaseModel):
    id: int
    start_date: date
    end_date: date
    semester: str
    status: str
    weekly_distributions: List[WeeklyDistributionResponse]

    class Config:
        from_attributes = True


class SlotCreate(BaseModel):
    day: str
    start_time: str
    end_time: str
    subject_name: str
    room_name: str
    group_name: str


class SlotUpdate(BaseModel):
    day: str
    start_time: str
    group_name: str


class HoursResponse(BaseModel):
    assigned_hours: float
    total_hours: float
    remaining_hours: float


class ScheduleItemResponse(BaseModel):
    id: int
    subject_name: str
    group_name: str
    room_name: str
    total_hours: float
    weekly_hours: float
    week_type: str


class ProgressEntryCreate(BaseModel):
    schedule_item_id: int
    hours: float
    date: Optional[date] = None
    note: Optional[str] = None


class ProgressEntryResponse(BaseModel):
    id: int
    schedule_item_id: int
    date: date
    hours: float
    note: Optional[str] = None

    class Config:
        from_attributes = True


class HoursExtendedResponse(BaseModel):
    assigned_hours: float
    manual_completed_hours: float
    effective_completed_hours: float
    total_hours: float
    remaining_hours: float

