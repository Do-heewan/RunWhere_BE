# RunWhere Backend

**RunWhere**는 사용자의 현재 위치와 목표 거리를 바탕으로 달리기 좋은 러닝 코스를 생성·추천하는 앱입니다.
이 저장소는 RunWhere의 **백엔드**로, 경로 생성 알고리즘과 Django 기반 API 서버를 포함합니다.

> 현재는 초기 개발 단계입니다. 경로 생성·평가 로직은 Streamlit 프로토타입으로 검증했으며, Django 서버로 옮기는 작업이 진행 중입니다.

## 주요 기능

- **러닝 코스 생성**: [OpenRouteService(ORS)](https://openrouteservice.org/)의 `foot-walking` 프로필로 보행 가능한 도로망 위에 경로를 만듭니다.
  - **Loop**: 출발점으로 돌아오는 순환 코스 (ORS `round_trip` 사용, seed를 바꿔 여러 후보 생성)
  - **Out&Back**: 목표 거리의 절반쯤 떨어진 임의 방향의 지점까지 갔다가 돌아오는 왕복 코스
  - **Point-to-Point**: 출발점에서 도착점까지 가는 편도 코스
- **코스 평가 및 추천**: 생성한 후보 경로마다 "달리기 좋은 정도"를 점수로 매기고, 점수가 높은 순서대로 추천합니다.

## 코스 점수 계산

```
score = -(w_turn · sharp_turn_density
        + w_back · backtrack_proxy
        + w_dist · distance_error)
        + loop_closure_bonus
```

| 지표 | 설명 | 기본값 |
|---|---|---|
| `sharp_turn_density` | 단위 거리(m)당 급회전(기준 각도 θ 이상) 횟수. 꺾이는 곳이 많을수록 감점 | θ = 45°, `w_turn` = 3.0 |
| `backtrack_proxy` | 경로를 약 25m 간격으로 샘플링한 뒤, 이미 지나간 지점(12m 이내)을 다시 지나는 비율. 같은 길을 되밟을수록 감점 | `w_back` = 3.0 |
| `distance_error` | 실제 경로 길이와 목표 거리의 차이(km) | `w_dist` = 2.0 |
| `loop_closure_bonus` | 출발점과 도착점이 150m 이내면 +0.5 | 150 m |

거리는 모두 Haversine 공식으로 계산합니다.

## 기술 스택

- **Python 3.11**
- **Django 5.2**: API 서버
- **SQLite**: 개발용 DB
- **OpenRouteService API**: 도로망 기반 경로 탐색
- **Streamlit, Folium, pydeck**: 알고리즘 검증용 프로토타입 UI

## 프로젝트 구조

```
RunWhere_BE/
├── route_utils.py       # 경로 생성·평가 핵심 모듈 (ORS 호출, 기하 계산, 점수 계산)
├── prototype.py         # Streamlit 프로토타입 (지도에서 출발점 선택 → 후보 생성 → 시각화)
└── runwhere/            # Django 프로젝트
    ├── manage.py
    ├── runwhere/        # 프로젝트 설정 (settings, urls, wsgi/asgi)
    └── course/          # 러닝 코스 앱 (모델·뷰 구현 예정)
```

### `route_utils.py` 주요 함수

| 함수 | 역할 |
|---|---|
| `ors_round_trip(api_key, lon, lat, length_m, seed)` | ORS로 순환 코스 생성 |
| `ors_directions(api_key, coords_lonlat)` | 여러 지점을 잇는 경로 탐색 |
| `score_route(coords, target_km, ...)` | 경로 점수와 세부 지표 반환 |
| `path_len_m`, `sharp_turn_density`, `backtrack_proxy`, `loop_closure_m` | 경로 기하 지표 계산 |

> 좌표는 ORS 규칙에 따라 `[경도(lon), 위도(lat)]` 순서를 씁니다.

## 시작하기

### 1. 환경 준비

```bash
git clone <repository-url>
cd RunWhere_BE

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install django requests
```

### 2. ORS API 키 발급

[OpenRouteService](https://openrouteservice.org/dev/#/signup)에서 무료 API 키를 발급받습니다.

### 3. Django 서버 실행

```bash
cd runwhere
python manage.py migrate
python manage.py runserver
```

`http://127.0.0.1:8000/admin/`에서 관리자 페이지를 확인할 수 있습니다.

### 4. 프로토타입 실행 (선택)

경로 생성 알고리즘을 지도에서 직접 확인해 볼 수 있습니다.

```bash
pip install streamlit requests shapely numpy pandas pydeck folium streamlit-folium streamlit-geolocation
streamlit run prototype.py
```

1. 사이드바에 ORS API 키를 입력하고 모드(Loop / Out&Back / Point-to-Point)와 목표 거리를 정합니다.
2. **GPS로 위치 찾기**를 누르거나 지도를 클릭한 뒤 **위치 설정**으로 출발점을 정합니다.
3. **재검색**을 누르면 후보 코스가 생성되고, 점수 상위 5개가 지도에 표시됩니다.

## 앞으로 할 일

- [ ] `course` 앱을 `INSTALLED_APPS`에 등록하고 코스 모델 설계
- [ ] `route_utils`를 활용한 코스 생성·추천 REST API 구현
- [ ] ORS API 키 등 민감 정보를 환경 변수로 분리
- [ ] `requirements.txt` 추가
- [ ] 한국 시간대(`Asia/Seoul`) 및 언어 설정
