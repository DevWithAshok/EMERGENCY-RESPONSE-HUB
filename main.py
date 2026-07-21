from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
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

@app.get("/hospital-dashboard")
def serve_hospital_dashboard():
    return FileResponse("hospital_dashboard.html")

@app.get("/command-center")
def serve_command_center():
    return FileResponse("command_center.html")

@app.get("/tracking")
def serve_tracking():
    return FileResponse("tracking_dashboard.html")


# SECURITY & DATABASE SETUP WILL BE STARTED
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
        import requests
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

def grid_distance(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2)

@app.post("/api/green-corridor")
def activate_green_corridor(route: RouteRequest):
    
    ALERT_THRESHOLD = 15.0 
    alerted_police = []
    
    for police in POLICE_JUNCTIONS:
        distance = grid_distance(police["lat"], police["lon"], route.end_lat, route.end_lon)
        if distance <= ALERT_THRESHOLD:
            alerted_police.append(police["id"])

    room_id = room_manager.setup_emergency_room(route.driver_id, alerted_police)
            
    return {
        "status": "Green Corridor Activated", 
        "room_id": f"ROOM_{route.driver_id}",
        "alerted_junctions": alerted_police,
        "route_geometry": [] # OSRM path won't work on 0-100 scale
    }

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
    url = f"http://router.project-osrm.org/route/v1/driving/{route.start_lon},{route.start_lat};{route.end_lon},{route.end_lat}?geometries=geojson"
    
    try:
        response = requests.get(url).json()
        if "routes" not in response or len(response["routes"]) == 0:
            return {"status": "error", "message": "Could not calculate road route."}
        road_points = response["routes"][0]["geometry"]["coordinates"]
    except Exception as e:
        return {"status": "error", "message": "Failed to connect to Maps API."}

    ALERT_THRESHOLD_KM = 0.5
    alerted_police = []
    
    for police in POLICE_JUNCTIONS:
        for point in road_points:
            path_lon, path_lat = point
            distance = haversine_distance(police["lat"], police["lon"], path_lat, path_lon)
            if distance <= ALERT_THRESHOLD_KM:
                alerted_police.append(police["id"])
                break 

    room_id = room_manager.setup_emergency_room(route.driver_id, alerted_police)
            
    return {
        "status": "Green Corridor Activated", 
        "room_id": f"ROOM_{route.driver_id}",
        "alerted_junctions": alerted_police,
        "route_geometry": road_points
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
