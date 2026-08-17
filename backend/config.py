import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "komet123")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-to-a-random-string")

    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/app/data/komet-tv.db")
    MEDIA_PATH: str = os.getenv("MEDIA_PATH", "/app/media")

    PLAYLIST_REFRESH_SECONDS: int = int(os.getenv("PLAYLIST_REFRESH_SECONDS", "30"))

    DISPLAY_DURATION_IMAGE: int = int(os.getenv("DISPLAY_DURATION_IMAGE", "5"))
    DISPLAY_DURATION_ANNOUNCEMENT: int = int(os.getenv("DISPLAY_DURATION_ANNOUNCEMENT", "15"))

    MAX_IMAGE_SIZE: int = int(os.getenv("MAX_IMAGE_SIZE", "10485760"))
    MAX_VIDEO_SIZE: int = int(os.getenv("MAX_VIDEO_SIZE", "209715200"))

    # JWT settings
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ALGORITHM: str = "HS256"


settings = Settings()
