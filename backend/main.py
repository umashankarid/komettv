import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.database import init_db
from backend.config import settings
from backend.api.auth import router as auth_router
from backend.api.media import router as media_router
from backend.api.announcements import router as announcements_router
from backend.api.playlist import router as playlist_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and create directories on startup."""
    # Ensure media directories exist
    os.makedirs(os.path.join(settings.MEDIA_PATH, "images"), exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_PATH, "videos"), exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_PATH, "thumbnails"), exist_ok=True)

    await init_db()
    yield


app = FastAPI(
    title="Komet TV",
    description="Digital signage platform for BMK Komet",
    version="1.0.0",
    lifespan=lifespan,
)

# Register API routers
app.include_router(auth_router)
app.include_router(media_router)
app.include_router(announcements_router)
app.include_router(playlist_router)


# Serve TV player at /display/main
@app.get("/display/main")
async def serve_player():
    return FileResponse("player/main.html", media_type="text/html")


# Serve Admin frontend at /admin
@app.get("/admin")
async def serve_admin():
    return FileResponse("admin/index.html", media_type="text/html")


# Serve static media files
app.mount("/media", StaticFiles(directory=settings.MEDIA_PATH), name="media")

# Serve static assets for player (CSS/JS if separated later)
app.mount("/player", StaticFiles(directory="player"), name="player")

# Serve static assets for admin (CSS/JS)
app.mount("/admin/static", StaticFiles(directory="admin"), name="admin_static")
