from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.models import Announcement
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


# --- Schemas ---

class AnnouncementCreate(BaseModel):
    title: str
    content: str  # HTML content
    background_color: str | None = None  # Hex color e.g. #3B82F6
    active: bool = True


class AnnouncementUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    background_color: str | None = None
    active: bool | None = None


class AnnouncementOut(BaseModel):
    id: int
    title: str
    content: str
    background_color: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


# --- Routes ---

@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Announcement).order_by(Announcement.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=AnnouncementOut, status_code=201)
async def create_announcement(
    data: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    announcement = Announcement(
        title=data.title,
        content=data.content,
        background_color=data.background_color,
        active=data.active,
    )
    db.add(announcement)
    await db.flush()
    await db.refresh(announcement)
    return announcement


@router.put("/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    announcement_id: int,
    data: AnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = result.scalar_one_or_none()
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")

    if data.title is not None:
        announcement.title = data.title
    if data.content is not None:
        announcement.content = data.content
    if data.background_color is not None:
        announcement.background_color = data.background_color
    if data.active is not None:
        announcement.active = data.active

    announcement.updated_at = datetime.utcnow()
    db.add(announcement)
    await db.flush()
    await db.refresh(announcement)
    return announcement


@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = result.scalar_one_or_none()
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")

    await db.delete(announcement)
    return {"message": "Announcement deleted"}
