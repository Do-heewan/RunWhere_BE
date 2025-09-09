# app.py — ORS-only Running Route Generator (simple, shape-aware)
# deps: streamlit requests shapely numpy pandas pydeck

import math, random, requests
import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk
from shapely.geometry import LineString
import folium
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

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
    # sample points roughly every step_m; count near revisits far apart in index
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
    # optional loop-closure soft bonus for loop mode: if close enough, give small reward
    dse = loop_closure_m(coords)
    loop_bonus = 0.5 if dse <= loop_close_cap_m else 0.0
    score = -(w_turn*sd + w_back*rp + w_dist*derr) + loop_bonus
    return score, dict(length_km=Lm/1000.0, sharp_density=sd, backtrack=rp, dist_err_km=derr, loop_closure_m=dse)

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="ORS Running Route (Streamlit)", layout="wide")
st.title("러닝 코스 생성·점검 (ORS-only)")
st.caption("지도/툴팁은 English only. ORS foot-walking 기반 Loop / Out&Back / Point-to-Point")

with st.sidebar:
    api = st.text_input("ORS API Key", type="password", value="eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImQ0MDg2ZmQ0NWE5MTQzNDlhNDU2NTMwMWMyYjMyYjgwIiwiaCI6Im11cm11cjY0In0=")
    mode = st.selectbox("Mode", ["Loop", "Out&Back", "Point-to-Point"])
    target_km = st.number_input("Target distance (km)", 1.0, 50.0, 5.0, 0.5)

    if mode == "Point-to-Point":
        c3, c4 = st.columns(2)
        with c3: lat2 = st.number_input("End lat", value=37.5210, format="%.6f")
        with c4: lon2 = st.number_input("End lon", value=127.0350, format="%.6f")

    st.markdown("---")
    st.subheader("Candidates")
    n_cand = st.slider("Number of candidates", 1, 10, 5, 1)

    st.markdown("---")
    st.subheader("Shape scoring")
    theta = st.slider("Sharp-turn threshold (deg)", 30, 80, 45, 1)
    w_turn = st.slider("w_turn", 0.0, 10.0, 3.0, 0.1)
    w_back = st.slider("w_backtrack", 0.0, 10.0, 3.0, 0.1)
    w_dist = st.slider("w_distance_error", 0.0, 10.0, 2.0, 0.1)
    loop_close_cap = st.slider("Loop closure soft bonus within (m)", 50, 300, 150, 10)

# -----------------------------
# 위치 선택: GPS 버튼 + Folium 클릭 -> 위치 설정 버튼
# -----------------------------
st.markdown("---")
st.subheader("Select start location")

# GPS로 위치 찾기: 명시적으로 눌렀을 때만 현재 위치로 갱신
gps_go = st.button("GPS로 위치 찾기")
if gps_go:
    loc = streamlit_geolocation()
    if loc and loc.get("latitude") and loc.get("longitude"):
        st.session_state["start_lat"] = float(loc["latitude"])
        st.session_state["start_lon"] = float(loc["longitude"])
        # 대기 좌표 초기화
        st.session_state.pop("pending_lat", None)
        st.session_state.pop("pending_lon", None)
        st.success("GPS 위치를 가져왔습니다.")
    else:
        st.warning("GPS 좌표를 가져오지 못했습니다. 브라우저 권한을 확인하거나 지도를 클릭해 위치를 선택하세요.")

# Folium 지도: 클릭으로 후보 좌표 선택
default_center = (37.5665, 126.9780)
# pending 좌표가 있으면 지도를 그쪽으로 먼저 센터링하여 피드백 강화
center_lat = st.session_state.get("pending_lat", st.session_state.get("start_lat", default_center[0]))
center_lon = st.session_state.get("pending_lon", st.session_state.get("start_lon", default_center[1]))

fm = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="OpenStreetMap")

# 현재 확정된 시작점 (파란 원)
if "start_lat" in st.session_state and "start_lon" in st.session_state:
    folium.CircleMarker(
        [st.session_state["start_lat"], st.session_state["start_lon"]],
        radius=7, color="#007aff", fill=True, fill_color="#007aff", fill_opacity=0.95,
        tooltip="Start", popup="Start"
    ).add_to(fm)

