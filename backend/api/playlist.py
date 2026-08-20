import hashlib
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import (
    Playlist, PlaylistItem, ContentType, Media, Announcement, MediaType, Folder, FolderItem, Screen,
)
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/playlist", tags=["playlist"])


# --- Schemas ---

class PlaylistCreate(BaseModel):
    name: str


class PlaylistOut(BaseModel):
    id: int
    name: str
    music_filename: str | None
    music_path: str | None
    item_count: int
    created_at: datetime


class PlaylistItemCreate(BaseModel):
    content_type: ContentType
    content_id: int
    playlist_id: int
    duration: int | None = None


class PlaylistItemOut(BaseModel):
    id: int
    content_type: ContentType
    content_id: int
    content_name: str | None = None
    playlist_id: int | None = None
    position: int
    active: bool
    duration: int | None
    created_at: datetime


class PlaylistItemReorder(BaseModel):
    item_ids: list[int]


class PlaylistItemUpdate(BaseModel):
    active: bool | None = None
    duration: int | None = None


class PlayerPlaylistItem(BaseModel):
    id: int
    content_type: ContentType
    duration: int
    data: dict


class PlaylistVersion(BaseModel):
    version: str
    refresh_seconds: int
    music_url: str | None = None


# --- Playlist CRUD ---

@router.get("/lists", response_model=list[PlaylistOut])
async def list_playlists(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Playlist).order_by(Playlist.created_at))
    playlists = result.scalars().all()

    out = []
    for pl in playlists:
        count_result = await db.execute(
            select(func.count(PlaylistItem.id)).where(PlaylistItem.playlist_id == pl.id)
        )
        out.append(PlaylistOut(
            id=pl.id,
            name=pl.name,
            music_filename=pl.music_filename,
            music_path=pl.music_path,
            item_count=count_result.scalar() or 0,
            created_at=pl.created_at,
        ))
    return out


