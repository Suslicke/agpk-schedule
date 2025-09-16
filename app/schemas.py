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
    # Tuning toggles
    min_pairs_per_day: Optional[int] = 0
    max_pairs_per_day: Optional[int] = 4
    # Prefer packing classes onto these weekdays first (e.g., ["Tuesday", "Thursday"]) 
    preferred_days: Optional[List[str]] = None
    # If true, attempt to concentrate weekly load on preferred days
    concentrate_on_preferred_days: Optional[bool] = False
    # Enable two-shift time slots based on group course (1,3 -> shift1; 2,4 -> shift2)
    enable_shifts: Optional[bool] = True
    # If true (default), run generation in background and return job id immediately
    async_mode: Optional[bool] = True


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


# Mapping: Group - Teacher - Subject
class GroupTeacherSubjectCreate(BaseModel):
    group_name: str
    teacher_name: str
    subject_name: str


class GroupTeacherSubjectResponse(BaseModel):
    id: int
    group_name: str
    teacher_name: str
    subject_name: str

    class Config:
        from_attributes = True


# Day plan scheduling with approvals
class DayPlanCreateRequest(BaseModel):
    date: date
    group_name: Optional[str] = None
    from_plan: bool = True
    # If true, automatically replace vacant/unknown teachers with available ones
    auto_vacant_remove: bool = False
    # Ignore weekly plan conflicts when building ad-hoc day plan
    ignore_weekly_conflicts: Optional[bool] = True
    # Toggles for building a day plan (mostly affects from_plan=false)
    # Max pairs per group for this day
    max_pairs_per_day: Optional[int] = 4
    # Allow repeating same subject multiple times in the day
    allow_repeated_subjects: Optional[bool] = False
    # Cap for repeats of same subject per day (effective only if allow_repeated_subjects)
    max_repeats_per_subject: Optional[int] = 2
    # Use both shifts time slots (up to 8 slots) instead of only shift by course
    use_both_shifts: Optional[bool] = False
    # Include debug reasons in the response why certain pairs were not added
    debug: Optional[bool] = False
    # Enforce consecutive slots without gaps for each group
    enforce_no_gaps: Optional[bool] = True


class DayPlanEntry(BaseModel):
    id: int
    group_name: str
    subject_name: str
    teacher_name: Optional[str] = None
    room_name: str
    start_time: str
    end_time: str
    status: str

    class Config:
        from_attributes = True


class DayPlanResponse(BaseModel):
    id: int
    date: date
    status: str
    entries: List[DayPlanEntry]
    # Stats
    planned_pairs: int
    approved_pairs: int
    planned_hours: float
    approved_hours: float
    # Optional debug notes (why not more pairs etc.)
    reasons: Optional[List[str]] = None

    class Config:
        from_attributes = True


class ReplaceEntryManualRequest(BaseModel):
    entry_id: int
    teacher_name: str


class UpdateEntryManualRequest(BaseModel):
    entry_id: int
    teacher_name: Optional[str] = None
    subject_name: Optional[str] = None
    room_name: Optional[str] = None


class DayReportIssue(BaseModel):
    code: str
    severity: str  # blocker | warning
    message: str
    entry_ids: Optional[List[int]] = None
    group_name: Optional[str] = None
    teacher_name: Optional[str] = None
    room_name: Optional[str] = None


class DayReportGroupStats(BaseModel):
    group_name: str
    planned_pairs: int
    approved_pairs: int
    pending_pairs: int
    windows: int
    duplicates: int
    unknown_teachers: int


class DayReport(BaseModel):
    day_id: int
    date: date
    can_approve: bool
    blockers_count: int
    warnings_count: int
    groups: List[DayReportGroupStats]
    issues: List[DayReportIssue]


# Lookup entries in a day
class EntryLookupItem(BaseModel):
    day_id: int
    date: date
    entry_id: int
    group_name: str
    subject_name: str
    teacher_name: Optional[str] = None
    room_name: str
    start_time: str
    end_time: str
    status: str


class EntryLookupResponse(BaseModel):
    items: List[EntryLookupItem]


# Bulk strict update for a day
class BulkUpdateEntryStrict(BaseModel):
    # How to match: by entry_id OR by (group_name + start_time [+ subject_name])
    entry_id: Optional[int] = None
    group_name: Optional[str] = None
    start_time: Optional[str] = None
    subject_name: Optional[str] = None  # optional disambiguation when matching
    # What to change
    update_teacher_name: Optional[str] = None
    update_subject_name: Optional[str] = None
    update_room_name: Optional[str] = None


class BulkUpdateStrictRequest(BaseModel):
    items: List[BulkUpdateEntryStrict]
    dry_run: Optional[bool] = False


class BulkUpdateStrictResultItem(BaseModel):
    entry_id: Optional[int] = None
    matched_count: int
    status: str  # updated | skipped | error
    error: Optional[str] = None
    old: Optional[dict] = None
    new: Optional[dict] = None


class BulkUpdateStrictResponse(BaseModel):
    updated: int
    skipped: int
    errors: int
    results: List[BulkUpdateStrictResultItem]
    report: DayReport


# Generic schedule query (by date / range)
class ScheduleQueryEntry(BaseModel):
    date: date
    day: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    room_name: str
    group_name: str
    # metadata for UI freshness and origin
    origin: str  # "day_plan" | "weekly"
    approval_status: Optional[str] = None  # approved | replaced_manual | replaced_auto | planned | pending
    is_override: bool = False
    day_id: Optional[int] = None
    entry_id: Optional[int] = None


class ScheduleQueryResponse(BaseModel):
    items: List[ScheduleQueryEntry]


# Progress summary per group/subject
class ProgressSummaryItem(BaseModel):
    group_name: str
    subject_name: str
    assigned_hours: float
    manual_completed_hours: float
    effective_completed_hours: float
    total_hours: float
    remaining_hours: float


class ProgressSummaryResponse(BaseModel):
    items: List[ProgressSummaryItem]


# Progress timeseries (for charts)
class ProgressTimeseriesPoint(BaseModel):
    date: date
    hours: float
    cumulative_hours: float


class ProgressTimeseriesResponse(BaseModel):
    points: List[ProgressTimeseriesPoint]
