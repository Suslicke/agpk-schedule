"""Service for replacing teachers, subjects, and rooms in schedules"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app import models, schemas
from app.services.crud import get_or_create_teacher, get_or_create_subject, get_or_create_room

logger = logging.getLogger(__name__)


def replace_teacher(db: Session, request: schemas.ReplaceTeacherRequest) -> dict:
    """
    Replace teacher in schedule.
    If date/start_time provided: replace in specific slot (DayScheduleEntry)
    Otherwise: replace in ScheduleItem (affects all future generations)
    """
    old_teacher = db.query(models.Teacher).filter(models.Teacher.name == request.old_teacher_name).first()
    if not old_teacher:
        raise ValueError(f"Old teacher '{request.old_teacher_name}' not found")

    new_teacher = get_or_create_teacher(db, request.new_teacher_name)  # Will raise if contains '/'
    group = db.query(models.Group).filter(models.Group.name == request.group_name).first()
    if not group:
        raise ValueError(f"Group '{request.group_name}' not found")

    subject = db.query(models.Subject).filter(models.Subject.name == request.subject_name).first()
    if not subject:
        raise ValueError(f"Subject '{request.subject_name}' not found")

    # Case 1: Replace in specific slot (DayScheduleEntry)
    if request.date and request.start_time:
        day_schedule = db.query(models.DaySchedule).filter(models.DaySchedule.date == request.date).first()
        if not day_schedule:
            raise ValueError(f"No schedule found for date {request.date}")

        replaced_count = 0
        for entry in day_schedule.entries:
            if (entry.group_id == group.id and
                entry.subject_id == subject.id and
                entry.teacher_id == old_teacher.id and
                entry.start_time == request.start_time):

                entry.teacher_id = new_teacher.id
                db.add(entry)
                replaced_count += 1
                logger.info(
                    "Replaced teacher in day schedule: date=%s time=%s group=%s subject=%s %s -> %s",
                    request.date, request.start_time, request.group_name, request.subject_name,
                    request.old_teacher_name, request.new_teacher_name
                )

        db.commit()
        return {"replaced_count": replaced_count, "scope": "day_schedule", "date": str(request.date)}

    # Case 2: Replace in ScheduleItem (affects all distributions)
    schedule_item = db.query(models.ScheduleItem).filter(
        models.ScheduleItem.group_id == group.id,
        models.ScheduleItem.subject_id == subject.id
    ).first()

    if not schedule_item:
        raise ValueError(f"Schedule item not found for group '{request.group_name}' and subject '{request.subject_name}'")

    # Replace in teacher assignments
    replaced_assignments = 0
    for assignment in schedule_item.teacher_assignments:
        if assignment.teacher_id == old_teacher.id:
            assignment.teacher_id = new_teacher.id
            db.add(assignment)
            replaced_assignments += 1

    # Also update primary teacher_id if it matches
    if schedule_item.teacher_id == old_teacher.id:
        schedule_item.teacher_id = new_teacher.id
        db.add(schedule_item)

    db.commit()

    logger.info(
        "Replaced teacher in schedule item id=%s: %s -> %s (%d assignments)",
        schedule_item.id, request.old_teacher_name, request.new_teacher_name, replaced_assignments
    )

    return {
        "replaced_count": replaced_assignments,
        "scope": "schedule_item",
        "schedule_item_id": schedule_item.id
    }


def replace_subject(db: Session, request: schemas.ReplaceSubjectRequest) -> dict:
    """Replace subject in a specific day schedule slot"""
    day_schedule = db.query(models.DaySchedule).filter(models.DaySchedule.date == request.date).first()
    if not day_schedule:
        raise ValueError(f"No schedule found for date {request.date}")

    group = db.query(models.Group).filter(models.Group.name == request.group_name).first()
    if not group:
        raise ValueError(f"Group '{request.group_name}' not found")

    old_subject = db.query(models.Subject).filter(models.Subject.name == request.old_subject_name).first()
    if not old_subject:
        raise ValueError(f"Old subject '{request.old_subject_name}' not found")

    new_subject = get_or_create_subject(db, request.new_subject_name)

    replaced_count = 0
    for entry in day_schedule.entries:
        if (entry.group_id == group.id and
            entry.subject_id == old_subject.id and
            entry.start_time == request.start_time):

            entry.subject_id = new_subject.id
            db.add(entry)
            replaced_count += 1
            logger.info(
                "Replaced subject: date=%s time=%s group=%s %s -> %s",
                request.date, request.start_time, request.group_name,
                request.old_subject_name, request.new_subject_name
            )

    db.commit()
    return {"replaced_count": replaced_count, "date": str(request.date)}


def replace_room(db: Session, request: schemas.ReplaceRoomRequest) -> dict:
    """
    Replace room in schedule.
    If date/start_time provided: replace in specific slot
    Otherwise: replace in ScheduleItem (affects all future generations)
    """
    old_room = db.query(models.Room).filter(models.Room.name == request.old_room_name).first()
    if not old_room:
        raise ValueError(f"Old room '{request.old_room_name}' not found")

    new_room = get_or_create_room(db, request.new_room_name)
    group = db.query(models.Group).filter(models.Group.name == request.group_name).first()
    if not group:
        raise ValueError(f"Group '{request.group_name}' not found")

    subject = db.query(models.Subject).filter(models.Subject.name == request.subject_name).first()
    if not subject:
        raise ValueError(f"Subject '{request.subject_name}' not found")

    # Case 1: Replace in specific slot
    if request.date and request.start_time:
        day_schedule = db.query(models.DaySchedule).filter(models.DaySchedule.date == request.date).first()
        if not day_schedule:
            raise ValueError(f"No schedule found for date {request.date}")

        replaced_count = 0
        for entry in day_schedule.entries:
            if (entry.group_id == group.id and
                entry.subject_id == subject.id and
                entry.room_id == old_room.id and
                entry.start_time == request.start_time):

                entry.room_id = new_room.id
                db.add(entry)
                replaced_count += 1
                logger.info(
                    "Replaced room in day schedule: date=%s time=%s group=%s subject=%s %s -> %s",
                    request.date, request.start_time, request.group_name, request.subject_name,
                    request.old_room_name, request.new_room_name
                )

        db.commit()
        return {"replaced_count": replaced_count, "scope": "day_schedule", "date": str(request.date)}

    # Case 2: Replace in ScheduleItem
    schedule_item = db.query(models.ScheduleItem).filter(
        models.ScheduleItem.group_id == group.id,
        models.ScheduleItem.subject_id == subject.id,
        models.ScheduleItem.room_id == old_room.id
    ).first()

    if not schedule_item:
        raise ValueError(f"Schedule item not found")

    schedule_item.room_id = new_room.id
    db.add(schedule_item)
    db.commit()

    logger.info(
        "Replaced room in schedule item id=%s: %s -> %s",
        schedule_item.id, request.old_room_name, request.new_room_name
    )

    return {"replaced_count": 1, "scope": "schedule_item", "schedule_item_id": schedule_item.id}
