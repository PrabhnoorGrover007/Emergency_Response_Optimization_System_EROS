import sqlite3
import csv
import os

DB_FILE = "emergency.db"
CSV_FILE = "vehicles.csv"

def init_db():
    # Always start fresh for this script
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"Removed existing {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE vehicles (
            id TEXT PRIMARY KEY,
            type TEXT,
            lat REAL,
            lon REAL,
            status TEXT,
            station_id TEXT
        )
    ''')

    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found.")
        return

    with open(CSV_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        to_db = []
        for row in reader:
            # Normalize data as in backend.py
            v_type = row["type"].strip().lower()
            v_status = row.get("status", "available").strip().lower()
            if v_status not in ("available", "busy"):
                v_status = "available"
            
            to_db.append((
                row['id'].strip(),
                v_type,
                float(row['lat']),
                float(row['lon']),
                v_status,
                row.get('station_id', '').strip()
            ))

    cursor.executemany("INSERT INTO vehicles (id, type, lat, lon, status, station_id) VALUES (?, ?, ?, ?, ?, ?)", to_db)
    conn.commit()
    conn.close()
    print(f"Database {DB_FILE} initialized with {len(to_db)} vehicles.")

if __name__ == "__main__":
    init_db()
