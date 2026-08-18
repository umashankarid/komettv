import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.models import StoredFile
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/storage", tags=["storage"])

STORAGE_DIR = os.path.join(settings.MEDIA_PATH, "storage")
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB per file


# --- Schemas ---

class StoredFileOut(BaseModel):
    id: int
    filename: str
    original_filename: str
    file_size: int
    folder: str
    uploaded_by: str | None
    created_at: datetime


class FolderInfo(BaseModel):
    path: str
    file_count: int


# --- Routes ---

@router.get("", response_model=list[StoredFileOut])
async def list_files(
    folder: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """List files in a specific folder."""
    query = select(StoredFile).where(StoredFile.folder == folder).order_by(StoredFile.original_filename)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/folders", response_model=list[FolderInfo])
async def list_folders(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """List all folders with file counts."""
    result = await db.execute(select(StoredFile.folder))
    all_folders = [row[0] for row in result.fetchall()]

    # Count files per folder
    folder_counts = {}
    for f in all_folders:
        folder_counts[f] = folder_counts.get(f, 0) + 1

    # Always include root
    if "/" not in folder_counts:
        folder_counts["/"] = 0

    return [FolderInfo(path=path, file_count=count) for path, count in sorted(folder_counts.items())]


@router.post("", response_model=StoredFileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form(default="/"),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Upload a file to storage."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read and check size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max: {MAX_FILE_SIZE // (1024*1024)}MB")

    # Normalize folder path
    folder = _normalize_folder(folder)

    # Generate unique filename
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    # Save file
    save_dir = os.path.join(STORAGE_DIR, folder.strip("/"))
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Save to database
    stored_file = StoredFile(
        filename=unique_filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        folder=folder,
        uploaded_by=current_admin.username,
    )
    db.add(stored_file)
    await db.flush()
    await db.refresh(stored_file)
    return stored_file


@router.post("/folder")
async def create_folder(
    path: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Create a folder (just validates the path, folders are virtual)."""
    path = _normalize_folder(path)
    # Create the physical directory
    folder_dir = os.path.join(STORAGE_DIR, path.strip("/"))
    os.makedirs(folder_dir, exist_ok=True)
    return {"path": path, "message": "Folder created"}


@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Download a file."""
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored_file = result.scalar_one_or_none()
    if not stored_file:
        raise HTTPException(status_code=404, detail="File not found")

    if not os.path.exists(stored_file.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=stored_file.file_path,
        filename=stored_file.original_filename,
        media_type="application/octet-stream",
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Delete a file."""
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored_file = result.scalar_one_or_none()
    if not stored_file:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete from disk
    if os.path.exists(stored_file.file_path):
        os.remove(stored_file.file_path)

    await db.delete(stored_file)
    return {"message": "File deleted"}


@router.delete("/folder/{folder_path:path}")
async def delete_folder(
    folder_path: str,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """Delete a folder and all files in it."""
    folder = _normalize_folder(folder_path)

    if folder == "/":
        raise HTTPException(status_code=400, detail="Cannot delete root folder")

    # Find all files in this folder
    result = await db.execute(select(StoredFile).where(StoredFile.folder == folder))
    files = result.scalars().all()

    # Delete files from disk and DB
    for f in files:
        if os.path.exists(f.file_path):
            os.remove(f.file_path)
        await db.delete(f)

    # Try to remove directory
    folder_dir = os.path.join(STORAGE_DIR, folder.strip("/"))
    if os.path.exists(folder_dir):
        try:
            os.rmdir(folder_dir)
        except OSError:
            pass  # Directory not empty (subfolders)

    return {"message": f"Folder '{folder}' deleted with {len(files)} file(s)"}


# --- Helpers ---

def _normalize_folder(path: str) -> str:
    """Normalize folder path: ensure starts with /, no trailing slash, no double slashes."""
    path = path.strip()
    if not path or path == "/":
        return "/"
    # Ensure starts with /
    if not path.startswith("/"):
        path = "/" + path
    # Remove trailing slash
    path = path.rstrip("/")
    # Clean double slashes
    while "//" in path:
        path = path.replace("//", "/")
    return path
