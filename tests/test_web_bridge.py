"""جسر نسخة المتصفح (web/invenu_web_bridge.py) يُختبر هنا بـ CPython: نفس الكود الذي يعمل داخل Pyodide."""
import base64
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "web")]
import invenu_web_bridge as W  # noqa: E402


class JsBytes:
    """يحاكي Uint8Array القادم من JavaScript (له to_bytes)."""

    def __init__(self, data):
        self.data = data

    def to_bytes(self):
        return self.data


def call(method, path, body=None):
    out = json.loads(W.call(method, path, json.dumps(body) if body is not None else ""))
    return out["status"], out["body"]


def test_demo_analyze_simulate_report():
    st, d = call("POST", "/api/demo", {})
    assert st == 200
    st, a = call("POST", "/api/analyze", {"token": d["token"], "settings": {"reference_date": "2026-10-23"}})
    assert st == 200 and a["groups"] and a["summary"]["total"] == d["rows"]
    st, s = call("POST", "/api/simulate", {"token": d["token"], "occupation": "سكرتير", "saudi": False, "wage": 5000, "count": 1})
    assert s["after"]["restricted_violations"] == s["before"]["restricted_violations"] + 1
    r = json.loads(W.report(json.dumps({"token": d["token"], "lang": "en"})))
    assert r["status"] == 200 and r["body"]["name"].endswith(".xlsx")
    assert base64.b64decode(r["body"]["b64"])[:2] == b"PK"


def test_errors_are_returned_not_raised():
    assert call("POST", "/api/analyze", {"token": "missing"})[0] == 404
    assert json.loads(W.upload(JsBytes(b"not excel"), "x.xlsx"))["status"] == 400
    assert call("GET", "/api/nope")[0] == 404


def test_build_zip_contains_engine_without_fastapi(tmp_path):
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_web as B
    z = zipfile.ZipFile(__import__("io").BytesIO(B.app_zip({})))
    names = set(z.namelist())
    assert {"backend/service.py", "backend/engine.py", "rules/saudization_rules.json", "invenu_web_bridge.py"} <= names
    assert "backend/api.py" not in names
