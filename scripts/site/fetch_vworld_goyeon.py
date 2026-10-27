"""고연리 1525 주변 600 m(±300 m) V-World Data API 수집 — PC에서 실행.
실행: doppler run --project mcp-agent-credentials --config dev -- python -X utf8 scripts/site/fetch_vworld_goyeon.py
키는 환경변수 VWORLD_API_KEY(선택 VWORLD_DOMAIN)에서만 읽고 출력하지 않는다.
주의: V-World 공개 API에는 등고선·표고점·DEM 레이어가 없다(2026-10-06 실측 조사). 지형은 NGII 수치지형도 v2
(1:5,000, 등고선 5 m) 또는 NGII 5 m DEM 파일을 받아 site-pipeline의 contours_to_landxml / dem_to_landxml로 처리한다.
결과: data/sites/goyeon-1525/raw/vworld_<LAYER>.geojson (EPSG:5186) — raw/는 커밋하지 않는다.
"""
import json, os, sys, time
import httpx

CX, CY, R = 395925.0, 319220.0, float(os.environ.get("MAP_RADIUS", 300))
BOX = f"BOX({CX-R},{CY-R},{CX+R},{CY+R})"
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sites", "goyeon-1525", "raw")
LAYERS = sys.argv[1:] or ["LP_PA_CBND_BUBUN", "LT_C_LANDINFOBASEMAP", "LT_L_N3A0020000", "LT_C_UQ111",
                          "LT_C_UQ112", "LT_C_BLDGINFO", "LT_L_MOCTLINK", "LT_C_ASITSOILDEP"]


def fetch(layer, c):
    feats, page = [], 1
    while True:
        p = {"service": "data", "request": "GetFeature", "version": "2.0", "format": "json", "data": layer,
             "geomFilter": BOX, "crs": "EPSG:5186", "geometry": "true", "attribute": "true", "size": 1000,
             "page": page, "key": os.environ["VWORLD_API_KEY"]}
        if os.environ.get("VWORLD_DOMAIN"):
            p["domain"] = os.environ["VWORLD_DOMAIN"]
        body = c.get("https://api.vworld.kr/req/data", params=p, timeout=40).json().get("response", {})
        if body.get("status") != "OK":
            return feats, body.get("status")
        feats += body["result"]["featureCollection"].get("features", [])
        pg = body.get("page", {})
        if int(pg.get("current", 1)) >= int(pg.get("total", 1)):
            return feats, "OK"
        page += 1


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    with httpx.Client() as c:
        for lyr in LAYERS:
            feats, st = fetch(lyr, c)
            print(lyr, st, len(feats))
            if feats:
                json.dump({"type": "FeatureCollection", "crs_note": "EPSG:5186", "features": feats},
                          open(os.path.join(OUT, f"vworld_{lyr}.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(0.3)