# 클릭으로 선택된 대기 위치 (노란 원)
if "pending_lat" in st.session_state and "pending_lon" in st.session_state:
    folium.CircleMarker(
        [st.session_state["pending_lat"], st.session_state["pending_lon"]],
        radius=6, color="#f1c40f", fill=True, fill_color="#f1c40f", fill_opacity=0.9,
        tooltip="Pending", popup="Pending"
    ).add_to(fm)

out = st_folium(fm, height=400, width=None, key="pick_map")

# 클릭된 좌표를 임시 저장 (None 안전 처리)
clicked = (out or {}).get("last_clicked") or {}
clicked_lat = clicked.get("lat")
clicked_lon = clicked.get("lng")
if clicked_lat is not None and clicked_lon is not None:
    st.info(f"Clicked: {clicked_lat:.6f}, {clicked_lon:.6f}")
    st.session_state["pending_lat"] = float(clicked_lat)
    st.session_state["pending_lon"] = float(clicked_lon)

c1, c2 = st.columns(2)
with c1:
    set_pos = st.button("위치 설정", disabled=("pending_lat" not in st.session_state or "pending_lon" not in st.session_state))
with c2:
    go = st.button("재검색", type="primary")

if set_pos and ("pending_lat" in st.session_state and "pending_lon" in st.session_state):
    # 사용자가 선택한 좌표를 확정 시작점으로 반영 (GPS에 의해 덮어쓰지 않도록)
    st.session_state["start_lat"] = st.session_state["pending_lat"]
    st.session_state["start_lon"] = st.session_state["pending_lon"]
    # 확정 후 pending은 남겨 UX 피드백을 유지할 수도 있지만, 혼동 방지를 위해 제거
    st.session_state.pop("pending_lat", None)
    st.session_state.pop("pending_lon", None)
    st.success("시작 위치를 설정했습니다.")

# 현재/대기 위치 요약 텍스트
st.caption(
    f"Start: {st.session_state.get('start_lat', float('nan')):.6f}, {st.session_state.get('start_lon', float('nan')):.6f}"
    + (f"  |  Pending: {st.session_state.get('pending_lat'):.6f}, {st.session_state.get('pending_lon'):.6f}"
       if ('pending_lat' in st.session_state and 'pending_lon' in st.session_state) else "")
)

# -----------------------------
# 코스 생성 (재검색 버튼 클릭 시)
# -----------------------------
cand = []
if go:
    if not api:
        st.error("ORS API Key가 필요합니다.")
    elif "start_lat" not in st.session_state or "start_lon" not in st.session_state:
        st.error("시작 위치를 먼저 설정해주세요 (GPS 또는 지도를 클릭 후 '위치 설정').")
    else:
        start = (st.session_state["start_lon"], st.session_state["start_lat"])  # ORS expects (lon, lat)

        try:
            if mode == "Loop":
                for _ in range(n_cand):
                    seed = random.randint(0, 99999)
                    coords = ors_round_trip(api, start[0], start[1], target_km*1000, seed=seed)
                    s, feats = score_route(coords, target_km, theta_deg=theta, w_turn=w_turn, w_back=w_back, w_dist=w_dist, loop_close_cap_m=loop_close_cap)
                    cand.append(dict(kind="loop", coords=coords, score=s, **feats))

            elif mode == "Out&Back":
                # simple outward anchor ~ half distance; then return using network path
                for _ in range(n_cand):
                    r_m = max(300.0, (target_km*1000)/2.0*0.95)
                    ang = random.random()*2*math.pi
                    dlon = (r_m*math.cos(ang)) / (111320*math.cos(math.radians(st.session_state["start_lat"])) )
                    dlat = (r_m*math.sin(ang)) / 110540.0
                    anchor = (start[0] + dlon, start[1] + dlat)
                    out_coords = ors_directions(api, [start, anchor])
                    back_coords = ors_directions(api, [anchor, start])
                    coords = out_coords + back_coords
                    s, feats = score_route(coords, target_km, theta_deg=theta, w_turn=w_turn, w_back=w_back, w_dist=w_dist, loop_close_cap_m=loop_close_cap)
                    cand.append(dict(kind="out&back", coords=coords, score=s, **feats))

            else:  # Point-to-Point
                end = (lon2, lat2)
                for _ in range(n_cand):
                    coords = ors_directions(api, [start, end])
                    s, feats = score_route(coords, target_km, theta_deg=theta, w_turn=w_turn, w_back=w_back, w_dist=w_dist, loop_close_cap_m=loop_close_cap)
                    cand.append(dict(kind="p2p", coords=coords, score=s, **feats))

        except Exception as e:
            st.error(f"ORS error: {e}")
            cand = []

