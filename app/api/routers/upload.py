import logging
import pandas as pd
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.services import crud
from app.core.database import get_db
from io import BytesIO
from app.core.security import require_admin

router = APIRouter(prefix="/upload", tags=["upload"])
logger = logging.getLogger(__name__)


@router.post(
    "/schedule",
    summary="Upload Excel (.xlsx) with base schedule items",
    tags=["upload"],
)
async def upload_schedule(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Only .xlsx files allowed")
    content = await file.read()
    df = pd.read_excel(BytesIO(content), sheet_name="Нагрузка ООД")
    logger.info("Uploading schedule file: %s", file.filename)
    items = crud.parse_and_create_schedule_items(db, df)
    logger.info("Parsed and created %d items", len(items))
    return {"created_items": len(items)}
