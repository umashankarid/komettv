from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db, pwd_context
from backend.models.models import Admin

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# --- Schemas ---

class Token(BaseModel):
    access_token: str
    token_type: str


class AdminOut(BaseModel):
    id: int
    username: str
    created_at: datetime


class AdminCreate(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# --- Helpers ---

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_admin(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(Admin).where(Admin.username == username))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise credentials_exception
    return admin


# --- Routes ---

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Admin).where(Admin.username == form_data.username))
    admin = result.scalar_one_or_none()

    if not admin or not pwd_context.verify(form_data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": admin.username})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if not pwd_context.verify(data.current_password, current_admin.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_admin.password_hash = pwd_context.hash(data.new_password)
    db.add(current_admin)
    return {"message": "Password changed successfully"}


@router.get("/admins", response_model=list[AdminOut])
async def list_admins(
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Admin))
    admins = result.scalars().all()
    return admins


@router.post("/admins", response_model=AdminOut, status_code=201)
async def create_admin(
    data: AdminCreate,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # Check if username already exists
    result = await db.execute(select(Admin).where(Admin.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    new_admin = Admin(
        username=data.username,
        password_hash=pwd_context.hash(data.password),
    )
    db.add(new_admin)
    await db.flush()
    await db.refresh(new_admin)
    return new_admin


@router.delete("/admins/{admin_id}")
async def delete_admin(
    admin_id: int,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if current_admin.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    await db.delete(admin)
    return {"message": "Admin deleted"}
