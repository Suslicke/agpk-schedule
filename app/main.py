from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import uuid
from routes import schedule, info

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

# Custom logging filter to add request_id
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(record, 'request_id', 'N/A')
        return True

console_handler.addFilter(RequestIdFilter())
logger.addHandler(console_handler)

# Middleware to add request_id
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        console_handler.setFormatter(
            logging.Formatter(f"%(asctime)s [%(levelname)s] [RequestID: {request_id}] %(message)s")
        )
        response = await call_next(request)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        return response

# FastAPI app
app = FastAPI(
    title="Генератор Расписания Уроков",
    description="API для генерации и хранения расписания уроков с учётом: спортзал (до 4 групп), до 4 пар в день (пн-пт), без окон, каникулы.",
    version="2.0.8",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add middleware
app.add_middleware(RequestIdMiddleware)

# Include routers
app.include_router(schedule.router)
app.include_router(info.router)

@app.get(
    "/",
    summary="API root",
    description="Root endpoint with API information.",
    tags=["Info"]
)
async def root():
    """API root endpoint."""
    logger.info("Root endpoint accessed")
    return JSONResponse(content={
        "status": "success",
        "message": "Schedule Generator API. Use POST /generate_schedule/ to generate, GET /schedule/{group} for schedules, GET /groups/ for groups, GET /debug/db/ for DB contents.",
        "data": {}
    })

logger.info("FastAPI application started")