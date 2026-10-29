"""
insights.py — تحليلات مالية وإدارية استباقية فوق محرك الامتثال
================================================================
- gap_cost           : التكلفة التقديرية لسد فجوة التوطين مقابل الغرامات المتوقعة
- wage_corrections   : سعوديون دون الحد الأدنى للأجر وتكلفة تصحيح أجورهم
- hiring_capacity    : كم غير سعودي يمكن توظيفه في كل مجموعة قبل المخالفة
- upcoming_calendar  : تقويم المواعيد القادمة (مراحل جديدة، مهن ستُقصر، مجموعات تقترب من حد السريان)
- simulate           : محاكي «ماذا لو» قبل التوظيف أو الاستغناء
"""
from __future__ import annotations

import pandas as pd

from . import data_loader as D
from . import engine as E


def gap_cost(res: dict) -> pd.DataFrame:
    df, units, pens = res["df"], res["units"], res["penalties"]
    if units.empty:
        return pd.DataFrame()
    saudi_median_all = df.loc[df["سعودي"], "الاجر الخاضع للاشتراك"].median()
    rows = []
    for _, u in units[units["applicable"] & ~units["compliant"]].iterrows():
        m = df[(df["unit_id"] == u["unit_id"]) & df["سعودي"]]["الاجر الخاضع للاشتراك"]
        ref = m.median() if len(m) else (u["min_wage"] if pd.notna(u["min_wage"]) else saudi_median_all)
        basis = "متوسط أجر السعوديين في المجموعة" if len(m) else ("الحد الأدنى للأجر" if pd.notna(u["min_wage"]) else "متوسط أجر السعوديين في المنشأة")
        fine = pens.loc[pens["المجموعة"] == u["unit"], "الإجمالي"].sum()
        rows.append({"المجموعة": u["unit"], "العجز": int(u["shortfall"]), "أجر مرجعي شهري": round(float(ref)), "أساس الأجر": basis,
                     "تكلفة شهرية تقديرية": round(float(ref) * u["shortfall"]), "تكلفة سنوية تقديرية": round(float(ref) * u["shortfall"] * 12),
                     "الغرامة المتوقعة": fine})
    return pd.DataFrame(rows)


def wage_corrections(res: dict) -> pd.DataFrame:
    df, units = res["df"], res["units"]
    appl = set(units.loc[units["applicable"], "unit_id"]) if not units.empty else set()
    m = df[df["unit_id"].isin(appl) & df["سعودي"] & ~df["أجر مطابق"]].copy()
    m["التكلفة الشهرية"] = m["الفرق عن الحد الأدنى"]
    m["التكلفة السنوية"] = m["الفرق عن الحد الأدنى"] * 12
    return m[["اسم المشترك", "رقم الهوية", "المهنة", "unit", "الاجر الخاضع للاشتراك", "min_wage", "التكلفة الشهرية", "التكلفة السنوية"]] \
        .rename(columns={"unit": "المجموعة", "min_wage": "الحد الأدنى"})


def hiring_capacity(res: dict) -> pd.DataFrame:
    u = res["units"]
    if u.empty:
        return u
    x = u[(u["scope"] != "restricted")].copy()
    x["يمكن إضافة غير سعوديين"] = x.apply(lambda r: int(r["headroom"]) if r["applicable"] and r["compliant"] else (0 if r["applicable"] else None), axis=1)
    x["قبل بلوغ حد السريان"] = x.apply(lambda r: None if r["applicable"] or not r["establishment_ok"] else int(r["threshold"] - r["n"]), axis=1)
    return x[["unit", "n", "counted", "required", "يمكن إضافة غير سعوديين", "قبل بلوغ حد السريان"]] \
        .rename(columns={"unit": "المجموعة", "n": "العاملون", "counted": "سعوديون محتسبون", "required": "المطلوب"})


