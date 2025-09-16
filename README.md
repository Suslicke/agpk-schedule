# Schedule Management API

FastAPI service to manage and generate academic schedules with daily views and manual progress tracking. Includes Docker and docker-compose for easy setup.

Quick start

- Prereqs: Docker and Docker Compose installed.
- Build and run: `docker-compose up --build`
- API: `http://localhost:8000` (OpenAPI docs at `/docs`).
  - Админ-операции требуют заголовок `X-Admin-Token` и настроенную переменную окружения `ADMIN_API_KEY`.

Config

- Set `DATABASE_URL` to point to Postgres. docker-compose provides: `postgresql://postgres:postgres@db:5432/schedule_db`.
- Set `ADMIN_API_KEY` for admin endpoints security (header: `X-Admin-Token`).

Core endpoints

- Upload
  - `POST /admin/upload/schedule` — upload `.xlsx` (sheet "Нагрузка ООД") to seed schedule items. Requires `X-Admin-Token`.

- Schedule (public read)
  - `GET /schedule/{gen_id}` — get generated schedule with daily slots.
  - `GET /schedule/query` — unified query by date/range with filters.
    - Examples:
      - `/schedule/query?date=2025-12-23`
      - `/schedule/query?start_date=2025-12-22&end_date=2025-12-31`
      - `/schedule/query?start_date=2025-12-22&end_date=2025-12-31&group_name=Group1`
      - `/schedule/query?teacher_name=Ivanov I.I.`
    - Метаданные по «свежести»: каждый слот содержит
      - `origin`: `day_plan | weekly`
      - `approval_status`: `approved | replaced_manual | replaced_auto | planned | pending`
      - `is_override`: `true|false` — слот из дневного плана перекрывает недельный
      - `day_id`, `entry_id` (если из дневного плана)
    - Примечание: для дат, на которые есть дневной план, в выдаче приоритет у утверждённых и вручную заменённых пар из дневного плана; слоты недельного плана на эти же (date, group, time) скрываются.

- Day plan
  - `POST /admin/schedule/generate_semester` — generate schedules for a semester (async by default). Requires `X-Admin-Token`.
  - `POST /schedule/day/plan` — (protected) create plan for a date; by default for ALL groups (omit `group_name`). Requires `X-Admin-Token`.
    - Optional: `auto_vacant_remove: true` — automatically replace vacant/unknown teachers with available ones using group-teacher-subject mappings.
  - `GET /schedule/day?date=YYYY-MM-DD` — get day plan.
  - `POST /schedule/day/{day_id}/approve` — (protected) approve day plan. Query params:
    - `group_name` — approve only this group within the day
    - `record_progress` — create SubjectProgress entries (default: true)
    - `enforce_no_blockers` — abort approval if blockers detected (default: false)
    - Returns a detailed `report` with stats, warnings, and blockers.
  - `POST /schedule/day/{day_id}/replace_vacant_auto` — (protected) run auto-replacement manually.
  - `POST /schedule/day/replace_entry_manual` — (protected) manually set a teacher for an entry. Response includes a per-group validation `report`.
  - `POST /schedule/day/update_entry_manual` — (protected) advanced manual update of an entry (teacher/subject/room) with validation report.
  - `GET /schedule/day/entry_lookup?date=YYYY-MM-DD|&day_id=...&group_name=&start_time=&subject_name=&room_name=&teacher_name=` — быстрый поиск `entry_id` по фильтрам.
  - `POST /schedule/day/{day_id}/bulk_update_strict` — (protected) массовое обновление всего дня (строгое):
    - Тело: `{ items: [{ entry_id | group_name+start_time(+subject_name), update_teacher_name?, update_subject_name?, update_room_name? }], dry_run?: false }`
    - Учителя/предметы/аудитории должны существовать — иначе ошибка; проверяются конфликты преподавателя и вместимость аудитории.
    - Возвращает подробные результаты по каждому изменению и итоговый `report` по дню.
  - `GET /schedule/day/{day_id}/report` — validation report for a day (optionally filtered by `group_name`):
    - `can_approve`, counters, per-group stats (planned/approved/pending, windows, duplicates, unknown teachers), and issues list with severity (blocker/warning).

- Progress
  - `POST /progress/entry` — add manual progress `{schedule_item_id, hours, date?, note?}`.
  - `GET /progress/schedule_item/{id}` — list manual progress entries.
  - `GET /progress/summary?group_name=&subject_name=` — summary per group/subject: completed vs plan (shows all if no filters).
  - `GET /progress/timeseries?group_name=&subject_name=&teacher_name=&start_date=&end_date=` — временной ряд выполненных часов для графиков (date, hours, cumulative_hours).

- Dictionary
  - `GET /dict/groups|subjects|teachers|rooms?q=` — dictionary lookups (с поиском по подстроке через `q`).
  - `GET /dict/group_teacher_subjects` — list mappings; `POST /dict/group_teacher_subjects` — (protected) create mapping.

Notes

- Schedule is generated per day (stored in `weekly_distributions.daily_schedule`).
- Remaining hours consider manual progress if provided; otherwise they reflect assigned slots.
- Структура проекта: код в пакете `app/` (main, core, models, schemas, services, api/routers).

Logging

- Logs include request IDs and are written to console and `logs/app.log` (rotating).
- Configure via `.env` or environment variables:
  - `LOG_LEVEL` (default `INFO`; use `DEBUG` to trace slot assignment decisions)
  - `LOG_TO_FILE` (default `True`)
  - `LOG_FILE_PATH` (default `logs/app.log`)
  - `LOG_MAX_BYTES` (default `10485760`)
  - `LOG_BACKUP_COUNT` (default `5`)
- Every API call emits entries like: `[request_id] METHOD /path -> status in ms`.
- Schedule generation logs why slots are skipped (room busy, teacher/group busy, gym capacity, daily max) and what was assigned per week.

Security
- All mutating endpoints are protected and also mirrored under `/admin`.
- Set `ADMIN_API_KEY` and pass it in header `X-Admin-Token`.
- Recommended hardening in production:
  - Restrict `/admin/*` by IP (reverse proxy) and TLS only.
  - Rotate `ADMIN_API_KEY` periodically and store in a secrets manager.
  - Consider OAuth2 if you need multi-user roles.
