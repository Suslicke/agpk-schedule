from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from enum import Enum


class WeekType(Enum):
    EVEN_PRIORITY = "even_priority"
    ODD_PRIORITY = "odd_priority"
    BALANCED = "balanced"


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    schedule_items = relationship("ScheduleItem", back_populates="group", cascade="all, delete-orphan")


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    schedule_items = relationship("ScheduleItem", back_populates="subject", cascade="all, delete-orphan")


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    schedule_items = relationship("ScheduleItem", back_populates="teacher", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    schedule_items = relationship("ScheduleItem", back_populates="room", cascade="all, delete-orphan")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    total_hours = Column(Float, nullable=False)
    weekly_hours = Column(Float, nullable=False)
    week_type = Column(String, default=WeekType.BALANCED.value, nullable=False)
    group = relationship("Group", back_populates="schedule_items")
    subject = relationship("Subject", back_populates="schedule_items")
    teacher = relationship("Teacher", back_populates="schedule_items")
    room = relationship("Room", back_populates="schedule_items")


class Holiday(Base):
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    name = Column(String, nullable=False)


class GeneratedSchedule(Base):
    __tablename__ = "generated_schedules"
    id = Column(Integer, primary_key=True, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    semester = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    status = Column(String, default="pending", nullable=False)
    group = relationship("Group")
    weekly_distributions = relationship(
        "WeeklyDistribution",
        back_populates="generated_schedule",
        cascade="all, delete-orphan"
    )


class WeeklyDistribution(Base):
    __tablename__ = "weekly_distributions"
    id = Column(Integer, primary_key=True, index=True)
    generated_schedule_id = Column(Integer, ForeignKey("generated_schedules.id"), nullable=False, index=True)
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)
    is_even_week = Column(Integer, default=0, nullable=False)
    schedule_item_id = Column(Integer, ForeignKey("schedule_items.id"), nullable=False, index=True)
    hours_even = Column(Float, default=0.0, nullable=False)
    hours_odd = Column(Float, default=0.0, nullable=False)
    daily_schedule = Column(JSON, nullable=True)
    generated_schedule = relationship("GeneratedSchedule", back_populates="weekly_distributions")
    schedule_item = relationship("ScheduleItem")


class SubjectProgress(Base):
    __tablename__ = "subject_progress"
    id = Column(Integer, primary_key=True, index=True)
    schedule_item_id = Column(Integer, ForeignKey("schedule_items.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    hours = Column(Float, nullable=False)
    note = Column(String, nullable=True)


# Mapping between Group, Teacher, and Subject for replacements/permissions
class GroupTeacherSubject(Base):
    __tablename__ = "group_teacher_subjects"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)


# Day plan with approvals
class DaySchedule(Base):
    __tablename__ = "day_schedules"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    status = Column(String, default="pending", nullable=False)
    entries = relationship("DayScheduleEntry", back_populates="day_schedule", cascade="all, delete-orphan")


class DayScheduleEntry(Base):
    __tablename__ = "day_schedule_entries"
    id = Column(Integer, primary_key=True, index=True)
    day_schedule_id = Column(Integer, ForeignKey("day_schedules.id"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending/approved/replaced
    schedule_item_id = Column(Integer, ForeignKey("schedule_items.id"), nullable=True, index=True)

    day_schedule = relationship("DaySchedule", back_populates="entries")


# Practice periods for groups
class Practice(Base):
    __tablename__ = "practices"
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    name = Column(String, nullable=True)  # optional description
    group = relationship("Group")
