from pydantic import BaseModel, Field

try:
    # pydantic v2
    from pydantic import AliasChoices
except Exception:
    AliasChoices = None  # type: ignore
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


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
    # Override base date to compute even/odd weeks (YYYY-MM-DD)
    parity_base_date: Optional[date] = None
    # Override pair size in academic hours for this run (default from settings)
    pair_size_academic_hours: Optional[int] = None


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
    job_id: Optional[str] = None
    stats: Optional[Dict] = None  # Statistics: total_pairs, warnings, hours_exceeded, etc.
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
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
    # If True, clears existing entries before creating new ones (default False to preserve existing entries)
    clear_existing: Optional[bool] = False
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
    # Reference weekly plan for this date (same shape as entries, without status)
    plan_entries: Optional[List[DayPlanEntry]] = None
    # Differences vs weekly plan for this date
    differences: Optional[List[dict]] = None
    diff_counters: Optional[dict] = None
    # Aggregated summaries for convenience
    group_hours_summary: Optional[List[dict]] = None  # [{group_name, actual_pairs, plan_pairs, delta_pairs, actual_hours_AH, plan_hours_AH, delta_hours_AH}]
    subject_hours_summary: Optional[List[dict]] = None  # [{group_name, subject_name, actual_pairs, plan_pairs, delta_pairs, actual_hours_AH, plan_hours_AH, delta_hours_AH}]

    class Config:
        from_attributes = True


class ReplaceEntryManualRequest(BaseModel):
    entry_id: int
    # Accept both teacher_name and teacherName
    teacher_name: str = Field(
        ..., validation_alias=(AliasChoices("teacher_name", "teacherName") if AliasChoices else None)
    )


class UpdateEntryManualRequest(BaseModel):
    entry_id: int
    # Accept both snake_case and camelCase for all fields
    teacher_name: Optional[str] = Field(
        default=None,
        validation_alias=(AliasChoices("teacher_name", "teacherName") if AliasChoices else None),
    )
    subject_name: Optional[str] = Field(
        default=None,
        validation_alias=(AliasChoices("subject_name", "subjectName") if AliasChoices else None),
    )
    room_name: Optional[str] = Field(
        default=None,
        validation_alias=(AliasChoices("room_name", "roomName") if AliasChoices else None),
    )


# Manual add/delete + autofill for day plan
class AddEntryManualRequest(BaseModel):
    date: date
    group_name: str
    start_time: str
    end_time: Optional[str] = None  # if not set, derived from slot grid by start_time
    subject_name: str
    room_name: str
    teacher_name: Optional[str] = None
    # Validation/creation flags
    ignore_weekly_conflicts: Optional[bool] = True
    allow_create_entities: Optional[bool] = True  # create missing subject/room/teacher if needed


class DeleteEntryResponse(BaseModel):
    deleted: bool
    day_id: int
    date: date


class AutofillDayRequest(BaseModel):
    date: date
    group_name: Optional[str] = None
    ensure_pairs_per_day: int = 2  # ensure at least this many pairs per group on this date
    # Tuning
    allow_repeated_subjects: Optional[bool] = False
    max_repeats_per_subject: Optional[int] = 2
    use_both_shifts: Optional[bool] = False
    ignore_weekly_conflicts: Optional[bool] = True

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
    teacher_name: str  # Legacy: first teacher or joined with "/"
    teacher_names: Optional[List[str]] = None  # All teachers (supports multiple teachers per subject)
    room_name: str
    group_name: str
    # metadata for UI freshness and origin
    origin: str  # "day_plan" | "weekly"
    approval_status: Optional[str] = None  # approved | replaced_manual | replaced_auto | planned | pending
    is_override: bool = False
    day_id: Optional[int] = None
    entry_id: Optional[int] = None
    # week parity information
    is_even_week: Optional[bool] = None  # True for even weeks, False for odd weeks


class ScheduleQueryResponse(BaseModel):
    items: List[ScheduleQueryEntry]


# --- Replacement schemas ---
class ReplaceTeacherRequest(BaseModel):
    """Replace teacher in a specific time slot or for entire schedule item"""
    date: Optional[date] = None  # Specific date (for single slot replacement)
    start_time: Optional[str] = None  # Start time (for single slot replacement)
    group_name: str
    subject_name: str
    old_teacher_name: str
    new_teacher_name: str
    # If date/start_time not provided, replaces for ALL occurrences of this schedule item


class ReplaceSubjectRequest(BaseModel):
    """Replace subject in a specific time slot"""
    date: date
    start_time: str
    group_name: str
    old_subject_name: str
    new_subject_name: str


class ReplaceRoomRequest(BaseModel):
    """Replace room in a specific time slot or for entire schedule item"""
    date: Optional[date] = None
    start_time: Optional[str] = None
    group_name: str
    subject_name: str
    old_room_name: str
    new_room_name: str


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


class ExportDayRequest(BaseModel):
    date: date
    group_name: Optional[str] = None
    groups: Optional[List[str]] = None


