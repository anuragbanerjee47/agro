import cv2
import numpy as np
import sqlite3
import csv
import io
import os
import logging
import random
import string
from datetime import datetime
from typing import List, Dict, Optional, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutrient-monitor")

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "agronode_history.db")

# --- Database Initialization ---
def init_db():
    logger.info(f"Initializing AgroNode v4.2 Enterprise DB at {DB_PATH}...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Telemetry Log Table (Expanded to 14 nutrients)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    device_id TEXT,
                    crop_profile TEXT,
                    nitrogen REAL, phosphorus REAL, potassium REAL,
                    calcium REAL, magnesium REAL, sulfur REAL,
                    zinc REAL, iron REAL, boron REAL, manganese REAL,
                    copper REAL, molybdenum REAL, chlorine REAL, nickel REAL,
                    ph REAL, moisture REAL, canopy_temp REAL, ambient_temp REAL,
                    pest_detected BOOLEAN, nematode_detected BOOLEAN,
                    alerts TEXT
                )
            """)

            # User/Farmer Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_id TEXT UNIQUE NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    active_crop TEXT,
                    crop_group TEXT,
                    created_at TEXT
                )
            """)

            # Neighbor Connection Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS neighbor_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requestor_id INTEGER,
                    target_id INTEGER,
                    status TEXT,
                    created_at TEXT,
                    FOREIGN KEY(requestor_id) REFERENCES users(id),
                    FOREIGN KEY(target_id) REFERENCES users(id)
                )
            """)

            # Neighbor Share Codes Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS neighbor_codes (
                    code TEXT PRIMARY KEY,
                    user_id INTEGER,
                    created_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)
            conn.commit()
            logger.info("Enterprise Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AgroNode v4.2 Intelligence Platform", lifespan=lifespan)

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- State Management ---
class SystemState:
    def __init__(self):
        self.active_profile = "group1"
        self.device_id = "ESP32_FIELD_NODE_01"
        # Expanded state for 14 nutrients
        self.latest_telemetry = {
            "nitrogen": 120.0, "phosphorus": 45.0, "potassium": 150.0,
            "ca": 1420.0, "mg": 240.5, "s": 22.4,
            "zinc": 1.5, "iron": 2.0, "boron": 0.5, "manganese": 1.0,
            "copper": 0.2, "molybdenum": 0.1, "chlorine": 0.5, "nickel": 0.05,
            "ph": 6.8, "moisture": 35.0, "canopy_temp": 24.0, "ambient_temp": 23.0,
            "pest_detected": False, "nematode_detected": False
        }
        self.latest_analysis = {"nitrate": 0.0, "phosphate": 0.0, "zinc": 0.0}
        self.active_alerts = []

state = SystemState()

# --- Data Models ---
class TelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    device_id: str = "ESP32_FIELD_NODE_01"
    timestamp: Optional[str] = None
    status: Optional[str] = "online"
    telemetry: Optional[Dict[str, Any]] = None
    ca: Optional[float] = None
    mg: Optional[float] = None
    s: Optional[float] = None

# --- Remedy Dataset ---
REMEDY_DATA = {
    "Nitrogen": {
        "Govt Available Additives": "Urea (46% N, ~₹266/45kg bag at PACS/RSK/IFFCO); Nano Urea Liquid (500 mL, ~₹225-240)",
        "Homemade Remedy": "Jeevamrut (10 kg cow dung, 10 L cow urine, 2 kg jaggery, 2 kg pulse flour in 200 L water; ferment 48-72 hrs in shade)",
        "Emergency Action": "Foliar spray 2% conventional urea solution (2 kg in 100 L water/acre)"
    },
    "Phosphorus": {
        "Govt Available Additives": "DAP (18:46:0, ~₹1,350/50kg); SSP (16% P2O5, ~₹350-400/50kg); Nano DAP (500 mL, ~₹600)",
        "Homemade Remedy": "Bone Meal or Charred Bone Dust (20-30% P2O5; apply 20-25 kg/acre near root zone)",
        "Emergency Action": "Foliar spray 1% MAP (12:61:0; 1 kg in 100 L water/acre) or 2-4 mL Nano DAP per liter"
    },
    "Potassium": {
        "Govt Available Additives": "MOP (Muriate of Potash, 60% K2O; 20-30 kg/acre); 0:0:50 Potassium Sulfate (~₹100-150/kg)",
        "Homemade Remedy": "Wood/Chulha Ash (10-15 kg/acre before irrigation) or Banana Peel Extract (15-20 peels steeped in 10 L water for 3 days, diluted in 20 L water)",
        "Emergency Action": "1% 13:0:45 (Potassium Nitrate) foliar spray (1 kg in 100 L water/acre) or decanted Wood Ash Water spray"
    },
    "Calcium": {
        "Govt Available Additives": "Gypsum (CaSO4·2H2O; 100-200 kg/acre, ~₹100-200/50kg); Calcium Nitrate (1 kg, ~₹120-180)",
        "Homemade Remedy": "Edible Slaked Lime / Chuna (1 kg in 10 L water overnight, decanted and diluted into 200 L water); Eggshell Powder (2-3 kg/acre)",
        "Emergency Action": "Foliar spray 0.5% Calcium Nitrate (500 g in 100 L water/acre) or Vinegar-Eggshell extract (100 g eggshells in 1 L white vinegar for 7-10 days, dilute 200 mL in 100 L water)"
    },
    "Magnesium": {
        "Govt Available Additives": "Magnesium Sulfate / Epsom Salt (10-15 kg/acre, ~₹30-50/kg); Dolomite Limestone Dust (20-25 kg/acre)",
        "Homemade Remedy": "Household Epsom Salt drench (2 kg in 100 L water/acre around root zone)",
        "Emergency Action": "1% Magnesium Sulfate spray (1 kg in 100 L water/acre) or Epsom (500 g) + Urea (500 g) in 100 L water/acre for rapid greening"
    },
    "Sulfur": {
        "Govt Available Additives": "Elemental Sulfur (80%/90% WDG; 10-15 kg/acre, ~₹80-120/kg); SSP (contains 11% S; 50-75 kg/acre)",
        "Homemade Remedy": "Onion & Garlic Waste Extract (5 kg peels steeped in 20 L water for 4 days) or Mustard Cake (10 kg in 50 L water for 3-5 days, dilute into 200 L)",
        "Emergency Action": "Foliar spray 0.5% Liquid Sulfur (40%/80% SC) or Ammonium Sulfate (500 g in 100 L water)"
    },
    "Zinc": {
        "Govt Available Additives": "Zinc Sulfate Heptahydrate 21% (10-12 kg/acre, ~₹50-70/kg); Zinc Sulfate Monohydrate 33% (6-8 kg/acre); Zinc EDTA 12%",
        "Homemade Remedy": "Galvanized iron scrap soak in 20 L water with 1 L sour buttermilk (10-14 days) or Compost-enriched Zinc dust (2 kg ZnSO4 in 50 kg FYM under shade for 7 days)",
        "Emergency Action": "Foliar spray 500 g Zinc Sulfate (21%) + 250 g Agricultural Lime (Chuna) in 100 L water/acre, or 100-150 g Zinc EDTA (12%) in 100 L water"
    },
    "Iron": {
        "Govt Available Additives": "Ferrous Sulfate (FeSO4 19%; ~₹30-50/kg); Chelated Iron (Fe-EDTA 12% / Fe-EDDHA 6% for alkaline soils, ~₹150-300)",
        "Homemade Remedy": "Iron scrap + Jaggery water (2-3 kg clean rusted iron nails in 10 L water with 1 kg Jaggery, fermented 10-14 days until reddish-brown) or Sour Buttermilk iron extract",
        "Emergency Action": "Foliar spray 1 kg FeSO4 + 100 g Citric Acid (or 250 g Lime) in 100 L water/acre, or 100-150 g Fe-EDTA in 100 L water"
    },
    "Boron": {
        "Govt Available Additives": "Borax 10.5% (2-3 kg/acre, ~₹80-120/kg); Solubor / Disodium Octaborate Tetrahydrate 20% (~₹150-250)",
        "Homemade Remedy": "Wood Ash (15-20 kg) + Cow Dung Compost (100 kg); or Household Borax powder (1 kg in 50 kg compost)",
        "Emergency Action": "0.2% Solubor or Borax spray (200 g in 100 L water/acre) or Borax (150 g) + Jaggery (200 g) foliar spray before flowering"
    },
    "Manganese": {
        "Govt Available Additives": "Manganese Sulfate (MnSO4 30.5%; 8-10 kg/acre, ~₹60-90/kg); Mn-EDTA 12%",
        "Homemade Remedy": "Compost + Wood/Stem Ash Tea (10 kg ash in 50 kg FYM kept moist for 5 days) or Decayed Leaf Mold drench (20 kg leaf mold in 100 L water with 1 kg Jaggery)",
        "Emergency Action": "Foliar spray 500 g MnSO4 + 250 g Agricultural Lime in 100 L water/acre, or 100-150 g Mn-EDTA (12%) in 100 L water"
    },
    "Copper": {
        "Govt Available Additives": "Copper Sulfate / Blue Vitriol (Neela Thotha 24% Cu; ~₹150-220/kg); Cu-EDTA 12%",
        "Homemade Remedy": "Copper pot fermented sour buttermilk (5 L buttermilk with copper sheets for 10-14 days until bluish-green; dilute into 200 L water) or Wood Ash + Copper scrap tea",
        "Emergency Action": "Bordeaux Mixture spray (500 g Copper Sulfate + 500 g Lime in 100 L water/acre) or Organic Copper buttermilk spray (2 L fermented solution in 100 L water)"
    },
    "Molybdenum": {
        "Govt Available Additives": "Sodium Molybdate 52% or Ammonium Molybdate 54% (50-100 g/acre, ~₹150-250/100g); State Micronutrient Mixtures",
        "Homemade Remedy": "Wood ash (10-15 kg) + FYM (100 kg); or Slaked Lime (100-150 kg/acre to increase pH and unlock native Mo)",
        "Emergency Action": "0.03%-0.05% foliar spray (30-50 g Sodium Molybdate in 100 L water/acre) or Ash Water + Jaggery extract spray"
    },
    "Chlorine": {
        "Govt Available Additives": "Muriate of Potash / MOP (5-10 kg/acre, ~₹1,700/50kg); Ammonium Chloride (25% N, 66% Cl)",
        "Homemade Remedy": "Common Rock Salt / Sea Salt (200-250 g non-iodized salt in 100 L water/acre) or regular borewell/well water irrigation",
        "Emergency Action": "Foliar spray 0.1% MOP (100-150 g in 100 L water/acre) or Rock Salt (50 g) + Jaggery (100 g) in 100 L water"
    },
    "Nickel": {
        "Govt Available Additives": "Nickel Sulfate (NiSO4·6H2O; 20-50 g/acre, ~₹150-250/100g); City Compost (e.g., Bharat Compost)",
        "Homemade Remedy": "Mustard cake (10 kg) + cattle dung slurry; or Pond Silt / Talab Ki Mitti (100-200 kg/acre)",
        "Emergency Action": "Extremely low-dose spray (5-10 g Nickel Sulfate in 100 L water/acre, 0.005%-0.01%) or Fermented Mustard Cake extract (1 L) + Urea (500 g) in 100 L water"
    }
}

# --- Identity & Session Helpers ---
def generate_farmer_id():
    year = datetime.now().year
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"AGRO-FARMER-{random_part}-{year}"

def get_current_user(token: Optional[str]):
    if not token: return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            res = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
            return dict(res) if res else None
    except Exception:
        return None

def save_reading(device_id: str):
    tel = state.latest_telemetry
    ana = state.latest_analysis

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO telemetry_logs
                (timestamp, device_id, crop_profile, nitrogen, phosphorus, potassium,
                 calcium, magnesium, sulfur, zinc, iron, boron, manganese,
                 copper, molybdenum, chlorine, nickel, ph, moisture,
                 canopy_temp, ambient_temp, pest_detected, nematode_detected, alerts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                device_id,
                state.active_profile,
                tel.get("nitrogen", 0.0), tel.get("phosphorus", 0.0), tel.get("potassium", 0.0),
                tel.get("ca", 0.0), tel.get("mg", 0.0), tel.get("s", 0.0),
                tel.get("zinc", 0.0), tel.get("iron", 0.0), tel.get("boron", 0.0), tel.get("manganese", 0.0),
                tel.get("copper", 0.0), tel.get("molybdenum", 0.0), tel.get("chlorine", 0.0), tel.get("nickel", 0.0),
                tel.get("ph", 7.0), tel.get("moisture", 0.0),
                tel.get("canopy_temp", 25.0), tel.get("ambient_temp", 25.0),
                tel.get("pest_detected", False), tel.get("nematode_detected", False),
                " | ".join(state.active_alerts)
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Database write failed: {e}")

# --- Image Analysis Pipeline ---
def analyze_colorimetric_image(image_bytes: bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")

    h, w, _ = img.shape
    cy, cx = h // 2, w // 2
    rh, rw = int(h * 0.4), int(w * 0.4)
    roi = img[cy - rh//2 : cy + rh//2, cx - rw//2 : cx + rw//2]
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2Lab)
    avg_l, avg_a, avg_b = cv2.mean(lab)[:3]

    nitrate = np.clip((avg_a / 128.0) * 180.0, 0, 180)
    phosphate = np.clip((avg_b / 128.0) * 60.0, 0, 60)
    zinc = np.clip(((avg_l + avg_a) / 255.0) * 4.5, 0, 4.5)

    return {
        "nitrate": round(float(nitrate), 2),
        "phosphate": round(float(phosphate), 2),
        "zinc": round(float(zinc), 2)
    }

# --- Fusion & Disease Rules Engine ---
def evaluate_rules(telemetry: Dict[str, Any], analysis: Dict[str, float], profile: str):
    alerts = []
    ph = telemetry.get("ph", 7.0)
    moisture = telemetry.get("moisture", 50.0)
    canopy_temp = telemetry.get("canopy_temp", 25.0)
    ambient_temp = telemetry.get("ambient_temp", 25.0)
    stem_piezo = telemetry.get("stem_piezo", 50.0)
    soil_npk = telemetry.get("soil_npk", [0, 0, 0])
    k_val = soil_npk[2] if len(soil_npk) > 2 else 0
    zn_ppm = analysis.get("zinc", 0.0)

    # New Pest/Nematode detections
    if telemetry.get("pest_detected"):
        alerts.append("BIO-THREAT: Acoustic/Thermal sensors detected suspected pest activity!")
    if telemetry.get("nematode_detected"):
        alerts.append("BIO-THREAT: Acoustic stem probe detected suspected nematode activity!")

    if profile == "group1":
        if ph > 7.5 and zn_ppm < 1.2:
            alerts.append("CRITICAL: Zinc deficiency / Khaira Disease risk detected!")
    elif profile == "group2":
        if ambient_temp < 2.0:
            alerts.append("WARNING: Frost risk detected. Activate warming system.")
    elif profile == "group3":
        if stem_piezo > 85.0 and moisture < 20.0:
            alerts.append("CRITICAL: Stem cavitation drought alert!")
    elif profile == "group4":
        if (canopy_temp - ambient_temp >= 3.0) and (stem_piezo < 30.0) and (moisture > 40.0):
            alerts.append("CRITICAL: Vascular wilt (Fusarium) detected!")
        if k_val < 120:
            alerts.append(f"WARNING: Potassium deficiency ({k_val} mg/kg < 120).")

    return alerts

# ==============================================================================
# IDENTITY & NEIGHBOR ROUTES
# ==============================================================================

@app.post("/api/auth/signin")
async def signin(farmer_id: Optional[str] = Form(None), token: Optional[str] = Form(None)):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            # Check if user exists
            user = conn.execute("SELECT * FROM users WHERE farmer_id = ?", (farmer_id,)).fetchone()

            if user:
                if token and user['token'] != token:
                    raise HTTPException(status_code=401, detail="Invalid token")
                return {"status": "success", "user": dict(user)}

            # Register new user
            new_id = farmer_id or generate_farmer_id()
            new_token = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            now = datetime.utcnow().isoformat()

            conn.execute(
                "INSERT INTO users (farmer_id, token, created_at) VALUES (?, ?, ?)",
                (new_id, new_token, now)
            )
            conn.commit()
            return {"status": "registered", "farmer_id": new_id, "token": new_token}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Farmer ID already exists")
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        raise HTTPException(status_code=500, detail="Auth server error")

@app.get("/api/profile")
async def get_profile(token: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user

@app.post("/api/profile/crop")
async def update_crop(token: str, crop_group: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    valid_groups = ["group1", "group2", "group3", "group4", "group5", "group6"]
    if crop_group not in valid_groups:
        raise HTTPException(status_code=400, detail="Invalid crop group")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE users SET crop_group = ? WHERE id = ?", (crop_group, user['id']))
            conn.commit()
        return {"status": "success", "crop_group": crop_group}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/neighbors/code")
async def get_share_code(token: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Check for existing code
            code = conn.execute("SELECT code FROM neighbor_codes WHERE user_id = ?", (user['id'],)).fetchone()
            if code:
                return {"code": code[0]}

            # Generate new code
            new_code = 'AGRO-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            conn.execute("INSERT INTO neighbor_codes (code, user_id, created_at) VALUES (?, ?, ?)",
                         (new_code, user['id'], datetime.utcnow().isoformat()))
            conn.commit()
            return {"code": new_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/neighbors/request")
async def request_connection(token: str, code: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            target = conn.execute("SELECT user_id FROM neighbor_codes WHERE code = ?", (code,)).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Invalid share code")

            target_id = target['user_id']
            if target_id == user['id']:
                raise HTTPException(status_code=400, detail="Cannot connect to yourself")

            # Check for existing connection
            existing = conn.execute(
                "SELECT id FROM neighbor_connections WHERE requestor_id = ? AND target_id = ?",
                (user['id'], target_id)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="Request already exists")

            conn.execute(
                "INSERT INTO neighbor_connections (requestor_id, target_id, status, created_at) VALUES (?, ?, ?, ?)",
                (user['id'], target_id, 'pending', datetime.utcnow().isoformat())
            )
            conn.commit()
            return {"status": "requested"}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/neighbors/requests")
async def list_requests(token: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT nc.*, u.farmer_id FROM neighbor_connections nc JOIN users u ON nc.requestor_id = u.id WHERE nc.target_id = ? AND nc.status = 'pending'",
                (user['id'],)
            )
            return {"requests": [dict(row) for row in cursor.fetchall()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/neighbors/approve")
async def approve_connection(token: str, request_id: int, action: str): # action: 'accept' or 'reject'
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    status = 'accepted' if action == 'accept' else 'rejected'
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE neighbor_connections SET status = ? WHERE id = ? AND target_id = ?",
                         (status, request_id, user['id']))
            conn.commit()
            return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/neighbors/alerts")
async def get_neighbor_alerts(token: str):
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            # Find neighbors
            neighbors = conn.execute(
                "SELECT target_id FROM neighbor_connections WHERE requestor_id = ? AND status = 'accepted' "
                "UNION SELECT requestor_id FROM neighbor_connections WHERE target_id = ? AND status = 'accepted'",
                (user['id'], user['id'])
            ).fetchall()

            neighbor_ids = [n[0] for n in neighbors]
            if not neighbor_ids:
                return {"alerts": []}

            # Fetch only the most recent alert from each neighbor's last log
            placeholders = ','.join(['?'] * len(neighbor_ids))
            cursor = conn.execute(
                f"SELECT device_id, alerts FROM telemetry_logs WHERE device_id IN ({placeholders}) AND alerts IS NOT NULL "
                "GROUP BY device_id ORDER BY id DESC",
                neighbor_ids
            )
            return {"alerts": [dict(row) for row in cursor.fetchall()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=FileResponse)
async def serve_dashboard():
    dashboard_path = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend", "dashboard.html"))
    if not os.path.exists(dashboard_path):
        logger.error(f"Dashboard HTML not found at {dashboard_path}")
        raise HTTPException(status_code=404, detail="Dashboard HTML not found")
    return dashboard_path

@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    state.device_id = payload.device_id
    # Update state from telemetry dictionary
    if payload.telemetry:
        state.latest_telemetry.update(payload.telemetry)

    state.active_alerts = evaluate_rules(state.latest_telemetry, state.latest_analysis, state.active_profile)
    save_reading(payload.device_id)

    logger.info(f"Telemetry received from {payload.device_id}. Alerts: {len(state.active_alerts)}")
    return {"status": "success", "alerts_triggered": len(state.active_alerts)}

@app.post("/api/upload")
async def upload_image(
    device_id: Optional[str] = Form("ESP32_FIELD_NODE_01"),
    image: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None)
):
    img_file = image or file
    if not img_file:
        raise HTTPException(status_code=400, detail="No image file provided")

    contents = await img_file.read()
    try:
        analysis = analyze_colorimetric_image(contents)
        state.latest_analysis = analysis
        if state.latest_telemetry:
            state.active_alerts = evaluate_rules(state.latest_telemetry, state.latest_analysis, state.active_profile)

        save_reading(device_id)

        return {"status": "success", "analysis": analysis}
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/dashboard")
async def get_dashboard():
    return {
        "active_profile": state.active_profile,
        "latest_reading": {
            "telemetry": state.latest_telemetry,
            "alerts": state.active_alerts
        }
    }

@app.get("/api/history")
async def get_history(limit: int = 5):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM telemetry_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = [dict(row) for row in cursor.fetchall()]
            return {"history": rows}
    except Exception as e:
        logger.error(f"History fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/export")
async def export_csv():
    def generate_csv():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM telemetry_logs ORDER BY id ASC")
                output = io.StringIO()
                writer = csv.writer(output)
                if cursor.description:
                    headers = [col[0] for col in cursor.description]
                    writer.writerow(headers)
                for row in cursor:
                    writer.writerow(list(row))
                yield output.getvalue()
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            yield "Error generating CSV"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agronode_telemetry_log.csv"}
    )

@app.get("/api/remedies")
async def get_remedies():
    """Returns the full agronomic remedy dataset."""
    return REMEDY_DATA

@app.post("/api/profile")
async def set_profile(group_key: str = Query(...)):
    valid_groups = ["group1", "group2", "group3", "group4", "group5", "group6"]
    if group_key not in valid_groups:
        raise HTTPException(status_code=400, detail="Invalid group key")
    state.active_profile = group_key
    state.active_alerts = evaluate_rules(state.latest_telemetry, state.latest_analysis, state.active_profile)
    return {"status": "success", "active_profile": state.active_profile}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
