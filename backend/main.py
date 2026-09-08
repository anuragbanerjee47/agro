import os
import sqlite3
import csv
import io
import json
from datetime import datetime
from typing import Optional
import logging

from fastapi import FastAPI, Request, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import numpy as np
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutrient-monitor")

app = FastAPI(title="Soil & Nutrient Monitoring System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "agronode_history.db")

def get_db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            device_id TEXT,
            crop_profile TEXT,
            nitrogen REAL,
            phosphorus REAL,
            potassium REAL,
            ph REAL,
            moisture REAL,
            canopy_temp REAL,
            ambient_temp REAL,
            optical_nitrate REAL,
            optical_phosphate REAL,
            optical_zinc REAL,
            alerts TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

class SystemState:
    def __init__(self):
        self.active_profile = "group1"
        self.latest_telemetry = {
            "device_id": "ESP32_FIELD_NODE_01",
            "soil_npk": [120.0, 45.0, 180.0],
            "ph": 6.5,
            "moisture": 45.0,
            "canopy_temp": 25.0,
            "ambient_temp": 24.0,
            "stem_diam": 35.0,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.latest_analysis = {
            "nitrate": 180.0,
            "phosphate": 36.2,
            "zinc": 4.5
        }
        self.latest_alerts = []

state = SystemState()

@app.post("/api/telemetry")
async def receive_telemetry(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    device_id = data.get("device_id", "ESP32_FIELD_NODE_01")
    npk = data.get("soil_npk", [120.0, 45.0, 180.0])
    if not isinstance(npk, list) or len(npk) < 3:
        npk = [data.get("nitrogen", 120.0), data.get("phosphorus", 45.0), data.get("potassium", 180.0)]
    
    ph = float(data.get("ph", 6.5))
    moisture = float(data.get("moisture", 45.0))
    canopy_temp = float(data.get("canopy_temp", 25.0))
    ambient_temp = float(data.get("ambient_temp", 24.0))

    state.latest_telemetry = {
        "device_id": device_id,
        "soil_npk": npk,
        "ph": ph,
        "moisture": moisture,
        "canopy_temp": canopy_temp,
        "ambient_temp": ambient_temp,
        "stem_diam": float(data.get("stem_diam", 35.0)),
        "timestamp": datetime.utcnow().isoformat()
    }

    alerts = []
    if canopy_temp - ambient_temp > 3.0:
        alerts.append("Vascular Wilt Alert: Canopy temperature significantly above ambient.")
    if ph > 7.5 and state.latest_analysis.get("zinc", 5.0) < 3.0:
        alerts.append("Zinc Deficiency Alert: Alkaline soil reducing zinc bioavailability.")
    state.latest_alerts = alerts

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO telemetry_logs (
                timestamp, device_id, crop_profile,
                nitrogen, phosphorus, potassium, ph, moisture,
                canopy_temp, ambient_temp, optical_nitrate,
                optical_phosphate, optical_zinc, alerts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            state.latest_telemetry["timestamp"],
            device_id,
            state.active_profile,
            npk[0], npk[1], npk[2],
            ph, moisture, canopy_temp, ambient_temp,
            state.latest_analysis.get("nitrate", 0.0),
            state.latest_analysis.get("phosphate", 0.0),
            state.latest_analysis.get("zinc", 0.0),
            "; ".join(alerts)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database write error: {e}")

    return {"status": "ok"}

@app.post("/api/upload")
async def upload_image(request: Request):
    try:
        form = await request.form()
        uploaded_file = form.get("file") or form.get("image")
        if uploaded_file and hasattr(uploaded_file, "read"):
            contents = await uploaded_file.read()
            nparr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.error(f"Image read fallback: {e}")

    analysis = {
        "nitrate": round(float(np.random.uniform(140.0, 200.0)), 1),
        "phosphate": round(float(np.random.uniform(25.0, 45.0)), 1),
        "zinc": round(float(np.random.uniform(3.5, 6.0)), 1)
    }
    state.latest_analysis = analysis
    return {"status": "ok", "analysis": analysis}

@app.get("/api/dashboard")
async def get_dashboard():
    return {
        "active_profile": state.active_profile,
        "telemetry": state.latest_telemetry,
        "analysis": state.latest_analysis,
        "alerts": state.latest_alerts
    }

@app.post("/api/profile")
async def set_profile(group_key: str = Query(...)):
    state.active_profile = group_key
    return {"status": "ok", "active_profile": state.active_profile}

@app.get("/api/history")
async def get_history(limit: int = 15, has_alerts: Optional[bool] = None, profile: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT timestamp, crop_profile, nitrogen, phosphorus, potassium, ph, moisture, canopy_temp, alerts FROM telemetry_logs WHERE 1=1"
    params = []
    
    if profile:
        query += " AND crop_profile = ?"
        params.append(profile)
    if has_alerts is True:
        query += " AND alerts != '' AND alerts != 'None' AND alerts IS NOT NULL"
    elif has_alerts is False:
        query += " AND (alerts = '' OR alerts = 'None' OR alerts IS NULL)"
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "timestamp": r[0],
            "crop_profile": r[1],
            "nitrogen": r[2],
            "phosphorus": r[3],
            "potassium": r[4],
            "ph": r[5],
            "moisture": r[6],
            "canopy_temp": r[7],
            "alerts": r[8] if r[8] else "None"
        })
    return {"history": data}

@app.get("/api/export")
async def export_csv():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM telemetry_logs ORDER BY id ASC")
    rows = cur.fetchall()
    headers = [col[0] for col in cur.description] if cur.description else []
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agronode_telemetry_log.csv"}
    )

@app.get("/")
async def serve_dashboard():
    p = os.path.abspath(os.path.join(os.path.dirname(__file__), "dashboard.html"))
    return FileResponse(p)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)





