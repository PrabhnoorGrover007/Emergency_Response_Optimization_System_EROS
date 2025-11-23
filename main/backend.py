from flask import Flask, request, jsonify, send_from_directory, render_template, g
from dotenv import load_dotenv
from flask_cors import CORS
import sqlite3
import math
import os

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DB_FILE = "emergency.db"

app = Flask(__name__, template_folder='.')
CORS(app)

# ============ DATABASE CONNECTION ============

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_FILE)
        db.row_factory = sqlite3.Row  # Access columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ============ UTIL: DISTANCE ============

def distance_km(lat1, lon1, lat2, lon2):
    """Haversine distance in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ============ FRONTEND ROUTES ============

@app.route("/")
def sos_ui():
    """Serve the iPhone-style SOS interface (sos.html)."""
    return render_template("sos.html", GOOGLE_API_KEY=GOOGLE_API_KEY)


@app.route("/dashboard")
def dashboard_ui():
    """Serve the control-room dashboard (dashboard.html)."""
    return render_template("dashboard.html", GOOGLE_API_KEY=GOOGLE_API_KEY)


# ============ API ROUTES ============

@app.route("/api/request", methods=["POST"])
def request_unit():
    """
    Request closest available unit of a given type.
    """
    data = request.get_json(force=True) or {}

    req_type = str(data.get("type", "")).strip().lower()
    loc = data.get("location")

    if not loc or len(loc) != 2:
        return jsonify({"error": "Invalid location"}), 400

    try:
        lat, lon = float(loc[0]), float(loc[1])
    except (TypeError, ValueError):
        return jsonify({"error": "Location must be numeric [lat, lon]"}), 400

    # Query DB for available units of requested type
    db = get_db()
    cursor = db.execute(
        "SELECT * FROM vehicles WHERE type = ? AND status = 'available'",
        (req_type,)
    )
    candidates = cursor.fetchall()

    if not candidates:
        print(f"[INFO] No available unit for type={req_type}")
        return jsonify({"error": "No available unit"}), 400

    # Pick closest by distance
    # Note: We do distance calc in Python because SQLite doesn't have SQRT/ACOS by default easily
    # unless we load extensions, but for 50 vehicles Python is fine.
    
    best_unit = None
    min_dist = float('inf')

    for v in candidates:
        d = distance_km(lat, lon, v['lat'], v['lon'])
        if d < min_dist:
            min_dist = d
            best_unit = v

    if not best_unit:
        return jsonify({"error": "Error finding closest unit"}), 500

    # Mark it busy
    db.execute("UPDATE vehicles SET status = 'busy' WHERE id = ?", (best_unit['id'],))
    db.commit()

    print(
        f"[INFO] Assigned {best_unit['id']} ({best_unit['type']}) "
        f"from ({best_unit['lat']:.4f}, {best_unit['lon']:.4f}) "
        f"to incident at ({lat:.4f}, {lon:.4f})"
    )

    return jsonify({
        "unit": best_unit['id'],
        "from": {"lat": best_unit['lat'], "lon": best_unit['lon']},
        "to": {"lat": lat, "lon": lon}
    })


@app.route("/api/vehicles")
def get_vehicles():
    """
    Returns all vehicles (for dashboard + debugging).
    """
    db = get_db()
    cursor = db.execute("SELECT * FROM vehicles")
    rows = cursor.fetchall()
    
    # Convert to list of dicts
    vehicles = [dict(row) for row in rows]
    return jsonify(vehicles)


@app.route("/api/reset", methods=["POST"])
def reset_vehicles():
    """
    Reset all vehicles to 'available'.
    """
    db = get_db()
    db.execute("UPDATE vehicles SET status = 'available'")
    db.commit()
    print("[INFO] Reset all vehicles to 'available'")
    return jsonify({"message": "All vehicles reset to available"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
