from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import logging

logger = logging.getLogger(__name__)

# PostgreSQL configuration
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "111")
# Use localhost when connecting from host machine to Docker container
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")  
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")  # Host port
POSTGRES_DB = os.getenv("POSTGRES_DB", "schedule_db")
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

logger.info(f"Attempting to connect to database: {DATABASE_URL}")
try:
    engine = create_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    logger.info("Database connection established")
except Exception as e:
    logger.error(f"Failed to connect to database: {str(e)}")
    raise Exception(f"Database connection failed: {str(e)}")