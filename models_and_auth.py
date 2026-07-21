from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext

# 1. DATABASE SETUP
DATABASE_URL = "sqlite:///./emergency_hub.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. SECURITY SETUP
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "SUPER_SECRET_KEY_CHANGE_ME"
ALGORITHM = "HS256"

# 3. MODELS
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String) # "HOSPITAL_ADMIN", "POLICE", "DRIVER"

class Hospital(Base):
    __tablename__ = "hospitals"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    icu_beds_available = Column(Integer, default=0)
    general_beds_available = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)


class Driver(Base):
    __tablename__ = "drivers"
    id = Column(String, primary_key=True, index=True) # Using String because your HTML uses "D1"
    name = Column(String)
    is_online = Column(Boolean, default=False)


def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=60)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Initialize tables
Base.metadata.create_all(bind=engine)