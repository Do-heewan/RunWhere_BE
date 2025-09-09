# ORS 기반 러닝 코스 생성 및 평가 함수 모듈

import math
import random
import requests

# -----------------------------
# Geometry helpers (meters)
# -----------------------------
def hv_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def path_len_m(coords):
    return sum(hv_m(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0]) for i in range(len(coords)-1)) if len(coords) > 1 else 0.0

def heading_deg(a, b):
    dy, dx = b[1]-a[1], b[0]-a[0]
    ang = math.degrees(math.atan2(dy, dx))
    return (ang + 360.0) % 360.0

def sharp_turn_density(coords, th_deg=45):
    if len(coords) < 3: return 0.0
    L = max(1.0, path_len_m(coords))
    cnt = 0
    for i in range(1, len(coords)-1):
        h1 = heading_deg(coords[i-1], coords[i])
        h2 = heading_deg(coords[i], coords[i+1])
        d = abs(h2 - h1); d = 360 - d if d > 180 else d
        if d >= th_deg: cnt += 1
    return cnt / L

def backtrack_proxy(coords, step_m=25, near_m=12):
    if len(coords) < 3: return 0.0
    pts = [coords[0]]; acc = 0.0
    for i in range(1, len(coords)):
        acc += hv_m(coords[i-1][1], coords[i-1][0], coords[i][1], coords[i][0])
        if acc >= step_m:
            pts.append(coords[i]); acc = 0.0
    n = len(pts); reused = 0
    for i in range(n):
        for j in range(i+5, n):
            d = hv_m(pts[i][1], pts[i][0], pts[j][1], pts[j][0])
            if d <= near_m: reused += 1; break
    return reused / max(1, n)

def loop_closure_m(coords):
    if not coords: return 1e9
    return hv_m(coords[0][1], coords[0][0], coords[-1][1], coords[-1][0])

# -----------------------------
# ORS wrappers
# -----------------------------
def ors_round_trip(api_key, start_lon, start_lat, length_m, seed=None, profile="foot-walking"):
    url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": [[start_lon, start_lat]], "options": {"round_trip": {"length": int(length_m)}}}
    if seed is not None:
        body["options"]["round_trip"]["seed"] = int(seed)
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    gj = r.json()
    return gj["features"][0]["geometry"]["coordinates"]

def ors_directions(api_key, coords_lonlat, profile="foot-walking"):
    url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": coords_lonlat}
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    gj = r.json()
    return gj["features"][0]["geometry"]["coordinates"]

# -----------------------------
# Scoring (shape-aware, simple)
# -----------------------------
def score_route(coords, target_km, theta_deg=45, w_turn=3.0, w_back=3.0, w_dist=2.0, loop_close_cap_m=150):
    Lm = path_len_m(coords)
    sd = sharp_turn_density(coords, th_deg=theta_deg)
    rp = backtrack_proxy(coords)
    derr = abs(Lm/1000.0 - target_km)
    dse = loop_closure_m(coords)
    loop_bonus = 0.5 if dse <= loop_close_cap_m else 0.0
    score = -(w_turn*sd + w_back*rp + w_dist*derr) + loop_bonus
    return score, dict(length_km=Lm/1000.0, sharp_density=sd, backtrack=rp, dist_err_km=derr, loop_closure_m=dse)