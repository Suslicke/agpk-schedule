# Schedule Management API

FastAPI service to manage and generate academic schedules with daily views and manual progress tracking. Includes Docker and docker-compose for easy setup.

Quick start

- Prereqs: Docker and Docker Compose installed.
- Build and run: `docker-compose up --build`
- API: `http://localhost:8000` (OpenAPI docs at `/docs`).

Config

- Set `DATABASE_URL` to point to Postgres. docker-compose provides: `postgresql://postgres:postgres@db:5432/schedule_db`.

Core endpoints

- `POST /upload/schedule` — upload `.xlsx` (sheet "Нагрузка ООД") to seed schedule items.
- `POST /schedule/generate` — generate for one group/date range.
- `POST /schedule/generate_all` — generate for all groups/date range.
- `GET /schedule/{gen_id}` — get generated schedule with daily slots.
- `GET /schedule/group/{group}/week?week_start=YYYY-MM-DD` — weekly view for group.
- `GET /schedule/teacher/{teacher}/week?week_start=YYYY-MM-DD` — weekly view for teacher.
- NEW `GET /schedule/group/{group}/day?day=YYYY-MM-DD` — daily view for group.
- NEW `GET /schedule/teacher/{teacher}/day?day=YYYY-MM-DD` — daily view for teacher.
- `GET /schedule/schedule_item/{id}/hours` — planned vs remaining (from scheduled slots).
- NEW `GET /schedule/schedule_item/{id}/hours_extended` — planned, manual, effective, remaining.
- NEW `POST /progress/entry` — add manual progress `{schedule_item_id, hours, date?, note?}`.
- NEW `GET /progress/schedule_item/{id}` — list manual progress entries.
- NEW `GET /dict/groups|subjects|teachers|rooms` — dictionary lookups.

Notes

- Schedule is generated per day (stored in `weekly_distributions.daily_schedule`). You can add/edit/delete individual slots with existing teacher slot endpoints.
- Remaining hours consider manual progress if provided; otherwise they reflect assigned slots.
- Структура проекта: весь код внутри пакета `app/` (main, core, models, schemas, services, api/routers). В корне оставлены тонкие шимирующие файлы (`main.py`, `models.py`, `schemas.py`, `crud.py`) для совместимости.
