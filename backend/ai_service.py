"""
ai_service.py — المستشار الذكي (AI): قواعد توطين من نص القرار الوزاري
======================================================================
يأخذ «نص القرار الوزاري» ومفتاح API، ويجهّز طلب النموذج اللغوي (System Prompt هندسي)، ثم يحوّل ردّ النموذج
إلى **مسودة** قاعدة بنفس هيكلة rules/saudization_rules.json. المسودة لا تُحفظ تلقائياً أبداً: تُعرض في نموذج
مراجعة، ولا تدخل القواعد إلا بعد اعتماد المستخدم (service.approve_draft).

الخصوصية (القسم 7 من HANDOFF):
  • هذه الدالة لا ترى ملف التأمينات إطلاقاً؛ تستقبل نص القرار فقط (نص عام منشور).
  • المفتاح يمرّ في الذاكرة لكل طلب ولا يُخزَّن ولا يُكتب في سجل ولا في ملف القواعد.
  • الاتصال الخارجي الوحيد في الأداة: نص القرار يُرسل إلى مزوّد واحد من PROVIDERS (Anthropic أو OpenAI) بمفتاح
    المستخدم. سياسة CSP في نسخة المتصفح تسمح بأصول PROVIDERS فقط، وتمنع أي جهة أخرى.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

SYSTEM_PROMPT = """You are a data-extraction engine for Saudi labour-localisation (Saudization) ministerial decisions
issued by the Ministry of Human Resources and Social Development (HRSD).

TASK: read the decision text supplied by the user and extract ONE occupational group rule.
Return ONLY a single JSON object. No prose, no markdown, no code fences, no comments.

OUTPUT SCHEMA (exact keys):
{
  "group": {
    "id":        string  // lowercase snake_case ASCII slug derived from the English name, e.g. "project_management"
    "name":      string  // group name in Arabic exactly as in the decision (e.g. "التسويق")
    "name_en":   string  // English name
    "scope":     "group" | "subgroup" | "restricted"
                         // "restricted" ONLY if the decision limits the professions to Saudis 100 % and
                         // violations are counted per worker; "subgroup" if each sub-group is counted separately;
                         // otherwise "group"
    "min_headcount": integer >= 1
                         // the blocking threshold: the decision applies only if the establishment has at least this
                         // many workers in the group's professions
    "min_establishment_size": integer | null
                         // minimum TOTAL workers in the establishment, if the decision states one; else null
    "phases": [ { "effective_date": "YYYY-MM-DD", "ratio": number } ]
                         // one entry per stage; ratio is a FRACTION between 0 and 1 (60 % -> 0.6);
                         // effective_date is Gregorian ISO 8601 (convert from Hijri or Arabic-Indic digits if needed)
    "min_wage":  { "default": number } | { "bachelor": number, "diploma": number } | null
                         // minimum monthly wage in SAR for a Saudi to be counted; null if none is stated
    "decision":    string  // decision number and date in Arabic, e.g. "القرار الوزاري 101319 (19/01/2026)"
    "decision_en": string  // the same in English
    "source_url":  string  // only if a URL appears in the text; else ""
    "notes":       string  // short caveats worth a human reviewer's attention; else ""
  },
  "professions": [ { "title": string, "code": string } ]
                         // occupation titles (Arabic, as written) and their occupation codes if listed; [] if none
}

