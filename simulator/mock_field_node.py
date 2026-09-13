import requests
import time
import random
import numpy as np
import cv2
from datetime import datetime

BACKEND_URL = "https://agro-rxpe.onrender.com"
DEVICE_ID = "ESP32_FIELD_NODE_01"


def generate_mock_image(nitrate_ppm, phosphate_ppm, zinc_ppm):
    """Synthesizes an image reflecting nutrient concentrations via color shifts."""
    # Image size 320x240
    img = np.full((240, 320, 3), 128, dtype=np.uint8)

    # Define a center ROI (where the reagent liquid is)
    cy, cx = 120, 160
    rh, rw = 96, 128  # 40% of 240x320

    # Create a "liquid" color based on PPM
    # nitrate -> a* (Red/Green) -> We simulate this by adjusting BGR
    # phosphate -> b* (Blue/Yellow)
    # zinc -> L + a*

    blue = int(np.clip(128 + (phosphate_ppm * 2), 0, 255))
    green = int(np.clip(128 - (nitrate_ppm / 2), 0, 255))
    red = int(np.clip(128 + (zinc_ppm * 10), 0, 255))

    color = [blue, green, red]
    img[cy - rh//2: cy + rh//2, cx - rw//2: cx + rw//2] = color

    # Add some noise to make it look real
    noise = np.random.randint(-10, 11, (240, 320, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    _, buffer = cv2.imencode('.jpg', img)
    return buffer.tobytes()


def send_telemetry(anomaly_type=None):
    # Base values
    temp = 25.0 + random.uniform(-1, 1)
    humidity = 60.0 + random.uniform(-5, 5)
    ph = 6.5 + random.uniform(-0.2, 0.2)
    moisture = 45.0 + random.uniform(-5, 5)
    canopy_temp = 26.0 + random.uniform(-1, 1)
    ambient_temp = 25.0 + random.uniform(-1, 1)
    stem_piezo = 40.0 + random.uniform(-5, 5)

    # Expanded Nutrient Set (Typical values)
    nutrients = {
        "nitrogen": random.uniform(100, 200),
        "phosphorus": random.uniform(30, 70),
        "potassium": random.uniform(100, 200),
        "ca": round(random.uniform(1380.0, 1460.0), 2),
        "mg": round(random.uniform(225.0, 255.0), 2),
        "s": round(random.uniform(19.0, 26.5), 2),
        "zn": random.uniform(0.5, 3.0),
        "fe": random.uniform(1.0, 4.0),
        "b": random.uniform(0.1, 1.0),
        "mn": random.uniform(0.5, 2.0),
        "cu": random.uniform(0.1, 0.5),
        "mo": random.uniform(0.01, 0.2),
        "cl": random.uniform(10, 50),
        "ni": random.uniform(0.01, 0.1),
    }

    # Threat Flags
    pest_detected = random.random() < 0.05
    nematode_detected = random.random() < 0.05

    if anomaly_type == "alkaline_spike":
        ph = 8.5 + random.uniform(0, 0.5)
        logger_msg = "[ANOMALY] Injecting Alkaline pH spike"
    elif anomaly_type == "heat_spike":
        canopy_temp = 35.0 + random.uniform(0, 2)
        ambient_temp = 28.0
        logger_msg = "[ANOMALY] Injecting Canopy Heat spike"
    elif anomaly_type == "drought":
        moisture = 15.0
        stem_piezo = 95.0
        logger_msg = "[ANOMALY] Injecting Drought/Cavitation state"
    else:
        logger_msg = "Sending normal telemetry"

    # Combine everything into telemetry payload
    telemetry = {
        "temperature": temp,
        "humidity": humidity,
        "ph": ph,
        "moisture": moisture,
        "canopy_temp": canopy_temp,
        "ambient_temp": ambient_temp,
        "stem_piezo": stem_piezo,
        "pest_detected": pest_detected,
        "nematode_detected": nematode_detected,
        **nutrients
    }

    payload = {
        "device_id": DEVICE_ID,
        "timestamp": datetime.now().isoformat(),
        "telemetry": telemetry,
        "status": "online"
    }

    print(f"{logger_msg} -> {BACKEND_URL}/api/telemetry")
    try:
        requests.post(f"{BACKEND_URL}/api/telemetry", json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending telemetry: {e}")


def send_image(nitrate, phosphate, zinc):
    print(f"Uploading nutrient image: N={nitrate}, P={phosphate}, Zn={zinc}")
    img_bytes = generate_mock_image(nitrate, phosphate, zinc)
    files = {'image': ('nutrient.jpg', img_bytes, 'image/jpeg')}
    data = {'device_id': DEVICE_ID}
    try:
        requests.post(f"{BACKEND_URL}/api/upload",
                      files=files, data=data, timeout=5)
    except Exception as e:
        print(f"Error uploading image: {e}")


if __name__ == "__main__":
    print("Starting Mock Field Node Simulator...")
    iteration = 0
    while True:
        iteration += 1

        # Decide on anomaly
        anomaly = None
        if iteration % 10 == 0:
            anomaly = "alkaline_spike"
        elif iteration % 15 == 0:
            anomaly = "heat_spike"
        elif iteration % 20 == 0:
            anomaly = "drought"

        send_telemetry(anomaly)

        # Simulate nutrient variation for images
        send_image(
            nitrate=random.uniform(0, 180),
            phosphate=random.uniform(0, 60),
            zinc=random.uniform(0, 4.5)
        )

        time.sleep(10)
