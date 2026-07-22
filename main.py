from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict
import jwt
import math
import requests
from uuid import UUID

from models_and_auth import SessionLocal, Hospital, User, Driver, verify_password, create_access_token, SECRET_KEY, ALGORITHM

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def serve_index():
    return FileResponse("index.html")

@app.get("/patient")
def serve_patient():
    return FileResponse("patient.html")

@app.get("/driver")
def serve_driver():
    return FileResponse("driver.html")

@app.get("/hospital_dashboard")
def serve_hospital_dashboard():
    return FileResponse("hospital_dashboard.html")

@app.get("/command_center")
def serve_command_center():
    return FileResponse("command_center.html")

@app.get("/tracking_dashboard")
def serve_tracking():
    return FileResponse("tracking_dashboard.html")


# SECURITY & DATABASE SETUP 
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# SCHEMAS FROM HERE
class BedUpdate(BaseModel):
    icu_beds: int

class RouteRequest(BaseModel):
    driver_id: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

class DriverStatusUpdate(BaseModel):
    is_online: bool

class Location(BaseModel):
    latitude: float
    longitude: float

class AmbulanceRequest(BaseModel):
    user_id: str
    pickup_location: Location
    fleet_preference: str


# REST API ENDPOINTS

@app.post("/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/hospitals")
def get_hospitals(db: Session = Depends(get_db)):
    hospitals = db.query(Hospital).all()
    result = []
    now = datetime.utcnow()
    
    for h in hospitals:
        is_verified = False
        if h.last_updated and (now - h.last_updated) <= timedelta(hours=4):
            is_verified = True
            
        result.append({
            "id": h.id,
            "name": h.name,
            "icu_beds_available": h.icu_beds_available,
            "general_beds_available": h.general_beds_available,
            "is_verified": is_verified
        })
    return result

@app.patch("/api/hospitals/{hospital_id}/beds")
def update_beds(hospital_id: int, update: BedUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if hospital:
        hospital.icu_beds_available = update.icu_beds
        
        hospital.last_updated = datetime.utcnow() 
        db.commit()
        
        return {"status": "success", "new_count": hospital.icu_beds_available, "updated_by": current_user.username}
    return {"status": "error", "message": "Hospital not found"}


@app.patch("/api/drivers/{driver_id}/status")
def update_driver_status(driver_id: str, update: DriverStatusUpdate, db: Session = Depends(get_db)):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    
    if not driver:
        driver = Driver(id=driver_id, name="Test Driver", is_online=update.is_online)
        db.add(driver)
    else:
        driver.is_online = update.is_online
        
    db.commit()
    
    status_text = "Online" if driver.is_online else "Offline"
    return {"message": f"Driver {driver_id} is now {status_text}!"}

@app.post("/api/book-ambulance")
def book_ambulance(request: AmbulanceRequest, db: Session = Depends(get_db)):
    available_driver = db.query(Driver).filter(Driver.is_online == True).first()
    
    if available_driver:
        MAKE_WEBHOOK_URL = "https://hook.eu1.make.com/koqj8j2uxwffv9t548estigtgdyeak1k"
        booking_payload = {
            "user_id": request.user_id,
            "driver_id": available_driver.id,
            "driver_name": available_driver.name
        }
        requests.post(MAKE_WEBHOOK_URL, json=booking_payload)
        
        return {
            "status": "success",
            "message": f"Ambulance Dispatched! Driver {available_driver.name} ({available_driver.id}) is en route."
        }
    else:
        return {
            "status": "error",
            "detail": "No ambulances are currently online. Please try again in a moment."
        }


# GREEN CORRIDOR
POLICE_JUNCTIONS = [
    {"id": "P1", "name": "North Highway", "lat": 50, "lon": 20}, # Updated to 0-100 scale
    {"id": "P2", "name": "East Crossroad", "lat": 80, "lon": 50},
    {"id": "P3", "name": "South Bridge", "lat": 50, "lon": 80},
    {"id": "P4", "name": "West Market", "lat": 20, "lon": 50},
]

# Math for the 0-100 grid simulation
def point_to_line_distance(px, py, x1, y1, x2, y2):
    line_len = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    if line_len == 0:
        return math.sqrt((px - x1)**2 + (py - y1)**2)
    
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / (line_len**2)))
    
    proj_x = x1 + t * (x2 - x1)
    proj_y = y1 + t * (y2 - y1)
    
    return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)


class EmergencyRoomManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}
        self.room_authorizations: Dict[str, List[str]] = {}

    def setup_emergency_room(self, driver_id: str, police_ids: List[str]):
        """Creates a private tracking room when an ambulance is dispatched."""
        room_id = f"ROOM_{driver_id}"
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.room_authorizations[room_id] = police_ids
        return room_id

    async def connect(self, websocket: WebSocket, room_id: str):
        """Joins a specific emergency room."""
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.rooms and websocket in self.rooms[room_id]:
            self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, data: dict):
        """Sends GPS data ONLY to the people in this specific room."""
        if room_id in self.rooms:
            for connection in self.rooms[room_id]:
                try:
                    await connection.send_json(data)
                except Exception:
                    pass

room_manager = EmergencyRoomManager()

@app.post("/api/green-corridor")
def activate_green_corridor(route: RouteRequest):
    ALERT_THRESHOLD = 15.0 # Distance threshold on your 0-100 grid
    alerted_police = []
    
    for police in POLICE_JUNCTIONS:
        # Check distance from police station to the ROUTE segment
        dist = point_to_line_distance(
            police["lat"], police["lon"], 
            route.start_lat, route.start_lon, 
            route.end_lat, route.end_lon
        )
        
        if dist <= ALERT_THRESHOLD:
            alerted_police.append(police["id"])

    room_id = room_manager.setup_emergency_room(route.driver_id, alerted_police)
            
    return {
        "status": "Green Corridor Activated", 
        "room_id": f"ROOM_{route.driver_id}",
        "alerted_junctions": alerted_police
    }

@app.websocket("/ws/driver/{room_id}")
async def driver_broadcast(websocket: WebSocket, room_id: str):
    await room_manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_json()
            await room_manager.broadcast(room_id, data)
    except WebSocketDisconnect:
        room_manager.disconnect(websocket, room_id)

@app.websocket("/ws/listen/{room_id}")
async def police_listen(websocket: WebSocket, room_id: str):
    await room_manager.connect(websocket, room_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        room_manager.disconnect(websocket, room_id)


class ConnectionManager:
    def __init__(self):
        self.active_listeners: Dict[str, List[WebSocket]] = {}

    async def connect_listener(self, websocket: WebSocket, driver_id: str):
        await websocket.accept()
        if driver_id not in self.active_listeners:
            self.active_listeners[driver_id] = []
        self.active_listeners[driver_id].append(websocket)

    def disconnect_listener(self, websocket: WebSocket, driver_id: str):
        if driver_id in self.active_listeners:
            self.active_listeners[driver_id].remove(websocket)
            if len(self.active_listeners[driver_id]) == 0:
                del self.active_listeners[driver_id]

    async def broadcast_location(self, driver_id: str, location_data: dict):
        if driver_id in self.active_listeners:
            for connection in self.active_listeners[driver_id]:
                try:
                    await connection.send_json(location_data)
                except Exception:
                    pass

manager = ConnectionManager()

@app.websocket("/ws/driver/{driver_id}")
async def driver_location_updater(websocket: WebSocket, driver_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            await manager.broadcast_location(driver_id, data)
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/listen/{driver_id}")
async def listen_to_driver(websocket: WebSocket, driver_id: str):
    await manager.connect_listener(websocket, driver_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_listener(websocket, driver_id)
