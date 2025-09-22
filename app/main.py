from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db
from app.api.routers import schedule, upload, progress, dictionary, admin, export, analytics
from app.core.config import settings
from app.core.logging_config import setup_logging, RequestIdMiddleware

setup_logging(
    level=settings.log_level,
    to_file=settings.log_to_file,
    file_path=settings.log_file_path,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)

tags_metadata = [
    {"name": "schedule", "description": "Генерация и запрос расписания (по дате/диапазону)"},
    {"name": "day_plan", "description": "Планирование дня: создание плана, авто/ручная замена и утверждение"},
    {"name": "progress", "description": "Учет часов: фактически проведенные часы vs план"},
    {"name": "dictionary", "description": "Справочники (группы, предметы, преподаватели, аудитории)"},
    {"name": "upload", "description": "Импорт исходных данных (например, xlsx)"},
]

app = FastAPI(
    title="Schedule Management API",
    description="API для генерации, планирования и учета расписания",
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIdMiddleware)

init_db()

app.include_router(schedule.router)
app.include_router(upload.router)
app.include_router(progress.router)
app.include_router(dictionary.router)
app.include_router(admin.router)
app.include_router(export.router)
app.include_router(analytics.router)


@app.get("/")
async def root():
    return {"message": "Welcome to the Schedule Management API"}


@app.get("/healths")
async def healths():
    return {"status": "ok"}
