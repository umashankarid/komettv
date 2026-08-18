from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.models import DisplaySettings
from backend.api.auth import get_current_admin, Admin

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Default settings
DEFAULTS = {
    "orientation": "vertical",  # "vertical" or "horizontal"
    "rotation": "90",  # 0, 90, 180, 270 degrees
}


# --- Schemas ---

class SettingUpdate(BaseModel):
    value: str


class SettingsOut(BaseModel):
    orientation: str
    rotation: str


# --- Routes ---

@router.get("", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns display settings for the player."""
    result = await db.execute(select(DisplaySettings))
    settings_rows = result.scalars().all()

    settings_dict = {s.key: s.value for s in settings_rows}

    return SettingsOut(
        orientation=settings_dict.get("orientation", DEFAULTS["orientation"]),
        rotation=settings_dict.get("rotation", DEFAULTS["rotation"]),
    )


@router.put("/{key}")
async def update_setting(
    key: str,
    data: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    if key not in DEFAULTS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")

    result = await db.execute(select(DisplaySettings).where(DisplaySettings.key == key))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = data.value
        db.add(setting)
    else:
        new_setting = DisplaySettings(key=key, value=data.value)
        db.add(new_setting)

    return {"key": key, "value": data.value}
