import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.models import Screen
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/screens", tags=["screens"])


# --- Schemas ---

class ScreenCreate(BaseModel):
    name: str
    slug: str  # URL-friendly: only lowercase letters, numbers, hyphens
    playlist_id: int | None = None
    orientation: str = "horizontal"
    rotation: str = "0"


class ScreenUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    playlist_id: int | None = None
    orientation: str | None = None
    rotation: str | None = None
    active: bool | None = None


class ScreenOut(BaseModel):
    id: int
    name: str
    slug: str
    playlist_id: int | None
    orientation: str
    rotation: str
    active: bool
    created_at: datetime


# --- Routes ---

@router.get("", response_model=list[ScreenOut])
async def list_screens(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Screen).order_by(Screen.created_at))
    return result.scalars().all()


@router.post("", response_model=ScreenOut, status_code=201)
async def create_screen(
    data: ScreenCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    # Validate slug format
    if not re.match(r'^[a-z0-9][a-z0-9\-]*$', data.slug):
        raise HTTPException(status_code=400, detail="Slug must be lowercase letters, numbers, and hyphens only")

    # Check slug is unique
    result = await db.execute(select(Screen).where(Screen.slug == data.slug))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A screen with this slug already exists")

    screen = Screen(
        name=data.name,
        slug=data.slug,
        playlist_id=data.playlist_id,
        orientation=data.orientation,
        rotation=data.rotation,
    )
    db.add(screen)
    await db.flush()
    await db.refresh(screen)
    return screen


@router.put("/{screen_id}", response_model=ScreenOut)
async def update_screen(
    screen_id: int,
    data: ScreenUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Screen).where(Screen.id == screen_id))
    screen = result.scalar_one_or_none()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")

    if data.name is not None:
        screen.name = data.name
    if data.slug is not None:
        if not re.match(r'^[a-z0-9][a-z0-9\-]*$', data.slug):
            raise HTTPException(status_code=400, detail="Slug must be lowercase letters, numbers, and hyphens only")
        # Check uniqueness
        existing = await db.execute(select(Screen).where(Screen.slug == data.slug, Screen.id != screen_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="A screen with this slug already exists")
        screen.slug = data.slug
    if data.playlist_id is not None:
        screen.playlist_id = data.playlist_id
    if data.orientation is not None:
        screen.orientation = data.orientation
    if data.rotation is not None:
        screen.rotation = data.rotation
    if data.active is not None:
        screen.active = data.active

    db.add(screen)
    await db.flush()
    await db.refresh(screen)
    return screen


@router.delete("/{screen_id}")
async def delete_screen(
    screen_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Screen).where(Screen.id == screen_id))
    screen = result.scalar_one_or_none()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")

    await db.delete(screen)
    return {"message": f"Screen '{screen.name}' deleted"}


# --- Public endpoint for player ---

@router.get("/by-slug/{slug}")
async def get_screen_settings(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Public: get screen settings by slug for the player."""
    result = await db.execute(select(Screen).where(Screen.slug == slug, Screen.active == True))
    screen = result.scalar_one_or_none()
    if not screen:
        return None
    return {
        "id": screen.id,
        "name": screen.name,
        "slug": screen.slug,
        "orientation": screen.orientation,
        "rotation": screen.rotation,
    }
