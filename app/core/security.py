from fastapi import Header, HTTPException, status
from typing import Optional
from .config import settings


async def require_admin(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    if not settings.admin_api_key:
        # Admin API key is not configured: deny to be safe
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token not configured. Set ADMIN_API_KEY env and pass X-Admin-Token",
        )
    if not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-Token header",
        )
    if x_admin_token != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token")
    return True

