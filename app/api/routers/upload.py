import pandas as pd
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.services import crud
from app.core.database import get_db
from io import BytesIO

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/schedule")
async def upload_schedule(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="Only .xlsx files allowed")
    content = await file.read()
    df = pd.read_excel(BytesIO(content), sheet_name="Нагрузка ООД")
    items = crud.parse_and_create_schedule_items(db, df)
    return {"created_items": len(items)}

