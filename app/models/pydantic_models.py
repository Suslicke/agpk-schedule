from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class ScheduleRequest(BaseModel):
    data_str: Optional[str] = Field(
        None,
        description="Lesson data in format: 'group|subject|hours|teacher|room|side'. One lesson per line.",
        example="Т25-1|Информатика|2|Боранбаева Г.У./Шамшиева Ш.Ш.|ГК300а/ГК300б|"
    )
    start_even_week: str = Field(
        "01.09.2025",
        description="Start of even week (DD.MM.YYYY)",
        pattern=r"^\d{2}\.\d{2}\.\d{4}$"
    )
    end_year_date: str = Field(
        "03.07.2026",
        description="End of academic year (DD.MM.YYYY)",
        pattern=r"^\d{2}\.\d{2}\.\d{4}$"
    )
    holidays: Optional[List[str]] = Field(
        ["25.12.2025-05.01.2026"],
        description="Holiday periods in format 'DD.MM.YYYY-DD.MM.YYYY'",
        example=["25.12.2025-05.01.2026"]
    )

    @field_validator("start_even_week", "end_year_date")
    @classmethod
    def validate_date_format(cls, v):
        from datetime import datetime
        try:
            datetime.strptime(v, "%d.%m.%Y")
        except ValueError:
            raise ValueError("Date must be in DD.MM.YYYY format")
        return v

    @field_validator("holidays")
    @classmethod
    def validate_holidays(cls, v):
        from datetime import datetime
        if v:
            for holiday in v:
                try:
                    start, end = holiday.split("-")
                    datetime.strptime(start, "%d.%m.%Y")
                    datetime.strptime(end, "%d.%m.%Y")
                except ValueError:
                    raise ValueError("Holiday must be in DD.MM.YYYY-DD.MM.YYYY format")
        return v