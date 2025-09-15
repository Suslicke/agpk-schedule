from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:111@127.0.0.1:5433/schedule_db"

    class Config:
        env_file = ".env"


settings = Settings()

