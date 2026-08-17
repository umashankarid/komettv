import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import Folder, FolderItem, MediaType
from backend.api.auth import get_current_admin, Admin
from backend.services.thumbnails import generate_thumbnail

router = APIRouter(prefix="/api/folders", tags=["folders"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4"}
ALLOWED_MUSIC_EXTENSIONS = {".mp3"}


# --- Schemas ---

class FolderOut(BaseModel):
    id: int
    name: str
    music_filename: str | None
    music_path: str | None
    item_count: int
    created_at: datetime


class FolderItemOut(BaseModel):
    id: int
    folder_id: int
    filename: str
    original_filename: str
    media_type: MediaType
    file_path: str
    thumbnail_path: str | None
    file_size: int
    position: int
    created_at: datetime


class FolderCreate(BaseModel):
    name: str


# --- Routes ---

@router.get("", response_model=list[FolderOut])
async def list_folders(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Folder).order_by(Folder.created_at.desc()))
    folders = result.scalars().all()

    folder_list = []
    for folder in folders:
        # Count items
        items_result = await db.execute(
            select(FolderItem).where(FolderItem.folder_id == folder.id)
        )
        item_count = len(items_result.scalars().all())

        folder_list.append(FolderOut(
            id=folder.id,
            name=folder.name,
            music_filename=folder.music_filename,
            music_path=folder.music_path,
            item_count=item_count,
            created_at=folder.created_at,
        ))

    return folder_list


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    data: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    folder = Folder(name=data.name)
    db.add(folder)
    await db.flush()
    await db.refresh(folder)

    return FolderOut(
        id=folder.id,
        name=folder.name,
        music_filename=folder.music_filename,
        music_path=folder.music_path,
        item_count=0,
        created_at=folder.created_at,
    )


@router.get("/{folder_id}/items", response_model=list[FolderItemOut])
async def list_folder_items(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Folder not found")

    result = await db.execute(
        select(FolderItem)
        .where(FolderItem.folder_id == folder_id)
        .order_by(FolderItem.position)
    )
    return result.scalars().all()


@router.post("/{folder_id}/upload", response_model=FolderItemOut | dict, status_code=201)
async def upload_to_folder(
    folder_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    # Verify folder exists
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()

    # Determine file type
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        media_type = MediaType.IMAGE
        max_size = settings.MAX_IMAGE_SIZE
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        media_type = MediaType.VIDEO
        max_size = settings.MAX_VIDEO_SIZE
    elif ext in ALLOWED_MUSIC_EXTENSIONS:
        # Handle music file separately
        content = await file.read()
        if len(content) > settings.MAX_VIDEO_SIZE:  # Use video limit for music
            raise HTTPException(status_code=400, detail="Music file too large")

        unique_filename = f"{uuid.uuid4().hex}{ext}"
        save_dir = os.path.join(settings.MEDIA_PATH, "music")
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, unique_filename)

        with open(file_path, "wb") as f:
            f.write(content)

        # Update folder with music
        folder.music_filename = file.filename
        folder.music_path = f"/media/music/{unique_filename}"
        db.add(folder)

        return {"message": "Music file uploaded", "filename": file.filename, "path": folder.music_path}
    else:
        allowed = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS | ALLOWED_MUSIC_EXTENSIONS
        raise HTTPException(status_code=400, detail=f"File type not allowed. Allowed: {allowed}")

    # Read and validate size
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max: {max_size // (1024*1024)}MB",
        )

    # Save file
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(settings.MEDIA_PATH, "folders")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Generate thumbnail for images
    thumbnail_path = None
    if media_type == MediaType.IMAGE:
        thumbnail_path = generate_thumbnail(file_path, unique_filename)

    # Get next position
    result = await db.execute(
        select(FolderItem)
        .where(FolderItem.folder_id == folder_id)
        .order_by(FolderItem.position.desc())
    )
    last_item = result.scalars().first()
    next_pos = (last_item.position + 1) if last_item else 1

    # Save to database
    folder_item = FolderItem(
        folder_id=folder_id,
        filename=unique_filename,
        original_filename=file.filename,
        media_type=media_type,
        file_path=f"/media/folders/{unique_filename}",
        thumbnail_path=f"/media/thumbnails/{unique_filename}" if thumbnail_path else None,
        file_size=len(content),
        position=next_pos,
    )
    db.add(folder_item)
    await db.flush()
    await db.refresh(folder_item)
    return folder_item


@router.delete("/{folder_id}/items/{item_id}")
async def delete_folder_item(
    folder_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(
        select(FolderItem).where(FolderItem.id == item_id, FolderItem.folder_id == folder_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Delete file
    full_path = os.path.join(settings.MEDIA_PATH, item.file_path.replace("/media/", ""))
    if os.path.exists(full_path):
        os.remove(full_path)
    if item.thumbnail_path:
        thumb_path = os.path.join(settings.MEDIA_PATH, item.thumbnail_path.replace("/media/", ""))
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

    await db.delete(item)
    return {"message": "Item deleted"}


@router.delete("/{folder_id}/music")
async def delete_folder_music(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if folder.music_path:
        full_path = os.path.join(settings.MEDIA_PATH, folder.music_path.replace("/media/", ""))
        if os.path.exists(full_path):
            os.remove(full_path)
        folder.music_filename = None
        folder.music_path = None
        db.add(folder)

    return {"message": "Music removed"}


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Delete all items
    result = await db.execute(select(FolderItem).where(FolderItem.folder_id == folder_id))
    items = result.scalars().all()
    for item in items:
        full_path = os.path.join(settings.MEDIA_PATH, item.file_path.replace("/media/", ""))
        if os.path.exists(full_path):
            os.remove(full_path)
        if item.thumbnail_path:
            thumb_path = os.path.join(settings.MEDIA_PATH, item.thumbnail_path.replace("/media/", ""))
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        await db.delete(item)

    # Delete music
    if folder.music_path:
        music_path = os.path.join(settings.MEDIA_PATH, folder.music_path.replace("/media/", ""))
        if os.path.exists(music_path):
            os.remove(music_path)

    await db.delete(folder)
    return {"message": "Folder deleted"}
