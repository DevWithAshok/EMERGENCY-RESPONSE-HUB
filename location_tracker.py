from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import math
from typing import Dict, List
import uvicorn
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_listeners: Dict[str, List[WebSocket]] = {}

    async def connect_listener(self, websocket: WebSocket, driver_id: str):
        """Accepts a connection from a user or police officer wanting to track a specific driver."""
        await websocket.accept()
        if driver_id not in self.active_listeners:
            self.active_listeners[driver_id] = []
        self.active_listeners[driver_id].append(websocket)
        print(f"New listener connected to Driver {driver_id}")

    def disconnect_listener(self, websocket: WebSocket, driver_id: str):
        """Removes a listener when they close the app."""
        if driver_id in self.active_listeners:
            self.active_listeners[driver_id].remove(websocket)
            if len(self.active_listeners[driver_id]) == 0:
                del self.active_listeners[driver_id]

    async def broadcast_location(self, driver_id: str, location_data: dict):
        """Pushes the driver's latest GPS coordinates to all active listeners instantly."""
        if driver_id in self.active_listeners:
            for connection in self.active_listeners[driver_id]:
                try:
                    await connection.send_json(location_data)
                except Exception as e:
                    print(f"Failed to send data to a listener: {e}")

manager = ConnectionManager()

# GREEN CORRIDOR: GEOSPATIAL LOGIC

POLICE_JUNCTIONS = [
    {"id": "P1", "name": "North Highway", "lat": 20, "lon": 50},
    {"id": "P2", "name": "East Crossroad", "lat": 50, "lon": 80},
    {"id": "P3", "name": "South Bridge", "lat": 80, "lon": 50},
    {"id": "P4", "name": "West Market", "lat": 50, "lon": 20},
]

class RouteRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

def point_to_segment_distance(px, py, x1, y1, x2, y2):
    """Calculates the shortest distance from a point to a line segment."""
    line_mag = math.hypot(x2 - x1, y2 - y1)
    if line_mag == 0:
        return math.hypot(px - x1, py - y1) # Start and End are the same
    
    u = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / (line_mag ** 2)
    
    # segment boundaries (0 to 1)
    if u < 0 or u > 1:
        ix = x1 if u < 0 else x2
        iy = y1 if u < 0 else y2
    else:
        ix = x1 + u * (x2 - x1)
        iy = y1 + u * (y2 - y1)
        
    return math.hypot(px - ix, py - iy)

@app.post("/api/green-corridor")
async def activate_green_corridor(route: RouteRequest):
    """
    Finds which police junctions are within the threshold distance of the route.
    """
    ALERT_THRESHOLD = 20.0 
    alerted_police = []

    for police in POLICE_JUNCTIONS:
        distance = point_to_segment_distance(
            police["lat"], police["lon"],
            route.start_lat, route.start_lon,
            route.end_lat, route.end_lon
        )
        
        if distance <= ALERT_THRESHOLD:
            alerted_police.append(police["id"])
            print(f"🚨 ALERTING: {police['name']} (Distance: {distance:.1f})")

    return {
        "status": "Green Corridor Activated",
        "alerted_junctions": alerted_police
    }

@app.websocket("/ws/driver/{driver_id}")
async def driver_location_updater(websocket: WebSocket, driver_id: str):
    """
    The driver's app connects here and constantly sends JSON with lat/lon.
    """
    await websocket.accept()
    print(f"Driver {driver_id} is now broadcasting location.")
    try:
        while True:
            data = await websocket.receive_json()
            
            await manager.broadcast_location(driver_id, data)
            
    except WebSocketDisconnect:
        print(f"Driver {driver_id} went offline or lost connection.")

@app.websocket("/ws/listen/{driver_id}")
async def listen_to_driver(websocket: WebSocket, driver_id: str):
    """
    The User app or Police dashboard connects here to receive live updates.
    """
    await manager.connect_listener(websocket, driver_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_listener(websocket, driver_id)
        print(f"A listener disconnected from Driver {driver_id}")