@router.post("/lists", response_model=PlaylistOut, status_code=201)
async def create_playlist(
    data: PlaylistCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    pl = Playlist(name=data.name)
    db.add(pl)
    await db.flush()
    await db.refresh(pl)
    return PlaylistOut(id=pl.id, name=pl.name, music_filename=pl.music_filename, music_path=pl.music_path, item_count=0, created_at=pl.created_at)


@router.delete("/lists/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Delete all items in this playlist
    items_result = await db.execute(select(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    for item in items_result.scalars().all():
        await db.delete(item)

    await db.delete(pl)
    return {"message": f"Playlist '{pl.name}' deleted"}


class PlaylistMusicSet(BaseModel):
    media_id: int | None = None  # null = remove music


@router.put("/lists/{playlist_id}/music")
async def set_playlist_music(
    playlist_id: int,
    data: PlaylistMusicSet,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Set or remove background music for a playlist from the media library."""
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")

    if data.media_id is None:
        # Remove music
        pl.music_path = None
        pl.music_filename = None
        db.add(pl)
        return {"message": "Music removed"}

    # Set music from media library
    from backend.models.models import MediaType as MT
    media_result = await db.execute(select(Media).where(Media.id == data.media_id))
    media = media_result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.media_type != MT.AUDIO:
        raise HTTPException(status_code=400, detail="Selected media is not an audio file")

    pl.music_path = media.file_path
    pl.music_filename = media.original_filename
    db.add(pl)

    return {"message": "Music set", "filename": media.original_filename, "path": media.file_path}


@router.post("/lists/{playlist_id}/music")
async def upload_playlist_music(
    playlist_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Upload background music directly for a playlist (legacy, still supported)."""
    import os, uuid
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".mp3":
        raise HTTPException(status_code=400, detail="Only MP3 files allowed")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max: 50MB")

    # Save file
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(settings.MEDIA_PATH, "music")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    pl.music_path = f"/media/music/{unique_filename}"
    pl.music_filename = file.filename
    db.add(pl)

    return {"message": "Music uploaded", "filename": file.filename, "path": pl.music_path}


@router.delete("/lists/{playlist_id}/music")
async def remove_playlist_music(
    playlist_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Remove background music from a playlist."""
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    pl = result.scalar_one_or_none()
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")

    pl.music_filename = None
    pl.music_path = None
    db.add(pl)

    return {"message": "Music removed"}


# --- Playlist Items ---

@router.get("", response_model=list[PlaylistItemOut])
async def list_playlist_items(
    playlist_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    query = select(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id).order_by(PlaylistItem.position)
    result = await db.execute(query)
    items = result.scalars().all()

    items_out = []
    for item in items:
        name = await _get_content_name(db, item.content_type, item.content_id)
        items_out.append(PlaylistItemOut(
            id=item.id,
            content_type=item.content_type,
            content_id=item.content_id,
            content_name=name,
            playlist_id=item.playlist_id,
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
    await _validate_content_exists(db, data.content_type, data.content_id)

    # Get next position for this playlist
    pos_query = select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == data.playlist_id)
    result = await db.execute(pos_query)
    max_pos = result.scalar() or 0

    item = PlaylistItem(
        content_type=data.content_type,
        content_id=data.content_id,
        playlist_id=data.playlist_id,
        position=max_pos + 1,
        duration=data.duration,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)

    name = await _get_content_name(db, item.content_type, item.content_id)
    return PlaylistItemOut(
        id=item.id, content_type=item.content_type, content_id=item.content_id,
        content_name=name, playlist_id=item.playlist_id, position=item.position,
        active=item.active, duration=item.duration, created_at=item.created_at,
    )


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

    name = await _get_content_name(db, item.content_type, item.content_id)
    return PlaylistItemOut(
        id=item.id, content_type=item.content_type, content_id=item.content_id,
        content_name=name, playlist_id=item.playlist_id, position=item.position,
        active=item.active, duration=item.duration, created_at=item.created_at,
    )


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


# --- Public Endpoints (for TV player) ---

@router.get("/player", response_model=list[PlayerPlaylistItem])
async def get_player_playlist(
    screen: str = Query(default="main"),
    db: AsyncSession = Depends(get_db),
):
    """Public: get playlist for a screen by slug."""
    # Find screen by slug
    result = await db.execute(select(Screen).where(Screen.slug == screen, Screen.active == True))
    screen_obj = result.scalar_one_or_none()

    if not screen_obj or not screen_obj.playlist_id:
        return []

    # Get items for this screen's playlist
    result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == screen_obj.playlist_id, PlaylistItem.active == True)
        .order_by(PlaylistItem.position)
    )
    items = result.scalars().all()

    player_items = []
    for item in items:
        content_data = await _resolve_content(db, item)
        if content_data is None:
            continue

        duration = item.duration or _get_default_duration(item.content_type)
        player_items.append(PlayerPlaylistItem(
            id=item.id, content_type=item.content_type, duration=duration, data=content_data,
        ))

    return player_items


@router.get("/version", response_model=PlaylistVersion)
async def get_playlist_version(
    screen: str = Query(default="main"),
    db: AsyncSession = Depends(get_db),
):
    """Public: version hash for a screen's playlist."""
    result = await db.execute(select(Screen).where(Screen.slug == screen, Screen.active == True))
    screen_obj = result.scalar_one_or_none()

    if not screen_obj or not screen_obj.playlist_id:
        return PlaylistVersion(version="empty", refresh_seconds=settings.PLAYLIST_REFRESH_SECONDS)

    # Get playlist for music info
    pl_result = await db.execute(select(Playlist).where(Playlist.id == screen_obj.playlist_id))
    playlist_obj = pl_result.scalar_one_or_none()

    result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == screen_obj.playlist_id, PlaylistItem.active == True)
        .order_by(PlaylistItem.position)
    )
    items = result.scalars().all()

    # Include announcement timestamps
    content_timestamps = []
    for item in items:
        if item.content_type == ContentType.ANNOUNCEMENT:
            ann_result = await db.execute(select(Announcement).where(Announcement.id == item.content_id))
            ann = ann_result.scalar_one_or_none()
            if ann and ann.updated_at:
                content_timestamps.append(str(ann.updated_at))

    version_data = json.dumps([
        {"id": i.id, "pos": i.position, "type": i.content_type.value, "cid": i.content_id}
        for i in items
    ] + content_timestamps)
    version_hash = hashlib.md5(version_data.encode()).hexdigest()[:12]

    return PlaylistVersion(
        version=version_hash,
        refresh_seconds=settings.PLAYLIST_REFRESH_SECONDS,
        music_url=playlist_obj.music_path if playlist_obj else None,
    )


# --- Helpers ---

async def _validate_content_exists(db: AsyncSession, content_type: ContentType, content_id: int):
    if content_type in (ContentType.IMAGE, ContentType.VIDEO):
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
    if item.content_type in (ContentType.IMAGE, ContentType.VIDEO):
        result = await db.execute(select(Media).where(Media.id == item.content_id))
        media = result.scalar_one_or_none()
        if not media:
            return None
        return {"url": media.file_path, "filename": media.original_filename}
    elif item.content_type == ContentType.ANNOUNCEMENT:
        result = await db.execute(select(Announcement).where(Announcement.id == item.content_id))
        announcement = result.scalar_one_or_none()
        if not announcement or not announcement.active:
            return None
        return {
            "title": announcement.title, "content": announcement.content,
            "background_color": announcement.background_color,
            "title_color": announcement.title_color, "content_color": announcement.content_color,
            "title_size": announcement.title_size, "content_size": announcement.content_size,
        }
    elif item.content_type == ContentType.FOLDER:
        result = await db.execute(select(Folder).where(Folder.id == item.content_id))
        folder = result.scalar_one_or_none()
        if not folder:
            return None
        items_result = await db.execute(
            select(FolderItem).where(FolderItem.folder_id == folder.id).order_by(FolderItem.position)
        )
        folder_items = items_result.scalars().all()
        if not folder_items:
            return None
        return {
            "name": folder.name, "music_url": folder.music_path,
            "items": [{"url": fi.file_path, "filename": fi.original_filename, "media_type": fi.media_type.value} for fi in folder_items],
        }
    return None


def _get_default_duration(content_type: ContentType) -> int:
    if content_type == ContentType.IMAGE:
        return settings.DISPLAY_DURATION_IMAGE
    elif content_type == ContentType.ANNOUNCEMENT:
        return settings.DISPLAY_DURATION_ANNOUNCEMENT
    elif content_type == ContentType.VIDEO:
        return 0
    elif content_type == ContentType.FOLDER:
        return settings.DISPLAY_DURATION_IMAGE
    return 10


async def _get_content_name(db: AsyncSession, content_type: ContentType, content_id: int) -> str | None:
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