RULES:
1. Extract ONLY what the text explicitly states. Never infer, estimate or recall values from memory.
2. If a field is not stated, use null (or "" for strings, [] for lists). Never invent a number or a date.
3. Never output a field that is not in the schema.
4. If the text contains no localisation decision, return {"group": null, "professions": []}.
"""

PROMPT_VERSION = "2"
MAX_TEXT_CHARS = 60_000
TIMEOUT_S = 180

# المزوّدون المسموح بهم. أصل كل رابط هنا هو الاستثناء الوحيد في سياسة CSP لنسخة المتصفح (build_web.py يقرؤه من هنا).
# الطلب مبني بـ HTTP خام (لا SDK) لأن نسخة المتصفح ترسله عبر fetch من JavaScript، والطلب نفسه يُبنى هنا مرة واحدة للبيئتين.
PROVIDERS = {
    "anthropic": {"url": "https://api.anthropic.com/v1/messages", "model": "claude-opus-5-5"},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4.1"},
}
ANTHROPIC_VERSION = "2026-10-21"
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"      # عند رفض النموذج لأسباب السلامة يُعاد الطلب تلقائياً على نموذج بديل
PROVIDER_ORIGINS = sorted({"/".join(p["url"].split("/")[:3]) for p in PROVIDERS.values()})

# transport(request) -> (http_status, response_text); status 0 = تعذّر الاتصال
Transport = Callable[[dict], Tuple[int, str]]


class AIError(Exception):
    """خطأ موجّه للمستخدم بلغتين: (code, ar, en)."""

    def __init__(self, code: str, ar: str, en: str):
        super().__init__(en)
        self.code, self.ar, self.en = code, ar, en


def build_messages(decision_text: str) -> list:
    """رسائل الطلب (system + user). لا تحتوي المفتاح."""
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "DECISION TEXT:\n<<<\n" + decision_text.strip() + "\n>>>"}]


def detect_provider(api_key: str, provider: Optional[str] = None) -> str:
    if provider in PROVIDERS:
        return provider
    return "anthropic" if api_key.strip().startswith("sk-ant-") else "openai"


def build_request(text: str, api_key: str, provider: Optional[str] = None, model: Optional[str] = None) -> dict:
    """يتحقق من المدخلات ويبني طلب HTTP كاملاً {provider, url, headers, body}. يُرسله الخادم (urllib) أو المتصفح (fetch)."""
    key = (api_key or "").strip()
    if not key:
        raise AIError("no_key", "أدخل مفتاح API أولاً من «إعدادات القواعد»، قسم «مفتاح API للمستشار الذكي (AI)».",
                      "Enter an API key first in Rules settings, under \"API key for the Smart Advisor (AI)\".")
    if not (text or "").strip():
        raise AIError("no_text", "الصق نص القرار الوزاري أولاً.", "Paste the ministerial decision text first.")
    if len(text) > MAX_TEXT_CHARS:
        raise AIError("too_long", f"النص طويل جداً (الحد {MAX_TEXT_CHARS:,} حرفاً).", f"The text is too long (limit {MAX_TEXT_CHARS:,} characters).")
    prov = detect_provider(key, provider)
    spec, (system, user) = PROVIDERS[prov], build_messages(text)
    mdl = (model or "").strip() or spec["model"]
    if prov == "anthropic":
        headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
                   "anthropic-beta": ANTHROPIC_FALLBACK_BETA,
                   "anthropic-dangerous-direct-browser-access": "true"}          # مطلوب لطلبات المتصفح المباشرة (CORS)
        body = {"model": mdl, "max_tokens": 16000, "system": system["content"], "messages": [user],
                "output_config": {"effort": "medium"}, "fallbacks": "default"}
    else:
        headers = {"content-type": "application/json", "authorization": f"Bearer {key}"}
        body = {"model": mdl, "messages": [system, user], "response_format": {"type": "json_object"}}
    return {"provider": prov, "url": spec["url"], "headers": headers, "body": body}


def _provider_message(raw: str) -> str:
    try:
        err = json.loads(raw).get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        return str(msg or "")[:300]
    except (ValueError, AttributeError):
        return ""


def read_response(provider: str, status: int, raw: str) -> dict:
    """يحوّل ردّ HTTP من المزوّد إلى مسودة (parse_model_output) أو يرفع AIError بلغتين. لا يتضمن المفتاح أبداً."""
    if status == 0:
        # في المتصفح: OpenAI لا يرسل ترويسة CORS مع ردود الخطأ (مثل 401)، فيظهر المفتاح الخاطئ كتعذّر اتصال
        raise AIError("network", "تعذّر الاتصال بمزوّد الذكاء الاصطناعي، أو رفض المزوّد المفتاح. تحقق من اتصال الإنترنت ومن صحة المفتاح والمزوّد، ثم أعد المحاولة.",
                      "Could not reach the AI provider, or the provider rejected the key. Check your internet connection, the key and the provider, then try again.")
    if status in (401, 403):
        raise AIError("bad_key", "المفتاح غير صالح أو لا يملك صلاحية. تحقق منه ومن اختيار المزوّد.",
                      "The key is invalid or lacks permission. Check it and the selected provider.")
    if status == 429:
        raise AIError("rate_limited", "تجاوزت حد الطلبات أو الرصيد لدى المزوّد. انتظر قليلاً ثم أعد المحاولة.",
                      "Rate or credit limit reached at the provider. Wait a moment and try again.")
    if status >= 500:
        raise AIError("provider_down", "خدمة المزوّد غير متاحة الآن. أعد المحاولة لاحقاً.", "The provider service is unavailable. Try again later.")
    if status != 200:
        m = _provider_message(raw)
        raise AIError("provider_error", f"رفض المزوّد الطلب ({status}). {m}", f"The provider rejected the request ({status}). {m}")
    try:
        data = json.loads(raw)
    except ValueError:
        raise AIError("bad_json", "ردّ المزوّد غير مفهوم.", "The provider reply could not be read.")
    if provider == "anthropic":
        if data.get("stop_reason") == "refusal":
            raise AIError("refused", "امتنع النموذج عن معالجة هذا النص.", "The model declined to process this text.")
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
    else:
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return parse_model_output(text)


def _urllib_transport(req: dict) -> Tuple[int, str]:
    """النقل في الخادم المحلي / Docker. نسخة المتصفح لا تستخدمه (bridge.js يرسل الطلب نفسه عبر fetch)."""
    r = urllib.request.Request(req["url"], data=json.dumps(req["body"]).encode(), headers=req["headers"], method="POST")
    try:
        with urllib.request.urlopen(r, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return 0, ""


def extract_rule(text: str, api_key: str, provider: Optional[str] = None, model: Optional[str] = None,
                 transport: Optional[Transport] = None) -> dict:
    """يعيد {'draft': {...}, 'warnings': [...]} أو يرفع AIError. لا يحفظ شيئاً."""
    req = build_request(text, api_key, provider, model)
    status, raw = (transport or _urllib_transport)(req)
    return read_response(req["provider"], status, raw)


# ------------------------------------------------------------------
def _json_object(raw: str) -> dict:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)          # نماذج كثيرة تلف الرد بسياج رغم التعليمات
    if not s.startswith("{"):
        a, b = s.find("{"), s.rfind("}")
        s = s[a:b + 1] if a != -1 and b > a else s
    try:
        obj = json.loads(s)
    except ValueError:
        raise AIError("bad_json", "ردّ النموذج ليس JSON صالحاً. أعد المحاولة أو أدخل القاعدة يدوياً.",
                      "The model reply is not valid JSON. Try again or enter the rule manually.")
    if not isinstance(obj, dict):
        raise AIError("bad_json", "ردّ النموذج ليس كائن JSON.", "The model reply is not a JSON object.")
    return obj


def parse_model_output(raw: str) -> dict:
    """يحوّل ردّ النموذج إلى مسودة مطبَّعة بهيكلة القواعد + تحذيرات للمراجعة. لا يُحفظ شيء هنا."""
    obj = _json_object(raw)
    g = obj.get("group")
    if not isinstance(g, dict):
        raise AIError("no_decision", "لم يعثر النموذج على قرار توطين في النص.", "The model found no localisation decision in the text.")
    warnings: list = []

    ratio_fix = False
    phases = []
    for p in g.get("phases") or []:
        try:
            r = float(p.get("ratio"))
        except (TypeError, ValueError):
            continue
        if 1 < r <= 100:                                  # «60» بدل 0.6
            r, ratio_fix = r / 100, True
        phases.append({"effective_date": str(p.get("effective_date") or ""), "ratio": r})
    if ratio_fix:
        warnings.append("ratio_percent")
    mw = g.get("min_wage")
    if isinstance(mw, dict):
        mw = {k: float(v) for k, v in mw.items() if k in ("default", "bachelor", "diploma") and isinstance(v, (int, float))} or None
    else:
        mw = None
    est = g.get("min_establishment_size")
    scope = g.get("scope") if g.get("scope") in ("group", "subgroup", "restricted") else "group"
    if scope != g.get("scope"):
        warnings.append("scope_defaulted")

    def s(k):
        return str(g.get(k) or "").strip()

    try:
        headcount = int(g.get("min_headcount"))
    except (TypeError, ValueError):
        headcount = None
        warnings.append("headcount_missing")
    draft = {
        "group": {"id": re.sub(r"[^a-z0-9_]+", "_", s("id").lower()).strip("_") or "new_group", "name": s("name"), "name_en": s("name_en"),
                  "scope": scope, "min_headcount": headcount if headcount and headcount >= 1 else 1,
                  "min_establishment_size": int(est) if isinstance(est, (int, float)) and est > 0 else None,
                  "phases": phases, "min_wage": mw, "decision": s("decision"), "decision_en": s("decision_en"),
                  "source_title": "", "source_url": s("source_url"), "notes": s("notes"),
                  "accreditation": "", "activity_specific": False, "enabled": True,
                  "verified": False},                    # مسودة ذكاء اصطناعي: لا تُوثَّق إلا بتأكيد بشري من المصدر الرسمي
        "professions": [{"title": str(p.get("title") or "").strip(), "code": str(p.get("code") or "").strip()}
                        for p in obj.get("professions") or [] if isinstance(p, dict) and str(p.get("title") or "").strip()],
    }
    if not phases:
        warnings.append("phases_missing")
    return {"draft": draft, "warnings": warnings}
