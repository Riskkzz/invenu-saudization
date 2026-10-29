"""
service.py — منطق الطلبات المشترك بين الخادم المحلي (api.py) ونسخة المتصفح (web/)
==================================================================================
لا يعتمد على FastAPI: نفس الدوال تُستدعى من الخادم، أو مباشرة داخل المتصفح عبر Pyodide.
ملف التأمينات يبقى في الذاكرة فقط (SESSIONS) ولا يُكتب على القرص.
"""
from __future__ import annotations

import copy
import io
import secrets
import time

import pandas as pd

from . import ai_service as AI
from . import config as C
from . import data_loader as D
from . import engine as E
from . import presenter as P
from . import reports
from . import rules_store as R

MAX_SESSIONS = 20
SESSIONS: dict[str, dict] = {}
STATE = {"rules": R.load_rules()}


class ServiceError(Exception):
    """خطأ موجّه للمستخدم مع رمز حالة HTTP."""

    def __init__(self, status: int, detail):
        super().__init__(detail if isinstance(detail, str) else str(detail))
        self.status, self.detail = status, detail


def make_settings(s: dict | None) -> E.Settings:
    s = s or {}
    ref = pd.Timestamp(s["reference_date"]) if s.get("reference_date") else pd.Timestamp.today().normalize()
    return E.Settings(reference_date=ref, wage_tier=s.get("wage_tier") or "bachelor", below_min_weight=s.get("below_min_weight"),
                      include_activity_specific=bool(s.get("include_activity_specific")), category=s.get("category") or None,
                      repeat_multiplier=s.get("repeat_multiplier"))


def _session(token: str) -> dict:
    if token not in SESSIONS:
        raise ServiceError(404, "انتهت الجلسة؛ ارفع الملف من جديد.")
    return SESSIONS[token]


def _store(gosi: pd.DataFrame, name: str, demo: bool) -> dict:
    if len(SESSIONS) >= MAX_SESSIONS:
        SESSIONS.pop(min(SESSIONS, key=lambda k: SESSIONS[k]["ts"]))
    token = secrets.token_urlsafe(16)
    SESSIONS[token] = {"gosi": gosi, "name": name, "demo": demo, "ts": time.time()}
    return {"token": token, "name": name, "rows": len(gosi), "demo": demo}


# ------------------------------------------------------------------
def get_rules() -> dict:
    return STATE["rules"]


def put_rules(rules: dict) -> dict:
    if C.RULES_READONLY:
        raise ServiceError(403, "تعديل القواعد معطّل في هذا الخادم (INVENU_RULES_READONLY=1).")
    errs = R.validate_rules(rules)
    if errs:
        raise ServiceError(422, {"errors": errs})
    R.save_rules(rules)
    STATE["rules"] = R.load_rules()
    return STATE["rules"]


def reset_rules() -> dict:
    STATE["rules"] = R.load_rules()
    return STATE["rules"]


def upload(content: bytes, filename: str | None) -> dict:
    # .xlsx فقط (بلا xlrd): الصيغ القديمة .xls وغيرها تُرفض برسالة واضحة بلغتين
    if not (filename or "").lower().endswith(".xlsx") or content[:2] != b"PK":
        raise ServiceError(400, {"ar": "الأداة تقبل ملفات Excel بصيغة .xlsx فقط. افتح الملف في Excel واحفظه بصيغة «مصنف Excel (.xlsx)» ثم ارفعه من جديد.",
                                 "en": "Only .xlsx Excel files are accepted. Open the file in Excel, save it as \"Excel Workbook (.xlsx)\", then upload it again."})
    try:
        gosi = D.read_gosi_file(io.BytesIO(content))
    except Exception as exc:
        raise ServiceError(400, str(exc))
    if gosi.empty:
        raise ServiceError(400, "لم يُعثر على موظفين في الملف بعد التنظيف.")
    return _store(gosi, filename or "GOSI.xlsx", False)


