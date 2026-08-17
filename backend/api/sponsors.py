import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import Sponsor
from backend.api.auth import get_current_admin, Admin
from backend.services.thumbnails import generate_thumbnail

router = APIRouter(prefix="/api/sponsors", tags=["sponsors"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


# --- Schemas ---

class SponsorOut(BaseModel):
    id: int
    name: str
    logo_filename: str
    logo_path: str
    thumbnail_path: str | None
    active: bool
    created_at: datetime


# --- Routes ---

@router.get("", response_model=list[SponsorOut])
async def list_sponsors(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Sponsor).order_by(Sponsor.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=SponsorOut, status_code=201)
async def create_sponsor(
    name: str = Form(...),
    logo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    if not logo.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(logo.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Allowed: {ALLOWED_EXTENSIONS}")

    content = await logo.read()
    if len(content) > settings.MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max: {settings.MAX_IMAGE_SIZE // (1024*1024)}MB")

    # Save file
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(settings.MEDIA_PATH, "sponsors")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Generate thumbnail
    thumbnail_path = generate_thumbnail(file_path, unique_filename)

    sponsor = Sponsor(
        name=name,
        logo_filename=unique_filename,
        logo_path=f"/media/sponsors/{unique_filename}",
        thumbnail_path=f"/media/thumbnails/{unique_filename}" if thumbnail_path else None,
    )
    db.add(sponsor)
    await db.flush()
    await db.refresh(sponsor)
    return sponsor


@router.put("/{sponsor_id}", response_model=SponsorOut)
async def update_sponsor(
    sponsor_id: int,
    name: str = Form(None),
    active: bool = Form(None),
    logo: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Sponsor).where(Sponsor.id == sponsor_id))
    sponsor = result.scalar_one_or_none()
    if not sponsor:
        raise HTTPException(status_code=404, detail="Sponsor not found")

    if name is not None:
        sponsor.name = name
    if active is not None:
        sponsor.active = active

    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"File type not allowed")

        content = await logo.read()
        if len(content) > settings.MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="File too large")

        # Delete old file
        old_path = os.path.join(settings.MEDIA_PATH, sponsor.logo_path.replace("/media/", ""))
        if os.path.exists(old_path):
            os.remove(old_path)
        if sponsor.thumbnail_path:
            old_thumb = os.path.join(settings.MEDIA_PATH, sponsor.thumbnail_path.replace("/media/", ""))
            if os.path.exists(old_thumb):
                os.remove(old_thumb)

        # Save new file
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        save_dir = os.path.join(settings.MEDIA_PATH, "sponsors")
        file_path = os.path.join(save_dir, unique_filename)

        with open(file_path, "wb") as f:
            f.write(content)

        thumbnail_path = generate_thumbnail(file_path, unique_filename)

        sponsor.logo_filename = unique_filename
        sponsor.logo_path = f"/media/sponsors/{unique_filename}"
        sponsor.thumbnail_path = f"/media/thumbnails/{unique_filename}" if thumbnail_path else None

    db.add(sponsor)
    await db.flush()
    await db.refresh(sponsor)
    return sponsor


@router.delete("/{sponsor_id}")
async def delete_sponsor(
    sponsor_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Sponsor).where(Sponsor.id == sponsor_id))
    sponsor = result.scalar_one_or_none()
    if not sponsor:
        raise HTTPException(status_code=404, detail="Sponsor not found")

    # Delete files
    logo_path = os.path.join(settings.MEDIA_PATH, sponsor.logo_path.replace("/media/", ""))
    if os.path.exists(logo_path):
        os.remove(logo_path)
    if sponsor.thumbnail_path:
        thumb_path = os.path.join(settings.MEDIA_PATH, sponsor.thumbnail_path.replace("/media/", ""))
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

    await db.delete(sponsor)
    return {"message": "Sponsor deleted"}
