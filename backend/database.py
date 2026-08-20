import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.models.models import Base, Admin
from backend.config import settings
from backend.migrations import run_migration_sync
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Ensure data directory exists
os.makedirs(os.path.dirname(settings.DATABASE_PATH), exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{settings.DATABASE_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Dependency that provides a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Run migrations, create tables, and seed defaults."""

    # Step 1: Run migrations (synchronous, before async engine touches the DB)
    run_migration_sync(settings.DATABASE_PATH)

    # Step 2: Create any new tables (safe to run - skips existing tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Step 3: Seed defaults
    async with async_session() as session:
        from sqlalchemy import select, func
        from backend.models.models import Playlist, Screen

        # Seed default admin user if no admins exist
        result = await session.execute(select(func.count(Admin.id)))
        count = result.scalar()

        if count == 0:
            default_admin = Admin(
                username=settings.ADMIN_USERNAME,
                password_hash=pwd_context.hash(settings.ADMIN_PASSWORD),
            )
            session.add(default_admin)

        # Seed default playlist if none exists
        result = await session.execute(select(func.count(Playlist.id)))
        if result.scalar() == 0:
            default_playlist = Playlist(name="Main Playlist")
            session.add(default_playlist)
            await session.flush()

            # Seed default "main" screen
            main_screen = Screen(
                name="Main Screen",
                slug="main",
                playlist_id=default_playlist.id,
                orientation="vertical",
                rotation="90",
            )
            session.add(main_screen)

        # Ensure "main" screen exists (for upgrades)
        result = await session.execute(select(Screen).where(Screen.slug == "main"))
        if not result.scalar_one_or_none():
            # Get first playlist or create one
            pl_result = await session.execute(select(Playlist).order_by(Playlist.id))
            playlist = pl_result.scalars().first()
            if not playlist:
                playlist = Playlist(name="Main Playlist")
                session.add(playlist)
                await session.flush()

            main_screen = Screen(
                name="Main Screen",
                slug="main",
                playlist_id=playlist.id,
                orientation="vertical",
                rotation="90",
            )
            session.add(main_screen)

        await session.commit()
