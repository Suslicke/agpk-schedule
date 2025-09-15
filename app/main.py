from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db
from app.api.routers import schedule, upload, progress, dictionary

app = FastAPI(title="Schedule Management API", description="API for managing academic schedules")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.include_router(schedule.router)
app.include_router(upload.router)
app.include_router(progress.router)
app.include_router(dictionary.router)


@app.get("/")
async def root():
    return {"message": "Welcome to the Schedule Management API"}


@app.get("/healths")
async def healths():
    return {"status": "ok"}

