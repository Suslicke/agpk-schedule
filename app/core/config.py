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

    class Config:
        env_file = ".env"


settings = Settings()
