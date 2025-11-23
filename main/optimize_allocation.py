import csv
import sys
import os

# =========================
# CSV HELPERS
# =========================

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_vehicles(path, vehicles, fieldnames=None):
    if not vehicles:
        print("[WARN] No vehicles to save.")
        return

    if not fieldnames:
        fieldnames = list(vehicles[0].keys())

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(vehicles)


# =========================
# FACTOR SELECTION
# =========================

def choose_factor_scenario(factors, scenario_id=None):
    """
    Choose which scenario (row from factors.csv) to use.

    - If scenario_id is provided (e.g. command line argument),
      pick the row with matching id.
    - Otherwise, pick the row with the highest expected_call_volume.
    """
    if scenario_id is not None:
        for row in factors:
            if str(row["id"]) == str(scenario_id):
                return row

    # Fallback: pick scenario with highest expected_call_volume
    def safe_float(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    return max(factors, key=lambda r: safe_float(r.get("expected_call_volume", 0.0)))


# =========================
# ALLOCATION LOGIC
# =========================

def build_station_lookup(stations):
    """
    Returns:
      - station_lookup: id -> station dict
      - region_map: region -> list of station ids
    """
    station_lookup = {}
    region_map = {}

    for s in stations:
        sid = s["id"]
        station_lookup[sid] = s

        region = s.get("region", "").strip().lower()
        region_map.setdefault(region, []).append(sid)

    return station_lookup, region_map


def compute_station_weights(stations, factor, vehicle_type):
    """
    Compute a weight for each station for this vehicle_type based on:
      - station capacity for that type
      - whether the station's region matches the "hot" factor region
      - expected_call_volume (boost hotspot)

    Returns: dict station_id -> weight (int >= 0)
    """
    region_hot = factor.get("region", "").strip().lower()
    try:
        expected_volume = float(factor.get("expected_call_volume", 0.0))
    except Exception:
        expected_volume = 0.0

    # extra boost for hot region
    hot_multiplier = 1.0 + expected_volume  # e.g., volume=0.9 -> 1.9x
    base_multiplier = 1.0

    if vehicle_type == "ambulance":
        cap_field = "capacity_ambulance"
    elif vehicle_type == "police":
        cap_field = "capacity_police"
    else:
        cap_field = "capacity_fire"

    weights = {}
    for s in stations:
        sid = s["id"]
        region = s.get("region", "").strip().lower()

        try:
            cap = int(s.get(cap_field, "0"))
        except Exception:
            cap = 0

        if cap <= 0:
            continue  # this station doesn't house this type

        # base weight is capacity
        w = cap

        # if this station is in the hot region, boost its weight
        if region == region_hot:
            w = int(round(w * hot_multiplier))
        else:
            w = int(round(w * base_multiplier))

        if w < 0:
            w = 0

        if w > 0:
            weights[sid] = w

    return weights


def assign_vehicles_to_stations(vehicles, stations, factor):
    """
    Pure heuristic allocator:
      - Groups vehicles by type (ambulance/police/fire)
      - Computes station weights for each type
      - Uses weighted round-robin assignment to choose a station
      - Sets vehicle lat/lon to that station location
      - Adds/updates 'station_id' for each vehicle
    """
    # Pre-build lookups
    station_lookup, _ = build_station_lookup(stations)

    # Prepare vehicles by type
    vehicles_by_type = {
        "ambulance": [],
        "police": [],
        "fire": []
    }
    for v in vehicles:
        vtype = v["type"].strip().lower()
        if vtype in vehicles_by_type:
            vehicles_by_type[vtype].append(v)
        else:
            # Unknown type -> leave it untouched
            pass

    # For each vehicle type, assign stations
    for vtype, vlist in vehicles_by_type.items():
        if not vlist:
            continue

        # Compute station weights for this type
        weights = compute_station_weights(stations, factor, vtype)

        if not weights:
            print(f"[WARN] No stations with capacity for type={vtype}. "
                  f"Vehicles of this type keep their existing positions.")
            continue

        # Build a flat weighted list of station_ids
        weighted_station_ids = []
        for sid, w in weights.items():
            weighted_station_ids.extend([sid] * w)

        if not weighted_station_ids:
            print(f"[WARN] All station weights for type={vtype} are zero; "
                  f"vehicles keep existing positions.")
            continue

        # Assign each vehicle in round-robin over the weighted list
        n = len(weighted_station_ids)
        for i, v in enumerate(vlist):
            sid = weighted_station_ids[i % n]
            st = station_lookup.get(sid)
            if not st:
                # Shouldn't happen, but safety check
                continue

            # Update vehicle location to station location
            try:
                v["lat"] = float(st["lat"])
                v["lon"] = float(st["lon"])
            except Exception:
                pass

            v["station_id"] = sid

    return vehicles


# =========================
# MAIN
# =========================

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    vehicles_path = os.path.join(base_dir, "vehicles.csv")
    stations_path = os.path.join(base_dir, "stations.csv")
    factors_path = os.path.join(base_dir, "factors.csv")
    output_path = os.path.join(base_dir, "vehicles_optimized.csv")

    if not os.path.exists(vehicles_path):
        print(f"[ERROR] vehicles.csv not found at {vehicles_path}")
        return

    if not os.path.exists(stations_path):
        print(f"[ERROR] stations.csv not found at {stations_path}")
        return

    if not os.path.exists(factors_path):
        print(f"[ERROR] factors.csv not found at {factors_path}")
        return

    vehicles = load_csv(vehicles_path)
    stations = load_csv(stations_path)
    factors = load_csv(factors_path)

    # Optional scenario id from command line: python optimize_allocation.py 2
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else None
    factor = choose_factor_scenario(factors, scenario_id=scenario_id)

    print("[INFO] Using factor scenario:", factor)

    # Normalize vehicle types & status
    for v in vehicles:
        v["type"] = v["type"].strip().lower()
        v["status"] = v.get("status", "available").strip().lower()
        if v["status"] not in ("available", "busy"):
            v["status"] = "available"

    updated_vehicles = assign_vehicles_to_stations(vehicles, stations, factor)

    # Decide fieldnames: keep original fields plus station_id if missing
    fieldnames = list(updated_vehicles[0].keys())
    if "station_id" not in fieldnames:
        fieldnames.append("station_id")

    save_vehicles(output_path, updated_vehicles, fieldnames=fieldnames)

    print(f"[INFO] Wrote optimized vehicle positions to {output_path}")


if __name__ == "__main__":
    main()
