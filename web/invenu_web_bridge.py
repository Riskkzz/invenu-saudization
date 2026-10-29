"""
invenu_web_bridge.py — نقطة الدخول داخل المتصفح (Pyodide)
=========================================================
يستدعي service.py نفسه الذي يستخدمه الخادم المحلي، ويعيد النتيجة كـ JSON إلى web/bridge.js.
لا يوجد أي اتصال شبكي هنا: الملف يُقرأ من ذاكرة المتصفح ويبقى فيها. (طلب «المستشار الذكي» يبنيه ai_request
ويرسله bridge.js بنص القرار فقط، ثم يحلّل ai_response الرد.)
"""
import base64
import copy
import json
import traceback

from backend import rules_store as R
from backend import service as SV
from backend.presenter import jsonable
from backend.service import ServiceError

DEFAULT_RULES = copy.deepcopy(SV.STATE["rules"])


def _out(status, body):
    return json.dumps({"status": status, "body": jsonable(body)}, ensure_ascii=False, default=str)


def _guard(fn):
    try:
        return _out(200, fn())
    except ServiceError as e:
        return _out(e.status, {"detail": e.detail})
    except Exception as e:  # noqa: BLE001 — أي خطأ غير متوقع يُعرض للمستخدم بدل تعطل الصفحة
        traceback.print_exc()
        return _out(500, {"detail": f"{type(e).__name__}: {e}"})


def default_rules_version():
    return str(DEFAULT_RULES.get("version", ""))


def restore_saved_rules(rules_json):
    """قواعد عدّلها المستخدم سابقاً في هذا المتصفح (localStorage)."""
    return _guard(lambda: SV.put_rules(json.loads(rules_json)))


def restore_defaults():
    def run():
        R.save_rules(copy.deepcopy(DEFAULT_RULES), backup=False)
        return SV.reset_rules()
    return _guard(run)


def call(method, path, body_json):
    b = json.loads(body_json) if body_json else {}
    routes = {
        ("GET", "/api/rules"): lambda: SV.get_rules(),
        ("PUT", "/api/rules"): lambda: SV.put_rules(b),
        ("POST", "/api/rules/reset"): lambda: SV.reset_rules(),
        ("POST", "/api/rules/groups"): lambda: SV.approve_draft(b),
        ("POST", "/api/demo"): lambda: SV.demo(),
        ("POST", "/api/analyze"): lambda: SV.analyze(b["token"], b.get("settings")),
        ("POST", "/api/simulate"): lambda: SV.simulate(b["token"], b.get("settings"), b.get("occupation"), b.get("saudi", True),
                                                      float(b.get("wage") or 0), int(b.get("count") or 0), b.get("remove_ids")),
    }
    fn = routes.get((method, path))
    return _guard(fn) if fn else _out(404, {"detail": f"{method} {path}"})


def ai_request(body_json):
    b = json.loads(body_json or "{}")
    return _guard(lambda: SV.ai_request(b.get("text", ""), b.get("api_key", ""), b.get("provider"), b.get("model")))


def ai_response(provider, status, raw):
    return _guard(lambda: SV.ai_response(provider, int(status), raw or ""))


def upload(js_bytes, filename):
    return _guard(lambda: SV.upload(js_bytes.to_bytes(), filename))


def report(body_json):
    b = json.loads(body_json)

    def run():
        data, name = SV.report(b["token"], b.get("settings"), b.get("lang", "ar"))
        return {"b64": base64.b64encode(data).decode(), "name": name}
    return _guard(run)