def demo() -> dict:
    return _store(P.demo_gosi(), "demo", True)


def analyze(token: str, settings: dict | None) -> dict:
    sess, s = _session(token), make_settings(settings)
    res = E.run(sess["gosi"], STATE["rules"], s)
    out = P.build_payload(res, STATE["rules"], s)
    out["file"] = {"name": sess["name"], "rows": len(sess["gosi"]), "demo": sess["demo"]}
    return out


def simulate(token: str, settings: dict | None, occupation: str | None, saudi: bool, wage: float, count: int,
             remove_ids: list[str] | None) -> dict:
    sess, s = _session(token), make_settings(settings)
    return P.simulate_payload(sess["gosi"], STATE["rules"], s, occupation, saudi, wage, count, remove_ids or [])


def report(token: str, settings: dict | None, lang: str) -> tuple[bytes, str]:
    """يعيد (محتوى ملف Excel، اسم الملف)."""
    sess, s = _session(token), make_settings(settings)
    data = reports.excel_report(E.run(sess["gosi"], STATE["rules"], s), lang)
    name = ("تقرير امتثال التوطين" if lang == "ar" else "Saudization compliance report") + f" {s.reference_date:%Y-%m-%d}.xlsx"
    return data, name


# ------------------------------------------------------------------ المستشار الذكي (AI)
_AI_STATUS = {"no_key": 422, "no_text": 422, "too_long": 413, "bad_key": 401, "rate_limited": 429, "network": 502, "provider_down": 502}


def _ai(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except AI.AIError as e:
        raise ServiceError(_AI_STATUS.get(e.code, 422), {"code": e.code, "ar": e.ar, "en": e.en})


def ai_extract(text: str, api_key: str, provider: str | None = None, model: str | None = None, transport=None) -> dict:
    """نص القرار ← مسودة قاعدة للمراجعة. لا يمس القواعد ولا الجلسات، ولا يحتفظ بالمفتاح."""
    return _ai(AI.extract_rule, text, api_key, provider, model, transport)


def ai_request(text: str, api_key: str, provider: str | None = None, model: str | None = None) -> dict:
    """نسخة المتصفح: طلب HTTP جاهز يرسله bridge.js عبر fetch (المتصفح لا يستطيع الاتصال من داخل Python)."""
    return _ai(AI.build_request, text, api_key, provider, model)


def ai_response(provider: str, status: int, raw: str) -> dict:
    """نسخة المتصفح: ردّ المزوّد ← مسودة (نفس تحليل الخادم)."""
    return _ai(AI.read_response, provider, status, raw)


def approve_draft(draft: dict) -> dict:
    """يضيف مسودة (بعد مراجعة المستخدم وتعديله) إلى القواعد عبر مسار الحفظ والتحقق المعتاد."""
    g, profs = (draft or {}).get("group"), (draft or {}).get("professions") or []
    if not isinstance(g, dict):
        raise ServiceError(422, {"ar": "المسودة فارغة.", "en": "The draft is empty."})
    rules = copy.deepcopy(STATE["rules"])
    if g.get("id") in {x["id"] for x in rules["groups"]}:
        raise ServiceError(409, {"ar": f"المعرّف «{g.get('id')}» مستخدم لمجموعة موجودة؛ غيّر المعرّف.",
                                 "en": f"The id \"{g.get('id')}\" belongs to an existing group; change the id."})
    if not str(g.get("name") or "").strip():
        raise ServiceError(422, {"ar": "اسم المجموعة مطلوب.", "en": "The group name is required."})
    g = {k: v for k, v in g.items() if not (k == "min_establishment_size" and not v)}
    rules["groups"].append(g)
    rules["professions"].extend({"title": p["title"].strip(), "code": str(p.get("code") or ""), "group": g["id"], "effective_date": None,
                                 "subgroup": None, "aliases": []} for p in profs if str(p.get("title") or "").strip())
    return put_rules(rules)
