import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from backend.models.models import Base, Admin
from backend.config import settings
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
    """Create all tables and run migrations, then seed default admin if none exists."""
    async with engine.begin() as conn:
        # Create any new tables that don't exist yet
        await conn.run_sync(Base.metadata.create_all)

    # Run column migrations
    await run_migrations()

    # Seed default admin user if no admins exist
    async with async_session() as session:
        from sqlalchemy import select, func

        result = await session.execute(select(func.count(Admin.id)))
        count = result.scalar()

        if count == 0:
            default_admin = Admin(
                username=settings.ADMIN_USERNAME,
                password_hash=pwd_context.hash(settings.ADMIN_PASSWORD),
            )
            session.add(default_admin)
            await session.commit()


async def run_migrations():
    """Apply column migrations without losing data.
    
    Each migration checks if the column/table exists before applying.
    This is safe to run on every startup.
    """
    migrations = [
        # Add background_color to announcements
        {
            "table": "announcements",
            "column": "background_color",
            "sql": "ALTER TABLE announcements ADD COLUMN background_color VARCHAR(7)",
        },
        # Add display_settings table columns (table created by create_all, but in case of schema changes)
    ]

    async with engine.begin() as conn:
        for migration in migrations:
            # Check if column already exists
            exists = await conn.execute(
                text(f"SELECT COUNT(*) FROM pragma_table_info('{migration['table']}') WHERE name='{migration['column']}'")
            )
            if exists.scalar() == 0:
                try:
                    await conn.execute(text(migration["sql"]))
                    print(f"Migration: Added {migration['table']}.{migration['column']}")
                except Exception as e:
                    print(f"Migration skipped ({migration['table']}.{migration['column']}): {e}")
