import google.generativeai as genai
import sqlite3
import json
import os
import csv
from dotenv import load_dotenv

# ========== SETUP ==========

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=API_KEY)

DB_FILE = "emergency.db"


# ========== LOAD DATA FROM DB ==========

def load_vehicles_from_db():
    """Load current vehicle state from SQLite."""
    if not os.path.exists(DB_FILE):
        print(f"[ERROR] Database {DB_FILE} not found. Run init_db.py first.")
        return []

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM vehicles")
    rows = cursor.fetchall()
    conn.close()

    vehicles = [dict(row) for row in rows]
    print(f"[INFO] Loaded {len(vehicles)} vehicles from DB")
    return vehicles


def load_stations():
    stations = []
    if os.path.exists("stations.csv"):
        with open("stations.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stations.append(row)
    return stations


def load_factors():
    factors = []
    if os.path.exists("factors.csv"):
        with open("factors.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                factors.append(row)
    return factors


# ========== OPTIMIZATION LOGIC ==========

def optimize_allocation(vehicles, stations, factor_scenario):
    """
    Ask Gemini to optimize vehicle positions based on factors.
    """

    # Construct prompt
    prompt = f"""
    You are an AI dispatcher for emergency services.

    Context:
    - We have {len(vehicles)} emergency vehicles (ambulance, police, fire).
    - We have {len(stations)} stations.
    - Current environmental factors: {factor_scenario}

    Task:
    - Assign each vehicle to a station (station_id) or a specific lat/lon to optimize coverage.
    - High call volume expected? Move units to high-density areas.
    - Bad weather? Distribute them to minimize travel time risks.
    - Event? Concentrate units near the event type.

    Data:

    Stations:
    {json.dumps(stations, indent=2)}

    Vehicles (Current State):
    {json.dumps(vehicles, indent=2)}

    Output Format:
    Return ONLY a JSON array of objects. Each object must have:
    - "id": vehicle id
    - "lat": new latitude
    - "lon": new longitude
    - "station_id": (optional) if at a station

    Do not include markdown formatting or explanations. Just the JSON array.
    """

    model = genai.GenerativeModel("gemini-2.0-flash-exp")

    # Retry logic for rate limits
    max_retries = 5
    base_delay = 10  # seconds

    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            break  # Success
        except Exception as e:
            # Check for 429 or ResourceExhausted
            if "429" in str(e) or "ResourceExhausted" in str(e) or "Quota exceeded" in str(e):
                wait_time = base_delay * (2 ** attempt)
                print(f"[WARN] Rate limit hit. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                import time
                time.sleep(wait_time)
            else:
                print("Error calling Gemini:", e)
                return []
    else:
        print("[ERROR] Max retries exceeded.")
        return []

    try:
        # Clean up response if it has markdown code blocks
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]

        assignments = json.loads(text)
        return assignments
    except Exception as e:
        print("Error parsing Gemini response:", e)
        # print("Raw response:", response.text) # Commented out to reduce noise
        return []


# ========== UPDATE DB ==========

def update_db(assignments):
    """Update vehicle positions in SQLite."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    count = 0
    for a in assignments:
        try:
            cursor.execute(
                "UPDATE vehicles SET lat = ?, lon = ?, station_id = ? WHERE id = ?",
                (a["lat"], a["lon"], a.get("station_id", ""), a["id"])
            )
            count += 1
        except Exception as e:
            print(f"[WARN] Failed to update {a.get('id')}: {e}")

    conn.commit()
    conn.close()
    print(f"[INFO] Updated {count} vehicle positions in DB")


# ========== MAIN ==========

if __name__ == "__main__":
    vehicles = load_vehicles_from_db()
    stations = load_stations()
    factors = load_factors()

    # Pick a scenario (e.g., first one for demo)
    scenario = factors[1] if len(factors) > 1 else {}
    print(f"Using factor scenario: {scenario}")

    if not vehicles:
        print("[ERROR] No vehicles to optimize.")
        exit()

    new_assignments = optimize_allocation(vehicles, stations, scenario)

    if new_assignments:
        print(f"Received {len(new_assignments)} assignments from Gemini")
        update_db(new_assignments)
    else:
        print("Optimization failed.")