def upcoming_calendar(res: dict, ref: pd.Timestamp, horizon_days: int = 365) -> pd.DataFrame:
    rows, end = [], ref + pd.Timedelta(days=horizon_days)
    for _, u in res["units"].iterrows():
        if pd.notna(u.get("next_date")) and ref < u["next_date"] <= end:
            impact = f"ستحتاج {int(u['next_shortfall'])} سعوديين إضافيين" if u["applicable"] and u["next_shortfall"] else \
                     ("لا أثر حالياً — المجموعة دون حد السريان" if not u["applicable"] else "ممتثل بالنسبة الجديدة")
            rows.append({"التاريخ": u["next_date"].date(), "الحدث": f"ارتفاع نسبة «{u['unit']}» إلى {u['next_ratio']:.0%}", "الأثر عليكم": impact})
        if not u["enforced"] and pd.notna(u.get("effective")) and u["effective"] <= end:
            rows.append({"التاريخ": u["effective"].date(), "الحدث": f"بدء إلزام «{u['unit']}»", "الأثر عليكم": "راجع الامتثال قبل هذا التاريخ"})
    df = res["df"]
    soon = df[df["upcoming_date"].notna() & (df["upcoming_date"] > ref) & (df["upcoming_date"] <= end)]
    for (grp, d), m in soon.groupby(["upcoming_group", "upcoming_date"]):
        rows.append({"التاريخ": d.date(), "الحدث": f"مهن تنتقل إلى «{grp}»",
                     "الأثر عليكم": f"{len(m)} موظفاً، منهم {int((~m['سعودي']).sum())} غير سعودي يجب تصحيح وضعه"})
    return pd.DataFrame(rows).sort_values("التاريخ") if rows else pd.DataFrame(columns=["التاريخ", "الحدث", "الأثر عليكم"])


def simulate(gosi: pd.DataFrame, rules: dict, s: E.Settings, add: list[dict] | None = None, remove_ids: list[str] | None = None) -> dict:
    """يعيد نتيجة المحرك قبل وبعد تغيير افتراضي، مع مقارنة لكل مجموعة."""
    before = E.run(gosi, rules, s)
    g2 = gosi.copy()
    if remove_ids:
        g2 = g2[~g2["رقم الهوية"].isin(remove_ids)]
    if add:
        g2 = pd.concat([g2, pd.DataFrame(add)], ignore_index=True)
    after = E.run(g2, rules, s)
    keep = ["unit", "n", "counted", "required", "shortfall", "status"]
    b = before["units"][keep] if not before["units"].empty else pd.DataFrame(columns=keep)
    a = after["units"][keep] if not after["units"].empty else pd.DataFrame(columns=keep)
    labels = {"risk": "غير ممتثل", "grace": "قبل الإلزام", "ok": "ممتثل", "na": "غير خاضع"}
    ar = {"unit": "المجموعة", "n": "العاملون", "counted": "سعوديون محتسبون", "required": "المطلوب", "shortfall": "العجز", "status": "الحالة"}
    b, a = b.assign(status=b["status"].map(labels)).rename(columns=ar), a.assign(status=a["status"].map(labels)).rename(columns=ar)
    cmp = b.merge(a, on="المجموعة", how="outer", suffixes=(" قبل", " بعد"))
    return {"before": before, "after": after, "comparison": cmp}


def new_employee(occupation: str, saudi: bool, wage: float, n: int = 1) -> list[dict]:
    return [D.make_employee_row(f"موظف افتراضي {i + 1}", "السعودية" if saudi else "وافد", occupation, wage, f"SIM{i}")
            for i in range(n)]


def unmatched_occupations(res: dict, rules: dict) -> pd.DataFrame:
    """مسميات في التأمينات لا تطابق أي مهنة في القواعد + أقرب مسمى مقترح للمراجعة."""
    from difflib import get_close_matches
    from .textutils import normalize_arabic
    titles = {normalize_arabic(p["title"]): (p["title"], p["group"]) for p in rules["professions"]}
    gname = {g["id"]: g["name"] for g in rules["groups"]}
    df = res["df"]
    rows = []
    for occ, m in df[df["unit_id"].isna()].groupby("المهنة"):
        close = get_close_matches(normalize_arabic(occ), list(titles), n=1, cutoff=0.88)
        rows.append({"المسمى في التأمينات": occ, "الموظفون": len(m), "سعوديون": int(m["سعودي"].sum()),
                     "أقرب مهنة مستهدفة (للمراجعة)": f"{titles[close[0]][0]} — {gname[titles[close[0]][1]]}" if close else "—"})
    return pd.DataFrame(rows).sort_values("الموظفون", ascending=False) if rows else pd.DataFrame(
        columns=["المسمى في التأمينات", "الموظفون", "سعوديون", "أقرب مهنة مستهدفة (للمراجعة)"])
