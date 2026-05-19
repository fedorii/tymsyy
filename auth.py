import os
import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import Request
from sqlalchemy.orm import Session

SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed:str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except Exception:
        return None
    

async def get_current_user_from_cookie(request: Request, db: Session = None):
    token = request.cookies.get("token")
    if not token:
        return None
    user_id = decode_token(token)
    if not user_id:
        return None
    if db is None:
        from database import SessionLocal
        import crud
        db = SessionLocal()
        user = crud.get_user(db, user_id)
        db.close()
        return user
    import crud
    return crud.get_user(db, user_id)