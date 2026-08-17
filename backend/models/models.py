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
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_type = Column(SAEnum(ContentType), nullable=False)
    content_id = Column(Integer, nullable=False)  # References media.id, announcement.id, or sponsor.id
    position = Column(Integer, nullable=False)  # Order in playlist
    active = Column(Boolean, default=True)
    duration = Column(Integer, nullable=True)  # Override duration in seconds (null = use default)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
