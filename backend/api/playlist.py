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
    PlaylistItem, ContentType, Media, Announcement, MediaType, Folder, FolderItem,
)
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/playlist", tags=["playlist"])


# --- Schemas ---

class PlaylistItemCreate(BaseModel):
    content_type: ContentType
    content_id: int
    screen_id: int | None = None  # null = default screen (main)
    duration: int | None = None  # Override default duration


class PlaylistItemOut(BaseModel):
    id: int
    content_type: ContentType
    content_id: int
    content_name: str | None = None
    screen_id: int | None = None
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
    screen_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    query = select(PlaylistItem).order_by(PlaylistItem.position)
    if screen_id is not None:
        query = query.where(PlaylistItem.screen_id == screen_id)
    else:
        query = query.where(PlaylistItem.screen_id == None)

    result = await db.execute(query)
    items = result.scalars().all()

    # Resolve content names
    items_out = []
    for item in items:
        name = await _get_content_name(db, item.content_type, item.content_id)
        items_out.append(PlaylistItemOut(
            id=item.id,
            content_type=item.content_type,
            content_id=item.content_id,
            content_name=name,
            screen_id=item.screen_id,
            position=item.position,
            active=item.active,
            duration=item.duration,
            created_at=item.created_at,
        ))

    return items_out


@router.post("", response_model=PlaylistItemOut, status_code=201)
async def add_playlist_item(
    data: PlaylistItemCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    # Validate that the referenced content exists
    await _validate_content_exists(db, data.content_type, data.content_id)

    # Get next position for this screen
    pos_query = select(func.max(PlaylistItem.position))
    if data.screen_id is not None:
        pos_query = pos_query.where(PlaylistItem.screen_id == data.screen_id)
    else:
        pos_query = pos_query.where(PlaylistItem.screen_id == None)
    result = await db.execute(pos_query)
    max_pos = result.scalar() or 0

    item = PlaylistItem(
        content_type=data.content_type,
        content_id=data.content_id,
        screen_id=data.screen_id,
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
async def get_player_playlist(
    screen_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: returns the full playlist with resolved content for the TV player."""
    query = select(PlaylistItem).where(PlaylistItem.active == True).order_by(PlaylistItem.position)
    if screen_id is not None:
        query = query.where(PlaylistItem.screen_id == screen_id)
    else:
        query = query.where(PlaylistItem.screen_id == None)

    result = await db.execute(query)
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
async def get_playlist_version(
    screen_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: returns a version hash so the player knows when to refresh."""
    query = select(PlaylistItem).where(PlaylistItem.active == True).order_by(PlaylistItem.position)
    if screen_id is not None:
        query = query.where(PlaylistItem.screen_id == screen_id)
    else:
        query = query.where(PlaylistItem.screen_id == None)

    result = await db.execute(query)
    items = result.scalars().all()

    # Include content timestamps so edits trigger a version change
    content_timestamps = []
    for item in items:
        if item.content_type == ContentType.ANNOUNCEMENT:
            ann_result = await db.execute(
                select(Announcement).where(Announcement.id == item.content_id)
            )
            ann = ann_result.scalar_one_or_none()
            if ann and ann.updated_at:
                content_timestamps.append(str(ann.updated_at))

    # Create a hash of the current playlist state + content changes
    version_data = json.dumps([
        {"id": i.id, "pos": i.position, "type": i.content_type.value, "cid": i.content_id}
        for i in items
    ] + content_timestamps)
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
    elif content_type == ContentType.FOLDER:
        result = await db.execute(select(Folder).where(Folder.id == content_id))
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
            "background_color": announcement.background_color,
            "title_color": announcement.title_color,
            "content_color": announcement.content_color,
            "title_size": announcement.title_size,
            "content_size": announcement.content_size,
        }
    elif item.content_type == ContentType.FOLDER:
        result = await db.execute(select(Folder).where(Folder.id == item.content_id))
        folder = result.scalar_one_or_none()
        if not folder:
            return None

        # Get folder items
        items_result = await db.execute(
            select(FolderItem)
            .where(FolderItem.folder_id == folder.id)
            .order_by(FolderItem.position)
        )
        folder_items = items_result.scalars().all()
        if not folder_items:
            return None

        return {
            "name": folder.name,
            "music_url": folder.music_path,
            "items": [
                {
                    "url": fi.file_path,
                    "filename": fi.original_filename,
                    "media_type": fi.media_type.value,
                }
                for fi in folder_items
            ],
        }
    return None


def _get_default_duration(content_type: ContentType) -> int:
    if content_type == ContentType.IMAGE:
        return settings.DISPLAY_DURATION_IMAGE
    elif content_type == ContentType.ANNOUNCEMENT:
        return settings.DISPLAY_DURATION_ANNOUNCEMENT
    elif content_type == ContentType.VIDEO:
        return 0  # 0 means play to completion
    elif content_type == ContentType.FOLDER:
        return settings.DISPLAY_DURATION_IMAGE  # Per-item duration within folder
    return 10


async def _get_content_name(db: AsyncSession, content_type: ContentType, content_id: int) -> str | None:
    """Get a human-readable name for a playlist item's content."""
    if content_type in (ContentType.IMAGE, ContentType.VIDEO):
        result = await db.execute(select(Media).where(Media.id == content_id))
        media = result.scalar_one_or_none()
        return media.original_filename if media else None
    elif content_type == ContentType.ANNOUNCEMENT:
        result = await db.execute(select(Announcement).where(Announcement.id == content_id))
        ann = result.scalar_one_or_none()
        return ann.title if ann else None
    elif content_type == ContentType.FOLDER:
        result = await db.execute(select(Folder).where(Folder.id == content_id))
        folder = result.scalar_one_or_none()
        return folder.name if folder else None
    return None
