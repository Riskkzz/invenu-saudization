"""اختبارات الخادم المحلي ببيانات المثال (لا تحتوي بيانات حقيقية)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import app  # noqa: E402

c = TestClient(app)


def test_demo_analyze_and_report():
    tok = c.post("/api/demo").json()["token"]
    r = c.post("/api/analyze", json={"token": tok, "settings": {"reference_date": "2026-10-23"}})
    assert r.status_code == 200
    j = r.json()
    assert j["groups"] and all(g["source_url"] for g in j["groups"])
    assert all("employee_ids" in o for g in j["groups"] for o in g["occupations"])
    assert c.post("/api/report", json={"token": tok, "lang": "en"}).status_code == 200


def test_simulate_creates_violation():
    tok = c.post("/api/demo").json()["token"]
    r = c.post("/api/simulate", json={"token": tok, "occupation": "سكرتير", "saudi": False, "wage": 5000, "count": 1}).json()
    assert r["after"]["restricted_violations"] == r["before"]["restricted_violations"] + 1


def test_invalid_rules_rejected():
    rules = c.get("/api/rules").json()
    rules["groups"][0]["phases"] = [{"effective_date": "2026-01-01", "ratio": 5}]
    assert c.put("/api/rules", json=rules).status_code == 422


def test_bad_upload():
    r = c.post("/api/upload", files={"file": ("x.xlsx", b"not excel")})
    assert r.status_code == 400
