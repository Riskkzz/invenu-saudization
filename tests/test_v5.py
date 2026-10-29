"""اختبارات v5: رفع .xlsx فقط، المهن غير المشمولة، والمستشار الذكي (AI) (بنقل وهمي — لا اتصال شبكي فعلي)."""
import copy
import io
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "web")]
from backend import ai_service as AI  # noqa: E402
from backend import service as SV  # noqa: E402
from backend.service import ServiceError  # noqa: E402
import invenu_web_bridge as W  # noqa: E402

COLS = ["اسم المشترك", "رقم الهوية", "الجنسية", "المهنة", "الأجر الأساسي", "إجمالي الأجر", "الاجر الخاضع للاشتراك"]


def xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["تقرير المشتركين النشطين"])
    ws.append([])
    ws.append(COLS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [["موظف 1", 1000000001, "السعودية", "أخصائي تسويق", 7000, 8000, 7000],
        ["موظف 2", 1000000002, "الهند", "مصمم جرافيك", 6000, 7000, 6000],
        ["موظف 3", 1000000003, "مصر", "وظيفة غير موجودة في القرارات", 5000, 6000, 5000],
        ["موظف 4", 1000000004, "السعودية", "مسمى عام آخر", 5000, 6000, 5000]]


# ---------------------------------------------------------------- .xlsx فقط
@pytest.mark.parametrize("name", ["old.xls", "data.csv", "file.xlsb", "noext", "report.xlsx.xls"])
def test_non_xlsx_rejected_with_bilingual_message(name):
    with pytest.raises(ServiceError) as e:
        SV.upload(xlsx_bytes(ROWS), name)
    assert e.value.status == 400 and ".xlsx" in e.value.detail["ar"] and ".xlsx" in e.value.detail["en"]


def test_xls_content_with_xlsx_name_rejected():
    with pytest.raises(ServiceError) as e:
        SV.upload(b"\xd0\xcf\x11\xe0" + b"0" * 100, "fake.xlsx")        # توقيع OLE لملف .xls قديم
    assert e.value.status == 400


def test_valid_xlsx_accepted():
    assert SV.upload(xlsx_bytes(ROWS), "GOSI.XLSX")["rows"] == 4


# ---------------------------------------------------------------- المهن غير المشمولة
def test_uncovered_split_adds_up_and_lists_the_right_people():
    tok = SV.upload(xlsx_bytes(ROWS), "g.xlsx")["token"]
    a = SV.analyze(tok, {"reference_date": "2026-10-23"})
    s = a["summary"]
    assert s["total"] == s["in_scope"] + s["out_of_scope"] == 4 and s["out_of_scope"] == 2
    assert {u["occupation"] for u in a["uncovered"]} == {"وظيفة غير موجودة في القرارات", "مسمى عام آخر"}
    assert len(a["uncovered"]) == s["out_of_scope"]
    assert all({"id", "name", "nationality", "occupation", "suggestion"} <= set(u) for u in a["uncovered"])
    assert all(u["id"] not in {i for g in a["groups"] for i in g["employee_ids"]} for u in a["uncovered"])


def test_demo_uncovered_matches_summary():
    a = SV.analyze(SV.demo()["token"], {"reference_date": "2026-10-23"})
    assert len(a["uncovered"]) == a["summary"]["out_of_scope"] > 0


# ---------------------------------------------------------------- المستشار الذكي (AI)
MODEL_REPLY = {"group": {"id": "Test Group!", "name": "مجموعة اختبار", "name_en": "Test group", "scope": "group", "min_headcount": 4,
                         "min_establishment_size": None, "phases": [{"effective_date": "2027-03-01", "ratio": 0.55}],
                         "min_wage": {"default": 5000}, "decision": "القرار 1 (01/01/2027)", "decision_en": "Decision 1",
                         "source_url": "", "notes": ""},
               "professions": [{"title": "مهنة اختبار", "code": "999001"}, {"title": "  ", "code": ""}]}


def test_prompt_demands_json_only_and_carries_no_key_or_employee_data():
    msgs = AI.build_messages("نص القرار")
    assert msgs[0]["role"] == "system" and "ONLY a single JSON object" in msgs[0]["content"]
    for field in ("id", "name", "ratio", "effective_date", "min_headcount", "min_wage"):
        assert field in msgs[0]["content"]
    assert "نص القرار" in msgs[1]["content"]


def test_extract_requires_key_and_text():
    with pytest.raises(AI.AIError) as e:
        AI.extract_rule("نص", "  ")
    assert e.value.code == "no_key"
    with pytest.raises(AI.AIError) as e:
        AI.extract_rule("  ", "k")
    assert e.value.code == "no_text"


def anthropic_reply(obj, stop="end_turn"):
    return json.dumps({"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)}],
                       "stop_reason": stop}, ensure_ascii=False)


def openai_reply(obj):
    return json.dumps({"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]}, ensure_ascii=False)


def fake_ok(req):
    return 200, (anthropic_reply if req["provider"] == "anthropic" else openai_reply)(MODEL_REPLY)


def test_requests_are_built_for_each_provider_and_only_carry_the_decision_text():
    a = AI.build_request("نص القرار", "sk-ant-abc")
    assert a["provider"] == "anthropic" and a["url"] == "https://api.anthropic.com/v1/messages"
    assert a["headers"]["x-api-key"] == "sk-ant-abc" and a["headers"]["anthropic-dangerous-direct-browser-access"] == "true"
    assert a["body"]["model"] == "claude-opus-5-5" and a["body"]["system"] == AI.SYSTEM_PROMPT and "temperature" not in a["body"]
    assert "نص القرار" in a["body"]["messages"][0]["content"] and "sk-ant-abc" not in json.dumps(a["body"])
    o = AI.build_request("نص القرار", "sk-proj-xyz", model="my-model")
    assert o["provider"] == "openai" and o["url"] == "https://api.openai.com/v1/chat/completions"
    assert o["headers"]["authorization"] == "Bearer sk-proj-xyz" and o["body"]["model"] == "my-model"
    assert o["body"]["response_format"] == {"type": "json_object"} and "sk-proj-xyz" not in json.dumps(o["body"])
    assert AI.build_request("x", "sk-proj-1", provider="anthropic")["provider"] == "anthropic"     # اختيار صريح يغلب التخمين
    assert AI.PROVIDER_ORIGINS == ["https://api.anthropic.com", "https://api.openai.com"]


@pytest.mark.parametrize("status,code,http", [(0, "network", 502), (401, "bad_key", 401), (403, "bad_key", 401), (429, "rate_limited", 429),
                                              (503, "provider_down", 502), (400, "provider_error", 422)])
def test_provider_errors_are_mapped_to_clear_bilingual_messages(status, code, http):
    raw = json.dumps({"error": {"message": "model not found"}})
    with pytest.raises(ServiceError) as e:
        SV.ai_extract("نص", "sk-ant-secret", transport=lambda req: (status, raw))
    assert e.value.status == http and e.value.detail["code"] == code and e.value.detail["ar"] and e.value.detail["en"]
    assert "sk-ant-secret" not in json.dumps(e.value.detail, ensure_ascii=False)


def test_refusal_is_reported():
    with pytest.raises(AI.AIError) as e:
        AI.read_response("anthropic", 200, anthropic_reply("", stop="refusal"))
    assert e.value.code == "refused"


def test_default_transport_posts_with_urllib(monkeypatch):
    seen = {}

    class Resp:
        status = 200

        def read(self):
            return anthropic_reply(MODEL_REPLY).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data))
        return Resp()
    monkeypatch.setattr(AI.urllib.request, "urlopen", urlopen)
    out = SV.ai_extract("نص قرار", "sk-ant-k")
    assert seen["url"] == AI.PROVIDERS["anthropic"]["url"] and seen["headers"]["X-api-key"] == "sk-ant-k"
    assert out["draft"]["group"]["id"] == "test_group"


def test_browser_csp_allows_only_self_and_the_two_providers():
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_web as B
    csp = B.csp_for("<html><script>x</script></html>")
    connect = next(d for d in csp.split(";") if d.strip().startswith("connect-src")).split()[1:]
    assert connect == ["'self'", "https://api.anthropic.com", "https://api.openai.com"]


@pytest.mark.parametrize("fmt", [anthropic_reply, openai_reply])
def test_both_reply_formats_parse(fmt):
    provider = "anthropic" if fmt is anthropic_reply else "openai"
    assert AI.read_response(provider, 200, fmt(MODEL_REPLY))["draft"]["group"]["name"] == "مجموعة اختبار"


def test_extract_with_fake_transport_returns_normalised_unverified_draft():
    seen = {}

    def fake(req):
        seen["req"] = req
        return 200, anthropic_reply("```json\n" + json.dumps(MODEL_REPLY, ensure_ascii=False) + "\n```")     # النماذج تلف الرد بسياج أحياناً
    out = SV.ai_extract("نص قرار", "sk-ant-secret-123", transport=fake)
    g = out["draft"]["group"]
    assert g["id"] == "test_group" and g["verified"] is False and g["min_headcount"] == 4
    assert g["phases"] == [{"effective_date": "2027-03-01", "ratio": 0.55}] and g["min_wage"] == {"default": 5000.0}
    assert out["draft"]["professions"] == [{"title": "مهنة اختبار", "code": "999001"}]
    assert "sk-ant-secret-123" not in json.dumps(seen["req"]["body"]) and "sk-ant-secret-123" not in json.dumps(out)


def test_percent_ratio_is_converted_and_flagged():
    r = copy.deepcopy(MODEL_REPLY)
    r["group"]["phases"][0]["ratio"] = 55
    out = AI.parse_model_output(json.dumps(r))
    assert out["draft"]["group"]["phases"][0]["ratio"] == 0.55 and "ratio_percent" in out["warnings"]


@pytest.mark.parametrize("raw,code", [("not json at all", "bad_json"), ("[1,2]", "bad_json"), ('{"group": null, "professions": []}', "no_decision")])
def test_bad_model_output_is_rejected(raw, code):
    with pytest.raises(AI.AIError) as e:
        AI.parse_model_output(raw)
    assert e.value.code == code


@pytest.fixture
def isolated_rules(monkeypatch):
    """يمنع الكتابة على ملف القواعد الحقيقي أثناء الاختبار."""
    base, holder = copy.deepcopy(SV.STATE["rules"]), {}
    monkeypatch.setattr(SV.R, "save_rules", lambda rules, *a, **k: holder.__setitem__("r", copy.deepcopy(rules)))
    monkeypatch.setattr(SV.R, "load_rules", lambda *a, **k: copy.deepcopy(holder.get("r", base)))
    yield holder
    SV.STATE["rules"] = base


def test_extraction_never_saves_and_approval_adds_group_and_professions(isolated_rules):
    before = copy.deepcopy(SV.STATE["rules"])
    draft = SV.ai_extract("نص قرار", "k", transport=fake_ok)["draft"]
    assert isolated_rules == {} and SV.STATE["rules"] == before                 # المسودة لا تمس القواعد
    rules = SV.approve_draft({"group": draft["group"], "professions": draft["professions"]})
    assert rules["groups"][-1]["id"] == "test_group" and rules["groups"][-1]["verified"] is False
    assert {"title": "مهنة اختبار", "code": "999001", "group": "test_group", "effective_date": None, "subgroup": None, "aliases": []} in rules["professions"]
    assert len(rules["groups"]) == len(before["groups"]) + 1


def test_approved_group_takes_part_in_analysis(isolated_rules):
    SV.approve_draft({"group": AI.parse_model_output(json.dumps(MODEL_REPLY))["draft"]["group"], "professions": [{"title": "وظيفة غير موجودة في القرارات", "code": ""}]})
    tok = SV.upload(xlsx_bytes(ROWS), "g.xlsx")["token"]
    a = SV.analyze(tok, {"reference_date": "2027-04-01"})
    assert a["summary"]["out_of_scope"] == 1 and "test_group" in {g["unit_id"] for g in a["groups"]}


def test_approval_rejects_duplicates_and_invalid_drafts(isolated_rules):
    g = AI.parse_model_output(json.dumps(MODEL_REPLY))["draft"]["group"]
    with pytest.raises(ServiceError) as e:
        SV.approve_draft({"group": {**g, "id": "marketing"}, "professions": []})
    assert e.value.status == 409
    with pytest.raises(ServiceError) as e:
        SV.approve_draft({"group": {**g, "phases": [{"effective_date": "2027-01-01", "ratio": 7}]}, "professions": []})
    assert e.value.status == 422
    with pytest.raises(ServiceError):
        SV.approve_draft({"group": {**g, "name": " "}, "professions": []})
    assert isolated_rules == {}


# ---------------------------------------------------------------- جسر المتصفح (نفس المسارات)
def test_web_bridge_routes(isolated_rules):
    class JsBytes:
        def to_bytes(self):
            return xlsx_bytes(ROWS)
    assert json.loads(W.upload(JsBytes(), "x.xls"))["status"] == 400
    assert json.loads(W.upload(JsBytes(), "x.xlsx"))["status"] == 200
    r = json.loads(W.ai_request(json.dumps({"text": "نص", "api_key": "sk-ant-k"})))
    assert r["status"] == 200 and r["body"]["url"].startswith("https://api.anthropic.com/")
    assert json.loads(W.ai_request(json.dumps({"text": "نص", "api_key": ""})))["status"] == 422
    ok = json.loads(W.ai_response("anthropic", 200, anthropic_reply(MODEL_REPLY)))
    assert ok["status"] == 200 and ok["body"]["draft"]["group"]["id"] == "test_group"
    assert json.loads(W.ai_response("openai", 0, ""))["status"] == 502
    g = AI.parse_model_output(json.dumps(MODEL_REPLY))["draft"]["group"]
    r = json.loads(W.call("POST", "/api/rules/groups", json.dumps({"group": g, "professions": []})))
    assert r["status"] == 200 and r["body"]["groups"][-1]["id"] == "test_group"


# ---------------------------------------------------------------- v5.1: القواعد المؤكدة والغرامات الرسمية
def test_confirmed_groups_and_official_penalties():
    R = SV.R.load_rules()
    g = {x["id"]: x for x in R["groups"]}
    assert g["project_management"]["verified"] and g["project_management"]["min_headcount"] == 3
    assert g["legal"]["verified"] and g["legal"]["min_headcount"] == 1
    pen = R["penalties"]
    # القرار 112377، البندان 29 و30 (فئة المخالفات العامة): ج ≤20، ب 21–49، أ 50+
    assert pen["verified"] and pen["source_url"].endswith("qrar-wzary---112377.pdf")
    assert pen["per_category"] == {"أ": {"restricted": 10000, "ratio": 6000}, "ب": {"restricted": 5000, "ratio": 4000},
                                   "ج": {"restricted": 3000, "ratio": 2000}}


def test_penalties_follow_rules_and_are_editable():
    tok = SV.demo()["token"]
    a = SV.analyze(tok, {"reference_date": "2026-10-28", "category": "أ"})
    assert {p["rate"] for p in a["penalties"] if p["type"] == "restricted"} == {10000.0}
    assert a["penalties_verified"] is True


def test_edited_penalty_amount_is_used(isolated_rules):
    rules = copy.deepcopy(SV.STATE["rules"])
    rules["penalties"]["per_category"]["أ"]["restricted"] = 12345
    SV.put_rules(rules)                                             # نفس مسار «حفظ» في تبويب إعدادات القواعد
    a = SV.analyze(SV.demo()["token"], {"reference_date": "2026-10-28", "category": "أ"})
    assert {p["rate"] for p in a["penalties"] if p["type"] == "restricted"} == {12345.0}


# ---------------------------------------------------------------- v5.2: هوية INVENU وتوحيد التسمية
def _frontend_text():
    return {f: f.read_text(encoding="utf-8") for f in (ROOT / "frontend").rglob("*") if f.suffix in {".css", ".js", ".html", ".svg"}}


def _is_yellowish(hex6):
    import colorsys
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    return 35 <= h * 360 <= 70 and s > 0.25            # الأصفر والذهبي والخردلي (الرماديات الدافئة تشبعها ≤ 0.1)


def test_no_yellow_anywhere_in_the_frontend():
    import re
    for f, t in _frontend_text().items():
        for c in re.findall(r"#([0-9A-Fa-f]{6})\b", t):
            assert not _is_yellowish(c), f"{f.name}: #{c}"
        assert "#F2CD01" not in t.upper(), f.name


def test_brand_tokens_font_and_purple_buttons():
    css = (ROOT / "frontend" / "css" / "styles.css").read_text(encoding="utf-8")
    for token in ("--bg:#E7E6E4", "--ink:#100F0D", "--mauve:#7B5AB7", "--mauve-ink:#5E4291", "--mauve-soft:#EEE7F8"):
        assert token in css
    assert '--font:"IBM Plex Sans Arabic"' in css
    assert ".btn{border:1px solid var(--mauve);background:var(--mauve)" in css        # الأزرار الأساسية بالبنفسجي
    assert ".dot.grace{background:var(--mauve)}" in css and ".pill.grace{background:var(--mauve-soft);color:var(--mauve-ink)}" in css


def test_smart_advisor_name_is_unified():
    txt = "\n".join(_frontend_text().values())
    assert "مولّد القواعد" not in txt and "rule builder" not in txt.lower()
    assert 'tab_ai: "المستشار الذكي (AI)"' in txt and 'tab_ai: "Smart Advisor (AI)"' in txt


def test_project_management_and_legal_confirmed_in_full():
    g = {x["id"]: x for x in SV.R.load_rules()["groups"]}
    pm, lg = g["project_management"], g["legal"]
    assert pm["verified"] and pm["min_wage"] == {"default": 6000} and [p["ratio"] for p in pm["phases"]] == [0.4, 0.7]
    assert lg["verified"] and lg["min_wage"] == {"default": 5500} and [p["ratio"] for p in lg["phases"]] == [0.7]
