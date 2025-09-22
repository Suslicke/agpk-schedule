from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:111@127.0.0.1:5433/schedule_db"
    # Logging
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    log_to_file: bool = True
    log_file_path: str = "logs/app.log"
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 5
    # Admin API key protection
    admin_api_key: str | None = None  # set via env ADMIN_API_KEY
    # Scheduling semantics
    # Academic hour length (minutes). Commonly 45.
    academic_hour_minutes: int = 45
    # One pair (lesson slot) size in academic hours (usually 2x45min = 2 academic hours)
    pair_size_academic_hours: int = 2
    # Parity base date to compute even/odd weeks (e.g., first study week Monday)
    # If None, defaults to 2025-09-01 for current dataset
    parity_base_date: str | None = "2025-09-01"
    # If True, interpret imported total_hours as ANNUAL and halve them for semester generation
    total_hours_is_annual: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
