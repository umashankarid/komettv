import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import Media, MediaType
from backend.api.auth import get_current_admin, Admin
from backend.services.thumbnails import generate_thumbnail

router = APIRouter(prefix="/api/media", tags=["media"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4"}


# --- Schemas ---

class MediaOut(BaseModel):
    id: int
    filename: str
    original_filename: str
    media_type: MediaType
    file_path: str
    thumbnail_path: str | None
    file_size: int
    created_at: datetime


# --- Routes ---

@router.get("", response_model=list[MediaOut])
async def list_media(
    media_type: MediaType | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    query = select(Media)
    if media_type:
        query = query.where(Media.media_type == media_type)
    query = query.order_by(Media.created_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()

    # Determine media type
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        media_type = MediaType.IMAGE
        max_size = settings.MAX_IMAGE_SIZE
        subfolder = "images"
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        media_type = MediaType.VIDEO
        max_size = settings.MAX_VIDEO_SIZE
        subfolder = "videos"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS}",
        )

    # Read file content
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size: {max_size // (1024*1024)}MB",
        )

    # Generate unique filename
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(settings.MEDIA_PATH, subfolder)
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    # Save file
    with open(file_path, "wb") as f:
        f.write(content)

    # Generate thumbnail
    thumbnail_path = None
    if media_type == MediaType.IMAGE:
        thumbnail_path = generate_thumbnail(file_path, unique_filename)

    # Save to database
    media_item = Media(
        filename=unique_filename,
        original_filename=file.filename,
        media_type=media_type,
        file_path=f"/media/{subfolder}/{unique_filename}",
        thumbnail_path=f"/media/thumbnails/{unique_filename}" if thumbnail_path else None,
        file_size=len(content),
    )
    db.add(media_item)
    await db.flush()
    await db.refresh(media_item)
    return media_item


@router.delete("/{media_id}")
async def delete_media(
    media_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Media).where(Media.id == media_id))
    media_item = result.scalar_one_or_none()
    if not media_item:
        raise HTTPException(status_code=404, detail="Media not found")

    # Delete files from disk
    full_path = os.path.join(settings.MEDIA_PATH, media_item.file_path.replace("/media/", ""))
    if os.path.exists(full_path):
        os.remove(full_path)

    if media_item.thumbnail_path:
        thumb_path = os.path.join(settings.MEDIA_PATH, media_item.thumbnail_path.replace("/media/", ""))
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

    # Remove from all playlists
    from backend.models.models import PlaylistItem, ContentType
    content_type = ContentType.IMAGE if media_item.media_type == MediaType.IMAGE else ContentType.VIDEO
    playlist_items = await db.execute(
        select(PlaylistItem).where(
            PlaylistItem.content_type == content_type,
            PlaylistItem.content_id == media_id,
        )
    )
    for pi in playlist_items.scalars().all():
        await db.delete(pi)

    await db.delete(media_item)
    return {"message": "Media deleted"}
