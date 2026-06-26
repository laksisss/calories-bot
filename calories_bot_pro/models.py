from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String)
    first_name = Column(String)
    is_pro = Column(Boolean, default=False)
    daily_requests = Column(Integer, default=0)
    last_request_date = Column(String)
    streak = Column(Integer, default=0)
    last_activity_date = Column(String)
    created_at = Column(DateTime, server_default=func.now())

class Goal(Base):
    __tablename__ = "goals"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    calories = Column(Float, default=2000)
    protein = Column(Float, default=100)
    fat = Column(Float, default=70)
    carbs = Column(Float, default=250)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class Meal(Base):
    __tablename__ = "meals"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    date = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    weight = Column(Float)
    calories = Column(Float)
    protein = Column(Float)
    fat = Column(Float)
    carbs = Column(Float)
    meal_type = Column(String)
    created_at = Column(DateTime, server_default=func.now())

class Achievement(Base):
    __tablename__ = "achievements"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    achievement_type = Column(String, nullable=False)
    unlocked_at = Column(DateTime, server_default=func.now())
