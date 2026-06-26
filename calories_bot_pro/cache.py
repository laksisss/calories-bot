import hashlib
import json
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from models import Base
from sqlalchemy import Column, String, DateTime
from config import CACHE_TTL

class Cache(Base):
    __tablename__ = "cache"
    key = Column(String, primary_key=True)
    value = Column(String)
    expires_at = Column(DateTime)

async def get_cached_result(session: AsyncSession, key: str):
    result = await session.execute(select(Cache).where(Cache.key == key))
    cache_entry = result.scalar_one_or_none()
    if cache_entry and cache_entry.expires_at > datetime.utcnow():
        return json.loads(cache_entry.value)
    return None

async def set_cached_result(session: AsyncSession, key: str, value: dict):
    expires_at = datetime.utcnow() + timedelta(seconds=CACHE_TTL)
    await session.execute(delete(Cache).where(Cache.key == key))
    cache_entry = Cache(key=key, value=json.dumps(value), expires_at=expires_at)
    session.add(cache_entry)
    await session.commit()

def get_image_hash(image_bytes: bytes) -> str:
    return hashlib.md5(image_bytes).hexdigest()

def get_text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()
