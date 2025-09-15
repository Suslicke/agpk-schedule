import pytest
import httpx
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from collections import defaultdict
import logging
import models

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация базы данных (замените на ваши реальные данные)
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:111@127.0.0.1:5432/schedule_db"  # Замените user, password, schedule_db
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый URL API
BASE_URL = "http://127.0.0.1:8000"

# Фикстура для сессии базы данных
@pytest.fixture(scope="function")
def db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Фикстура для асинхронного HTTP-клиента
@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        try:
            # Проверка доступности сервера
            response = await client.get("/")
            if response.status_code != 200:
                logger.error(f"Server not available: {response.status_code} {response.text}")
                pytest.skip("Server not available")
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to server: {e}")
            pytest.skip("Failed to connect to server")
        yield client

# Фикстура для проверки наличия данных в базе
@pytest.fixture(scope="function")
def ensure_data(db):
    groups = db.query(models.Group).count()
    if groups == 0:
        logger.error("No groups found in database")
        pytest.skip("No groups in database. Please upload Excel file.")
    yield

# Тест 1: Проверка генерации расписания без каникул
@pytest.mark.asyncio
async def test_generate_schedule_no_holidays(client, ensure_data):
    payload = {
        "start_date": "2025-12-01",
        "end_date": "2025-12-07",
        "semester": "2025-2026",
        "holidays": []
    }
    response = await client.post("/schedule/generate_all", json=payload)
    assert response.status_code == 200, f"Failed to generate schedule: {response.text}"
    schedules = response.json()
    assert len(schedules) > 0, "No schedules generated"
    for schedule in schedules:
        assert schedule["status"] == "completed", f"Schedule {schedule['id']} is not completed: {schedule['status']}"
        assert len(schedule["weekly_distributions"]) > 0, f"No distributions for schedule {schedule['id']}"

# Тест 2: Проверка генерации расписания с каникулами (22–24 декабря)
@pytest.mark.asyncio
async def test_generate_schedule_with_holidays(client, ensure_data):
    payload = {
        "start_date": "2025-12-22",
        "end_date": "2025-12-31",
        "semester": "2025-2026",
        "holidays": [
            {
                "start_date": "2025-12-25",
                "end_date": "2025-12-31",
                "name": "winter"
            }
        ]
    }
    response = await client.post("/schedule/generate_all", json=payload)
    assert response.status_code == 200, f"Failed to generate schedule: {response.text}"
    schedules = response.json()
    assert len(schedules) > 0, "No schedules generated"
    
    for schedule in schedules:
        assert schedule["status"] == "completed", f"Schedule {schedule['id']} is not completed: {schedule['status']}"
        for dist in schedule["weekly_distributions"]:
            assert dist["week_start"] == "2025-12-22", f"Unexpected week_start: {dist['week_start']}"
            assert dist["week_end"] == "2025-12-24", f"Unexpected week_end: {dist['week_end']}"
            for slot in dist["daily_schedule"]:
                assert slot["day"] in ["Monday", "Tuesday", "Wednesday"], f"Holiday slot found: {slot['day']}"

# Тест 3: Проверка отсутствия пересечений для групп
@pytest.mark.asyncio
async def test_no_group_conflicts(client, db, ensure_data):
    payload = {
        "start_date": "2025-12-22",
        "end_date": "2025-12-31",
        "semester": "2025-2026",
        "holidays": [
            {
                "start_date": "2025-12-25",
                "end_date": "2025-12-31",
                "name": "winter"
            }
        ]
    }
    response = await client.post("/schedule/generate_all", json=payload)
    assert response.status_code == 200, f"Failed to generate schedule: {response.text}"
    schedules = response.json()
    
    for schedule in schedules:
        group_id = schedule["group_id"]
        group_slots = defaultdict(list)
        for dist in schedule["weekly_distributions"]:
            week_start = date.fromisoformat(dist["week_start"])
            for slot in dist["daily_schedule"]:
                try:
                    day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                    slot_date = week_start + timedelta(days=day_idx)
                    slot_key = (slot_date, slot["start_time"])
                    group_slots[slot_key].append(slot)
                except ValueError:
                    continue
        
        for slot_key, slots in group_slots.items():
            assert len(slots) == 1, f"Group {group_id} has conflict at {slot_key}: {slots}"

# Тест 4: Проверка отсутствия пересечений для преподавателей
@pytest.mark.asyncio
async def test_no_teacher_conflicts(client, db, ensure_data):
    payload = {
        "start_date": "2025-12-22",
        "end_date": "2025-12-31",
        "semester": "2025-2026",
        "holidays": [
            {
                "start_date": "2025-12-25",
                "end_date": "2025-12-31",
                "name": "winter"
            }
        ]
    }
    response = await client.post("/schedule/generate_all", json=payload)
    assert response.status_code == 200, f"Failed to generate schedule: {response.text}"
    schedules = response.json()
    
    teacher_slots = defaultdict(list)
    for schedule in schedules:
        for dist in schedule["weekly_distributions"]:
            week_start = date.fromisoformat(dist["week_start"])
            for slot in dist["daily_schedule"]:
                try:
                    day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                    slot_date = week_start + timedelta(days=day_idx)
                    slot_key = (slot_date, slot["start_time"], slot["teacher_name"])
                    teacher_slots[slot_key].append(slot)
                except ValueError:
                    continue
    
    for slot_key, slots in teacher_slots.items():
        assert len(slots) == 1, f"Teacher {slot_key[2]} has conflict at {slot_key[0]} {slot_key[1]}: {slots}"

# Тест 5: Проверка отсутствия пересечений для комнат
@pytest.mark.asyncio
async def test_no_room_conflicts(client, db, ensure_data):
    payload = {
        "start_date": "2025-12-22",
        "end_date": "2025-12-31",
        "semester": "2025-2026",
        "holidays": [
            {
                "start_date": "2025-12-25",
                "end_date": "2025-12-31",
                "name": "winter"
            }
        ]
    }
    response = await client.post("/schedule/generate_all", json=payload)
    assert response.status_code == 200, f"Failed to generate schedule: {response.text}"
    schedules = response.json()
    
    room_slots = defaultdict(list)
    for schedule in schedules:
        for dist in schedule["weekly_distributions"]:
            week_start = date.fromisoformat(dist["week_start"])
            for slot in dist["daily_schedule"]:
                try:
                    day_idx = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].index(slot["day"])
                    slot_date = week_start + timedelta(days=day_idx)
                    slot_key = (slot_date, slot["start_time"], slot["room_name"])
                    room_slots[slot_key].append(slot)
                except ValueError:
                    continue
    
    for slot_key, slots in room_slots.items():
        room_name = slot_key[2]
        max_capacity = 4 if "Спортзал" in room_name else 1
        assert len(slots) <= max_capacity, f"Room {room_name} has conflict at {slot_key[0]} {slot_key[1]}: {slots}"

# Тест 6: Проверка расписания группы через endpoint
@pytest.mark.asyncio
async def test_group_week_schedule(client, ensure_data):
    group_name = "Group1"  # Замените на реальное имя группы из вашего Excel
    week_start = "2025-12-22"
    response = await client.get(f"/schedule/group/{group_name}/week?week_start={week_start}")
    assert response.status_code == 200, f"Failed to get schedule for {group_name}: {response.text}"
    slots = response.json()
    for slot in slots:
        assert slot["day"] in ["Monday", "Tuesday", "Wednesday"], f"Holiday slot found for {group_name}: {slot['day']}"