"""Propose candidate classes for hierarchy nodes whose definition has no class (inferred, unverified)."""
import json
from pathlib import Path

D = Path(__file__).resolve().parents[2] / "data/sources/sketchup/0914-meeting"
cls = {a["definition"]: a["class"] for a in json.loads((D / "classification.json").read_text(encoding="utf-8"))["assignments"]}
H = json.loads((D / "hierarchy.json").read_text(encoding="utf-8"))["nodes"]
P = {n["pid"]: n for n in H}


def anc(n):
    hops, p = 0, P.get(n.get("parent_pid"))
    while p:
        hops += 1
        if p.get("definition") in cls:
            return p, cls[p["definition"]], hops
        p = P.get(p.get("parent_pid"))
    return None, None, 0


def fmt(s):
    return "×".join(f"{v / 1000:.2f}" for v in s)


out = []
for i, n in enumerate(H):
    if n.get("definition") in cls:
        continue
    wb = n["world_bbox"]
    sz, zmin = wb["size"], wb["min"][2]
    a, ac, hops = anc(n)
    geo = f"월드 크기 {fmt(sz)} m, 최소 Z {zmin:,.0f} mm, 깊이 {n['depth']}, 면 {n['faces_recursive']}개, 재질 {n.get('material') or '없음'}"
    if ac == "site-container" and sz[0] > 30000 and sz[1] > 30000:
        c, conf, why = "terrain", 0.45, "대지 CAD 컨테이너 하위의 30 m 이상 넓은 판형 그룹(Z 범위 ±5 m)이라 지형으로 추정"
    elif "Glass" in (n.get("material") or "") and min(sz[0], sz[1]) <= 400 and max(sz[0], sz[1]) > 10000 and sz[2] > 3000:
        c, conf, why = "curtain-wall", 0.45, f"유리 재질의 두께 {min(sz[0], sz[1]):.0f} mm, 길이 10 m 이상·높이 3 m 이상 수직판이라 커튼월로 추정(상위 분류 '{ac}'와 다름)"
    elif ac:
        c, conf, why = ac, (0.55 if hops == 1 else 0.5), f"이름 없는 하위 그룹으로, {hops}단계 위 '{a['definition']}'의 분류 '{ac}'를 상속(부품으로 추정)"
    else:
        c, conf, why = "unused-definition", 0.2, "분류된 상위가 없음"
    out.append({
        "pid": n["pid"], "definition": n["definition"], "path": n.get("path"), "class": c,
        "confidence": conf, "verification_state": "unverified", "source_kind": "inferred",
        "basis_ko": f"{why}. 근거: {geo}.", "hierarchy_locator": f"$.nodes[{i}]",
    })
(D / "classification.supplement.json").write_text(json.dumps({
    "schema": "sion-sketchup-classification-supplement/1",
    "method": "scripts/sketchup/propose_supplement.py (geometry + parent-class inheritance; no auto-approval)",
    "assignments": out}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
from collections import Counter
print(len(out), Counter(o["class"] for o in out).most_common())
