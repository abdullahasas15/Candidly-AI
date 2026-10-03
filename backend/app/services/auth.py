import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.models import User

# Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "candidly_ai_enterprise_super_secret_jwt_key_2026")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7-day token for seamless user experience
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash, with legacy fallback."""
    if not hashed_password or not plain_password:
        return False
    try:
        # Check standard bcrypt
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        # Fallback for plain comparison if any legacy dev passwords exist
        return plain_password == hashed_password


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token containing subject and user claims."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    
    to_encode.update({
        "exp": expire,
        "iat": now
    })
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please sign in again."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token."
        )


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency to extract and verify current authenticated User."""
    extracted_token = None
    if authorization and authorization.startswith("Bearer "):
        extracted_token = authorization.split(" ")[1]
    elif token:
        extracted_token = token

    if not extracted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Bearer token."
        )

    payload = decode_access_token(extracted_token)
    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims: missing subject."
        )

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token no longer exists."
        )

    return user


async def get_optional_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """FastAPI dependency returning the current User or None if unauthenticated."""
    try:
        return await get_current_user(authorization=authorization, token=token, db=db)
    except HTTPException:
        return None


def require_role(required_role: str):
    """Dependency factory enforcing role-based access control ('recruiter' | 'candidate')."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != required_role.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {required_role.capitalize()} privileges required."
            )
        return current_user
    return role_checker

