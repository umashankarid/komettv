import hashlib
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import (
    PlaylistItem, ContentType, Media, Announcement, MediaType,
)
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/playlist", tags=["playlist"])


# --- Schemas ---

class PlaylistItemCreate(BaseModel):
    content_type: ContentType
    content_id: int
    duration: int | None = None  # Override default duration


class PlaylistItemOut(BaseModel):
    id: int
    content_type: ContentType
    content_id: int
    position: int
    active: bool
    duration: int | None
    created_at: datetime


class PlaylistItemReorder(BaseModel):
    item_ids: list[int]  # Ordered list of playlist item IDs


class PlaylistItemUpdate(BaseModel):
    active: bool | None = None
    duration: int | None = None


class PlayerPlaylistItem(BaseModel):
    """What the TV player receives."""
    id: int
    content_type: ContentType
    duration: int
    data: dict  # Content-specific data (url, html, etc.)


class PlaylistVersion(BaseModel):
    version: str
    refresh_seconds: int


# --- Routes (Admin) ---

@router.get("", response_model=list[PlaylistItemOut])
async def list_playlist_items(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(PlaylistItem).order_by(PlaylistItem.position))
    return result.scalars().all()


@router.post("", response_model=PlaylistItemOut, status_code=201)
async def add_playlist_item(
    data: PlaylistItemCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    # Validate that the referenced content exists
    await _validate_content_exists(db, data.content_type, data.content_id)

    # Get next position
    result = await db.execute(select(func.max(PlaylistItem.position)))
    max_pos = result.scalar() or 0

    item = PlaylistItem(
        content_type=data.content_type,
        content_id=data.content_id,
        position=max_pos + 1,
        duration=data.duration,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.put("/{item_id}", response_model=PlaylistItemOut)
async def update_playlist_item(
    item_id: int,
    data: PlaylistItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(PlaylistItem).where(PlaylistItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Playlist item not found")

    if data.active is not None:
        item.active = data.active
    if data.duration is not None:
        item.duration = data.duration

    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.delete("/{item_id}")
async def delete_playlist_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(PlaylistItem).where(PlaylistItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Playlist item not found")

    await db.delete(item)
    return {"message": "Playlist item deleted"}


@router.post("/reorder")
async def reorder_playlist(
    data: PlaylistItemReorder,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    for position, item_id in enumerate(data.item_ids, start=1):
        result = await db.execute(select(PlaylistItem).where(PlaylistItem.id == item_id))
        item = result.scalar_one_or_none()
        if item:
            item.position = position
            db.add(item)

    return {"message": "Playlist reordered"}


# --- Routes (Public - for TV player) ---

@router.get("/player", response_model=list[PlayerPlaylistItem])
async def get_player_playlist(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns the full playlist with resolved content for the TV player."""
    result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.active == True)
        .order_by(PlaylistItem.position)
    )
    items = result.scalars().all()

    player_items = []
    for item in items:
        content_data = await _resolve_content(db, item)
        if content_data is None:
            continue  # Skip items with missing content

        duration = item.duration or _get_default_duration(item.content_type)

        player_items.append(PlayerPlaylistItem(
            id=item.id,
            content_type=item.content_type,
            duration=duration,
            data=content_data,
        ))

    return player_items


@router.get("/version", response_model=PlaylistVersion)
async def get_playlist_version(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns a version hash so the player knows when to refresh."""
    result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.active == True)
        .order_by(PlaylistItem.position)
    )
    items = result.scalars().all()

    # Create a hash of the current playlist state
    version_data = json.dumps([
        {"id": i.id, "pos": i.position, "type": i.content_type.value, "cid": i.content_id}
        for i in items
    ])
    version_hash = hashlib.md5(version_data.encode()).hexdigest()[:12]

    return PlaylistVersion(
        version=version_hash,
        refresh_seconds=settings.PLAYLIST_REFRESH_SECONDS,
    )


# --- Helpers ---

async def _validate_content_exists(db: AsyncSession, content_type: ContentType, content_id: int):
    if content_type == ContentType.IMAGE or content_type == ContentType.VIDEO:
        result = await db.execute(select(Media).where(Media.id == content_id))
    elif content_type == ContentType.ANNOUNCEMENT:
        result = await db.execute(select(Announcement).where(Announcement.id == content_id))
    else:
        raise HTTPException(status_code=400, detail="Invalid content type")

    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"{content_type.value} with id {content_id} not found")


async def _resolve_content(db: AsyncSession, item: PlaylistItem) -> dict | None:
    """Resolve playlist item to actual content data for the player."""
    if item.content_type in (ContentType.IMAGE, ContentType.VIDEO):
        result = await db.execute(select(Media).where(Media.id == item.content_id))
        media = result.scalar_one_or_none()
        if not media:
            return None
        return {
            "url": media.file_path,
            "filename": media.original_filename,
        }
    elif item.content_type == ContentType.ANNOUNCEMENT:
        result = await db.execute(select(Announcement).where(Announcement.id == item.content_id))
        announcement = result.scalar_one_or_none()
        if not announcement or not announcement.active:
            return None
        return {
            "title": announcement.title,
            "content": announcement.content,
        }
    return None


def _get_default_duration(content_type: ContentType) -> int:
    if content_type == ContentType.IMAGE:
        return settings.DISPLAY_DURATION_IMAGE
    elif content_type == ContentType.ANNOUNCEMENT:
        return settings.DISPLAY_DURATION_ANNOUNCEMENT
    elif content_type == ContentType.VIDEO:
        return 0  # 0 means play to completion
    return 10
