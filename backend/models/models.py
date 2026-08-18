import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase
import enum


class Base(DeclarativeBase):
    pass


class MediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"


class ContentType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    ANNOUNCEMENT = "announcement"
    FOLDER = "folder"


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Media(Base):
    __tablename__ = "media"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    media_type = Column(SAEnum(MediaType), nullable=False)
    file_path = Column(String(500), nullable=False)
    thumbnail_path = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)  # HTML content
    background_color = Column(String(7), nullable=True)  # Hex color e.g. #3B82F6
    title_color = Column(String(7), nullable=True)  # Hex color, default white
    content_color = Column(String(7), nullable=True)  # Hex color, default white
    title_size = Column(String(10), nullable=True)  # e.g. "4rem", "3rem"
    content_size = Column(String(10), nullable=True)  # e.g. "2rem", "1.5rem"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_type = Column(SAEnum(ContentType), nullable=False)
    content_id = Column(Integer, nullable=False)  # References media.id, announcement.id, or folder.id
    position = Column(Integer, nullable=False)  # Order in playlist
    active = Column(Boolean, default=True)
    duration = Column(Integer, nullable=True)  # Override duration in seconds (null = use default)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DisplaySettings(Base):
    __tablename__ = "display_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=False)


class StoredFile(Base):
    __tablename__ = "stored_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    folder = Column(String(500), nullable=False, default="/")  # Virtual folder path
    uploaded_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Folder(Base):
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    music_filename = Column(String(255), nullable=True)
    music_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class FolderItem(Base):
    __tablename__ = "folder_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    folder_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    media_type = Column(SAEnum(MediaType), nullable=False)  # image or video
    file_path = Column(String(500), nullable=False)
    thumbnail_path = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