if go and not cand:
    st.warning("생성된 후보가 없습니다.")

# Table
if cand:
    df = pd.DataFrame([{k:v for k,v in c.items() if k!='coords'} for c in cand])
    st.subheader("Candidates (sorted by score)")
    st.dataframe(df.sort_values("score", ascending=False).round(4), use_container_width=True)

# Map (English-only tooltip)
# --- Map (Top routes · default settings) ---
def to_feat(c):
    # ORS coords: [lon, lat] -> pydeck PathLayer expects [lon, lat]
    path = [[p[0], p[1]] for p in c["coords"] if isinstance(p, (list, tuple)) and len(p) == 2]
    return {
        "path": path,
        "score": float(c["score"]),
        "length_km": float(c["length_km"]),
        "sharp_density": float(c["sharp_density"]),
        "backtrack": float(c["backtrack"]),
        "kind": c["kind"],
        "loop_closure_m": float(c["loop_closure_m"]),
    }

top = sorted(cand, key=lambda x: -x["score"])[:min(5, len(cand))]
features = [to_feat(x) for x in top if x.get("coords")]

# 코스별 색상 팔레트 (RGB)
palette = [
    [230, 57, 70],   # red
    [29, 53, 87],    # blue
    [20, 170, 95],   # green
    [255, 140, 0],   # orange
    [92, 124, 250],  # purple-ish
]
for idx, feat in enumerate(features):
    feat["color"] = palette[idx % len(palette)]
    feat["stroke_w"] = max(6 - idx, 2)

st.subheader("Map (Top routes)")
view = pdk.ViewState(
    latitude=st.session_state.get("start_lat", center_lat),
    longitude=st.session_state.get("start_lon", center_lon),
    zoom=13,
)

path_layer = pdk.Layer(
    "PathLayer",
    data=features,
    get_path="path",
    get_width="stroke_w",
    width_units="pixels",
    get_color="color",
    pickable=True,
    auto_highlight=True,
)

# 시작점 표시 (설정된 경우)
start_layer = None
if "start_lat" in st.session_state and "start_lon" in st.session_state:
    start_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"pos": [st.session_state["start_lon"], st.session_state["start_lat"]]}],
        get_position="pos",
        get_fill_color=[0, 122, 255],
        get_radius=10,
        radius_units="meters",
        pickable=False,
    )

tooltip = {
    "html": (
        "<div style='font-family:Inter,system-ui,sans-serif; font-size:12px; line-height:1.4'>"
        "<div style='display:flex; gap:24px'>"
        "  <div>"
        "    <div><b>score</b>: {score:.3f}</div>"
        "    <div><b>length_km</b>: {length_km:.2f}</div>"
        "    <div><b>kind</b>: {kind}</div>"
        "  </div>"
        "  <div>"
        "    <div><b>sharp_density</b>: {sharp_density:.3f}</div>"
        "    <div><b>backtrack</b>: {backtrack:.3f}</div>"
        "    <div><b>loop_closure_m</b>: {loop_closure_m:.1f}</div>"
        "  </div>"
        "</div>"
        "</div>"
    )
}

deck_layers = [path_layer] if start_layer is None else [path_layer, start_layer]
legend_html = " | ".join([f"Top {i+1}" for i in range(len(features))]) if features else ""
if legend_html:
    st.caption(f"Legend: {legend_html}")
st.pydeck_chart(pdk.Deck(
    layers=deck_layers,
    initial_view_state=view,
    tooltip=tooltip,
    map_provider="carto",
    map_style=pdk.map_styles.ROAD
))


st.caption("Scoring = - (w_turn·sharp_turn_density + w_back·backtrack_proxy + w_dist·distance_error) + loop_closure_bonus. Labels in English only.")
