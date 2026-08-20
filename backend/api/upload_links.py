import os
import uuid
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import UploadLink, Media, MediaType
from backend.api.auth import get_current_admin, Admin
from backend.services.thumbnails import generate_thumbnail

router = APIRouter(prefix="/api/upload-links", tags=["upload-links"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


# --- Schemas ---

class UploadLinkCreate(BaseModel):
    label: str
    expires_at: datetime | None = None


class UploadLinkOut(BaseModel):
    id: int
    token: str
    label: str
    used: bool
    file_count: int
    created_by: str | None
    expires_at: datetime | None
    used_at: datetime | None
    created_at: datetime


class UploadLinkStatus(BaseModel):
    valid: bool
    label: str | None = None
    message: str


# --- Admin Routes ---

@router.get("", response_model=list[UploadLinkOut])
async def list_upload_links(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(UploadLink).order_by(UploadLink.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=UploadLinkOut, status_code=201)
async def create_upload_link(
    data: UploadLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    token = secrets.token_urlsafe(48)  # 64-char URL-safe token

    link = UploadLink(
        token=token,
        label=data.label,
        created_by=current_admin.username,
        expires_at=data.expires_at,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    return link


@router.delete("/{link_id}")
async def delete_upload_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(UploadLink).where(UploadLink.id == link_id))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Upload link not found")

    await db.delete(link)
    return {"message": "Upload link deleted"}


# --- Public Routes (no auth required) ---

@router.get("/status/{token}", response_model=UploadLinkStatus)
async def check_upload_link(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Check if an upload link is valid."""
    result = await db.execute(select(UploadLink).where(UploadLink.token == token))
    link = result.scalar_one_or_none()

    if not link:
        return UploadLinkStatus(valid=False, message="This link is invalid.")

    if link.used:
        return UploadLinkStatus(valid=False, label=link.label, message="This link has already been used.")

    if link.expires_at and datetime.utcnow() > link.expires_at:
        return UploadLinkStatus(valid=False, label=link.label, message="This link has expired.")

    return UploadLinkStatus(valid=True, label=link.label, message="Ready to upload photos.")


@router.post("/upload/{token}")
async def upload_via_link(
    token: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Public: upload a photo using a one-time link."""
    result = await db.execute(select(UploadLink).where(UploadLink.token == token))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Invalid upload link")

    if link.used:
        raise HTTPException(status_code=410, detail="This link has already been used")

    if link.expires_at and datetime.utcnow() > link.expires_at:
        raise HTTPException(status_code=410, detail="This link has expired")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Only photos allowed: {ALLOWED_EXTENSIONS}")

    content = await file.read()
    if len(content) > settings.MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max: {settings.MAX_IMAGE_SIZE // (1024*1024)}MB")

    # Save file
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(settings.MEDIA_PATH, "images")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Generate thumbnail
    thumbnail_path = generate_thumbnail(file_path, unique_filename)

    # Save to media library
    media_item = Media(
        filename=unique_filename,
        original_filename=file.filename,
        media_type=MediaType.IMAGE,
        file_path=f"/media/images/{unique_filename}",
        thumbnail_path=f"/media/thumbnails/{unique_filename}" if thumbnail_path else None,
        file_size=len(content),
    )
    db.add(media_item)

    # Update link file count
    link.file_count += 1

    return {"message": "Photo uploaded!", "filename": file.filename, "count": link.file_count}


@router.post("/done/{token}")
async def mark_upload_done(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public: mark the upload link as used (user clicked 'Done')."""
    result = await db.execute(select(UploadLink).where(UploadLink.token == token))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Invalid upload link")

    link.used = True
    link.used_at = datetime.utcnow()
    db.add(link)

    return {"message": "Upload complete! This link is now deactivated.", "file_count": link.file_count}