class ExportScheduleRequest(BaseModel):
    # Range or period-based
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    period: Optional[str] = None  # week | month | semester
    anchor_date: Optional[date] = None
    semester_name: Optional[str] = None
    # Filters
    groups: Optional[List[str]] = None
    # View and formatting
    view: Optional[str] = "all"  # plan | actual | diff | all
    split_by_group: Optional[bool] = False


# --- Day entry room swap ---
class RoomSwapChoice(BaseModel):
    entry_id: int
    room_name: str = Field(
        ..., validation_alias=(AliasChoices("room_name", "roomName") if AliasChoices else None)
    )


class SwapRoomRequest(BaseModel):
    desired_room_name: str = Field(
        ..., validation_alias=(AliasChoices("desired_room_name", "desiredRoomName") if AliasChoices else None)
    )
    choices: Optional[List[RoomSwapChoice]] = None
    dry_run: Optional[bool] = False


class RoomSwapConflictItem(BaseModel):
    entry_id: int
    group_name: str
    subject_name: str
    teacher_name: Optional[str] = None
    room_name: str
    alternatives: List[str]


class RoomSwapPlanResponse(BaseModel):
    entry_id: int
    date: date
    start_time: str
    end_time: str
    desired_room_name: str
    is_free: bool
    conflicts: List[RoomSwapConflictItem]
    can_auto_resolve: bool


# --- Teacher swap ---
class TeacherSwapChoice(BaseModel):
    entry_id: int
    teacher_name: str = Field(
        ..., validation_alias=(AliasChoices("teacher_name", "teacherName") if AliasChoices else None)
    )


class SwapTeacherRequest(BaseModel):
    desired_teacher_name: str = Field(
        ..., validation_alias=(AliasChoices("desired_teacher_name", "desiredTeacherName") if AliasChoices else None)
    )
    choices: Optional[List[TeacherSwapChoice]] = None
    dry_run: Optional[bool] = False


class TeacherSwapConflictItem(BaseModel):
    entry_id: int
    group_name: str
    subject_name: str
    teacher_name: Optional[str] = None
    alternatives: List[str]


class TeacherSwapPlanResponse(BaseModel):
    entry_id: int
    date: date
    start_time: str
    end_time: str
    desired_teacher_name: str
    desired_subject_name: Optional[str] = None
    is_free: bool
    conflicts: List[TeacherSwapConflictItem]
    can_auto_resolve: bool


# --- Analytics ---
class AnalyticsFilter(BaseModel):
    start_date: date
    end_date: date
    groups: Optional[List[str]] = None
    teachers: Optional[List[str]] = None
    subjects: Optional[List[str]] = None
    rooms: Optional[List[str]] = None
    # Count "actual" только по утвержденным записям дневного плана
    only_approved: Optional[bool] = False


class TeacherSummaryItem(BaseModel):
    teacher_name: str
    group_name: str
    subject_name: str
    planned_pairs: int
    planned_hours_AH: float
    actual_pairs: int  # from day plan entries (approved/replaced)
    actual_hours_AH: float
    total_plan_hours_AH: float
    percent_assigned: float  # planned_hours / total_plan_hours
    percent_actual: float  # actual_hours / total_plan_hours
    manual_completed_hours_AH: float
    effective_hours_AH: float  # actual_hours + manual_completed; capped by total_plan_hours
    percent_effective: float


class GroupSubjectSummaryItem(BaseModel):
    group_name: str
    subject_name: str
    planned_pairs: int
    planned_hours_AH: float
    actual_pairs: int
    actual_hours_AH: float
    total_plan_hours_AH: float
    percent_assigned: float
    percent_actual: float
    manual_completed_hours_AH: float
    effective_hours_AH: float
    percent_effective: float


class RoomSummaryItem(BaseModel):
    room_name: str
    planned_pairs: int
    actual_pairs: int
    planned_hours_AH: float
    actual_hours_AH: float


class HeatmapResponse(BaseModel):
    days: List[str]
    slots: List[str]
    matrix: List[List[int]]  # rows=days, cols=slots
    totals_by_day: List[int]
    totals_by_slot: List[int]


class DistributionItem(BaseModel):
    name: str
    planned_pairs: int
    actual_pairs: int
    planned_hours_AH: float
    actual_hours_AH: float


class ScheduleTimeseriesPoint(BaseModel):
    date: date
    planned_pairs: int
    actual_pairs: int
    planned_hours_AH: float
    actual_hours_AH: float


class TeacherSummaryResponse(BaseModel):
    items: List[TeacherSummaryItem]


class GroupSummaryResponse(BaseModel):
    items: List[GroupSubjectSummaryItem]


class RoomSummaryResponse(BaseModel):
    items: List[RoomSummaryItem]


class DistributionResponse(BaseModel):
    items: List[DistributionItem]


class ScheduleTimeseriesResponse(BaseModel):
    points: List[ScheduleTimeseriesPoint]


# Practice periods schemas
class PracticeCreate(BaseModel):
    group_name: str
    start_date: date
    end_date: date
    name: Optional[str] = None


class PracticeResponse(BaseModel):
    id: int
    group_name: str
    start_date: date
    end_date: date
    name: Optional[str] = None

    class Config:
        from_attributes = True


class PracticeListResponse(BaseModel):
    items: List[PracticeResponse]
