import os
from PIL import Image
from backend.config import settings

THUMBNAIL_SIZE = (300, 300)


def generate_thumbnail(source_path: str, filename: str) -> str | None:
    """Generate a thumbnail for an image file. Returns the thumbnail path or None on failure."""
    try:
        thumb_dir = os.path.join(settings.MEDIA_PATH, "thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)

        thumb_path = os.path.join(thumb_dir, filename)

        with Image.open(source_path) as img:
            img.thumbnail(THUMBNAIL_SIZE)
            # Convert RGBA to RGB for JPEG compatibility
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(thumb_path, quality=85)

        return thumb_path
    except Exception:
        return None
