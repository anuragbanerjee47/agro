import time
import random
import requests

SERVER_URL = "https://agro-rxpe.onrender.com"


def run_simulator():
    print("AgroNode ESP32 Hardware Simulator started...")
    while True:
        # Generate dynamic agronomic fluctuations
        payload = {
            "device_id": "ESP32_FIELD_NODE_01",
            "soil_npk": [
                round(random.uniform(90.0, 140.0), 1),
                round(random.uniform(30.0, 60.0), 1),
                round(random.uniform(160.0, 210.0), 1)
            ],
            "ph": round(random.uniform(6.1, 7.8), 2),
            "moisture": round(random.uniform(38.0, 58.0), 1),
            "canopy_temp": round(random.uniform(24.0, 29.5), 1),
            "ambient_temp": round(random.uniform(23.0, 26.0), 1),
            "stem_diam": round(random.uniform(32.0, 36.0), 1)
        }

        try:
            res = requests.post(
                f"{SERVER_URL}/api/telemetry", json=payload, timeout=5)
            print(
                f"[Telemetry] Status: {res.status_code} | NPK: {payload['soil_npk']} | pH: {payload['ph']} | Moisture: {payload['moisture']}%")
        except Exception as e:
            print(f"[Telemetry Error]: {e}")

        # Simulate periodic optical test strip / colorimeter upload
        try:
            dummy_img = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xFF\xC0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xFF\xC4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xFF\xDA\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xFF\xD9"
            files = {"file": ("test_strip.jpg", dummy_img, "image/jpeg")}
            data = {"device_id": "ESP32_FIELD_NODE_01"}
            upload_res = requests.post(
                f"{SERVER_URL}/api/upload", data=data, files=files, timeout=5)
            print(f"[Upload] Status: {upload_res.status_code}")
        except Exception as e:
            print(f"[Upload Error]: {e}")

        time.sleep(3)


if __name__ == "__main__":
    run_simulator()
