"""
presenter.py — تحويل نتائج المحرك إلى JSON للواجهة
====================================================
الواجهة ثنائية اللغة، لذلك لا تُرسل نصوص جاهزة: التوصيات والمواعيد تُرسل كأنواع + معاملات
(kind + params) وتصوغها الواجهة بالعربية أو الإنجليزية.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import engine as E
from . import insights as I
from .data_loader import make_employee_row


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return None if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%d")
    if v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(float(v)) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


# ------------------------------------------------------------------
def _employees(df: pd.DataFrame) -> dict:
    out = {}
    for _, e in df.iterrows():
        out[e["رقم الهوية"]] = {
            "id": e["رقم الهوية"], "name": e["اسم المشترك"], "nationality": e["الجنسية"], "saudi": bool(e["سعودي"]),
            "occupation": e["المهنة"], "basic": e["الأجر الأساسي"], "total": e["إجمالي الأجر"], "subject": e["الاجر الخاضع للاشتراك"],
            "min_wage": e["min_wage"], "wage_ok": bool(e["أجر مطابق"]), "counted": bool(e["سعودي"] and e["وزن الاحتساب"] >= 1),
            "weight": e["وزن الاحتساب"], "unit_id": e["unit_id"], "profession": e["profession"], "code": e["code"],
            "upcoming_group": e["upcoming_group_id"], "upcoming_date": e["upcoming_date"], "member_date": e["member_date"],
            "joined": e.get("تاريخ الإلتحاق"),
        }
    return out


def _groups(res: dict) -> list[dict]:
    df, units = res["df"], res["units"]
    out = []
    for _, u in units.iterrows():
        m = df[df["unit_id"] == u["unit_id"]]
        occs = []
        for title, x in m.groupby("profession"):
            occs.append({"title": title, "code": x["code"].iloc[0], "n": len(x), "saudi": int(x["سعودي"].sum()),
                         "counted": float(x["وزن الاحتساب"].sum()), "non_saudi": int((~x["سعودي"]).sum()),
                         "under_wage": int((x["سعودي"] & ~x["أجر مطابق"]).sum()), "employee_ids": x["رقم الهوية"].tolist()})
        occs.sort(key=lambda o: -o["n"])
        d = {k: u[k] for k in ["unit_id", "unit", "unit_en", "group_id", "scope", "status", "n", "saudi", "counted", "non_saudi",
                               "under_wage", "ratio", "current_pct", "required", "shortfall", "headroom", "surplus", "threshold",
                               "applicable", "enforced", "compliant", "effective", "next_ratio", "next_date", "next_shortfall",
                               "hire_only", "fixed_shortfall", "min_wage", "source_url", "source_title", "decision", "decision_en", "verified",
                               "accreditation", "violator_ids", "upcoming_ids", "upcoming_violations", "at_threshold",
                               "establishment_total", "establishment_threshold", "establishment_ok"]}
        d["occupations"] = occs
        d["employee_ids"] = m["رقم الهوية"].tolist()
        out.append(d)
    return out


def _recommendations(res: dict) -> list[dict]:
    """نفس منطق engine.build_recommendations لكن كأنواع ومعاملات (للترجمة في الواجهة)."""
    df, units, recs = res["df"], res["units"], []
    emp = df.set_index("رقم الهوية")
    for _, u in units.iterrows():
        unit = {"ar": u["unit"], "en": u["unit_en"]}
        if u["scope"] == "restricted":
            for ids, active in ((u["violator_ids"], True), (u["upcoming_ids"], False)):
                for i in ids:
                    e = emp.loc[i]
                    when = e["member_date"] if active or pd.isna(e["upcoming_date"]) else e["upcoming_date"]
                    recs.append({"kind": "restricted", "priority": "urgent" if active else "proactive", "unit": unit,
                                 "params": {"id": i, "name": e["اسم المشترك"], "nationality": e["الجنسية"], "occupation": e["المهنة"],
                                            "date": when, "active": active}})
            continue
        if u["applicable"] and not u["compliant"]:
            recs.append({"kind": "shortfall", "priority": "urgent" if u["enforced"] else "proactive", "unit": unit,
                         "params": {k: u[k] for k in ["shortfall", "required", "ratio", "n", "counted", "hire_only", "under_wage",
                                                      "min_wage", "fixed_shortfall", "enforced", "effective"]}})
        elif u["applicable"] and u["headroom"] <= 1 and u["ratio"] < 1:
            recs.append({"kind": "thin_margin", "priority": "proactive", "unit": unit,
                         "params": {"headroom": u["headroom"], "min_wage": u["min_wage"], "surplus": u["surplus"]}})
        if u["applicable"] and pd.notna(u["next_ratio"]) and u["next_shortfall"] and u["next_shortfall"] > 0:
            recs.append({"kind": "next_phase", "priority": "proactive", "unit": unit,
                         "params": {"next_ratio": u["next_ratio"], "next_date": u["next_date"], "next_shortfall": u["next_shortfall"],
                                    "n": u["n"], "counted": u["counted"]}})
        if not u["establishment_ok"]:
            recs.append({"kind": "below_establishment", "priority": "proactive", "unit": unit,
                         "params": {"total": u["establishment_total"], "threshold": u["establishment_threshold"], "ratio": u["ratio"]}})
        if not u["applicable"] and u["at_threshold"]:
            recs.append({"kind": "near_threshold", "priority": "proactive", "unit": unit,
                         "params": {"n": u["n"], "threshold": u["threshold"], "left": u["threshold"] - u["n"],
                                    "required": u["at_threshold"]["required"], "ratio": u["ratio"], "counted": u["counted"]}})
        if u["applicable"] and u["accreditation"]:
            recs.append({"kind": "accreditation", "priority": "proactive", "unit": unit, "params": {"body": u["accreditation"]}})
    wc = I.wage_corrections(res)
    if len(wc):
        recs.append({"kind": "wage_fix", "priority": "urgent", "unit": None,
                     "params": {"count": len(wc), "monthly": float(wc["التكلفة الشهرية"].sum())}})
    recs.sort(key=lambda r: r["priority"] != "urgent")
    return recs


def _calendar(res: dict, ref: pd.Timestamp, horizon_days: int = 365) -> list[dict]:
    out, end = [], ref + pd.Timedelta(days=horizon_days)
    for _, u in res["units"].iterrows():
        unit = {"ar": u["unit"], "en": u["unit_en"]}
        if pd.notna(u.get("next_date")) and ref < u["next_date"] <= end:
            out.append({"date": u["next_date"], "kind": "phase", "unit": unit, "ratio": u["next_ratio"],
                        "applicable": bool(u["applicable"]), "shortfall": u["next_shortfall"]})
        if not u["enforced"] and pd.notna(u.get("effective")) and u["effective"] <= end:
            out.append({"date": u["effective"], "kind": "enforce", "unit": unit})
    df = res["df"]
    soon = df[df["upcoming_date"].notna() & (df["upcoming_date"] > ref) & (df["upcoming_date"] <= end)]
    for (gid, d), m in soon.groupby(["upcoming_group_id", "upcoming_date"]):
        out.append({"date": d, "kind": "restricted", "unit": {"ar": m["upcoming_group"].iloc[0], "en": gid},
                    "count": len(m), "non_saudi": int((~m["سعودي"]).sum())})
    return sorted(out, key=lambda x: x["date"])


def _uncovered(res: dict, rules: dict) -> list[dict]:
    """موظفو المهن غير المشمولة بأي قرار (لم يطابق مسماهم مهنة في القواعد) مع أقرب مهنة مستهدفة للمراجعة."""
    df = res["df"][res["df"]["unit_id"].isna()]
    close = {r["المسمى في التأمينات"]: r["أقرب مهنة مستهدفة (للمراجعة)"] for _, r in I.unmatched_occupations(res, rules).iterrows()}
    return [{"id": e["رقم الهوية"], "name": e["اسم المشترك"], "nationality": e["الجنسية"], "saudi": bool(e["سعودي"]),
             "occupation": e["المهنة"], "suggestion": close.get(e["المهنة"], "—")} for _, e in df.iterrows()]


def build_payload(res: dict, rules: dict, s: E.Settings) -> dict:
    ref = pd.Timestamp(s.reference_date)
    gc, cap, wc = I.gap_cost(res), I.hiring_capacity(res), I.wage_corrections(res)
    units = res["units"]
    unit_en = dict(zip(units["unit"], units["unit_en"])) if not units.empty else {}
    pens = [{"unit": {"ar": p["المجموعة"], "en": unit_en.get(p["المجموعة"], p["المجموعة"])},
             "type": "restricted" if "مقصورة" in p["نوع المخالفة"] else "ratio", "count": p["العدد"],
             "rate": p["الغرامة للعامل"], "total": p["الإجمالي"], "active": bool(p["سارية"])} for _, p in res["penalties"].iterrows()]
    payload = {
        "reference_date": ref, "summary": res["summary"], "rules_version": rules.get("version"),
        "penalties_verified": rules["penalties"].get("verified", False),
        "groups": _groups(res) if not units.empty else [],
        "employees": _employees(res["df"]),
        "recommendations": _recommendations(res) if not units.empty else [],
        "penalties": pens,
        "calendar": _calendar(res, ref) if not units.empty else [],
        "gap_cost": [{"unit": {"ar": r["المجموعة"], "en": unit_en.get(r["المجموعة"], r["المجموعة"])}, "shortfall": r["العجز"],
                      "ref_wage": r["أجر مرجعي شهري"], "monthly": r["تكلفة شهرية تقديرية"], "annual": r["تكلفة سنوية تقديرية"],
                      "fine": r["الغرامة المتوقعة"]} for _, r in gc.iterrows()],
        "capacity": [{"unit": {"ar": r["المجموعة"], "en": unit_en.get(r["المجموعة"], r["المجموعة"])}, "n": r["العاملون"],
                      "counted": r["سعوديون محتسبون"], "required": r["المطلوب"], "room": r["يمكن إضافة غير سعوديين"],
                      "to_threshold": r["قبل بلوغ حد السريان"]} for _, r in cap.iterrows()] if len(cap) else [],
        "wage_fixes": [{"id": r["رقم الهوية"], "name": r["اسم المشترك"], "occupation": r["المهنة"], "subject": r["الاجر الخاضع للاشتراك"],
                        "min_wage": r["الحد الأدنى"], "monthly": r["التكلفة الشهرية"]} for _, r in wc.iterrows()],
        "uncovered": _uncovered(res, rules),
        "unmatched": [{"occupation": r["المسمى في التأمينات"], "n": r["الموظفون"], "saudi": r["سعوديون"],
                       "suggestion": r["أقرب مهنة مستهدفة (للمراجعة)"]} for _, r in I.unmatched_occupations(res, rules).iterrows()],
    }
    return jsonable(payload)


def simulate_payload(gosi: pd.DataFrame, rules: dict, s: E.Settings, occupation: str | None, saudi: bool,
                     wage: float, count: int, remove_ids: list[str]) -> dict:
    add = I.new_employee(occupation, saudi, wage, count) if occupation and count > 0 else None
    sim = I.simulate(gosi, rules, s, add=add, remove_ids=remove_ids or None)
    b, a = sim["before"], sim["after"]

    def rows(r):
        return {u["unit_id"]: {"unit": {"ar": u["unit"], "en": u["unit_en"]}, "n": u["n"], "counted": u["counted"],
                               "required": u["required"], "shortfall": u["shortfall"], "status": u["status"]}
                for _, u in r["units"].iterrows()} if not r["units"].empty else {}
    rb, ra = rows(b), rows(a)
    comp = [{"unit": (ra.get(k) or rb.get(k))["unit"], "before": rb.get(k), "after": ra.get(k)} for k in dict.fromkeys([*rb, *ra])]
    return jsonable({"before": b["summary"], "after": a["summary"], "comparison": comp})


# ------------------------------------------------------------------
def demo_gosi() -> pd.DataFrame:
    """قوة عاملة افتراضية لعرض الأداة قبل رفع ملف حقيقي (أسماء وهويات وهمية)."""
    spec = [("أخصائي تسويق", 7, 4, [0, 5000]), ("مصمم جرافيك", 3, 1, []), ("مصمم إعلان", 3, 1, []), ("مندوب مبيعات", 2, 0, []),
            ("محاسب تكاليف", 4, 1, []), ("مدير مالي", 1, 0, []), ("مهندس مدني", 3, 1, []), ("مهندس كهربائي", 2, 0, []),
            ("سكرتير", 1, 0, []), ("أخصائي توظيف", 1, 1, []), ("سائق سيارة", 2, 0, []), ("عامل مخزن", 2, 0, [])]
    nats = ["الهند", "مصر", "الأردن", "اليمن", "باكستان", "السودان"]
    rows, i = [], 1
    for occ, n, sa, low in spec:
        for k in range(n):
            saudi = k < sa
            wage = low[k] if saudi and k < len(low) and low[k] else (9000 if saudi else 6300)
            r = make_employee_row(f"موظف تجريبي {i}", "السعودية" if saudi else nats[i % len(nats)], occ, wage, str(1_000_000_000 + i * 7919))
            r["الأجر الأساسي"], r["إجمالي الأجر"] = round(wage * 0.7), round(wage / 0.9)
            rows.append(r)
            i += 1
    return pd.DataFrame(rows)
