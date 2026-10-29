"""
engine.py — محرك الامتثال (Business Logic)
==========================================
القاعدة الأساسية (الأدلة الإجرائية لوزارة الموارد البشرية):
  • الامتثال يُقاس على مستوى «المجموعة المهنية» ككتلة واحدة (أو المجموعة الفرعية إن نص القرار)،
    وليس على كل مسمى وظيفي مفرد.
  • لا يسري القرار إلا إذا بلغ عدد العاملين في مهن المجموعة «حد السريان»، وبلغ إجمالي عمال المنشأة
    «حد حجم المنشأة» إن نص عليه القرار (min_establishment_size، مثل السلامة والصحة المهنية: 50 عاملاً فأكثر).
  • السعوديون المطلوبون = تقريب(النسبة × إجمالي العاملين في المجموعة).
  • لا يُحتسب السعودي الذي أجره الخاضع للاشتراك أقل من الحد الأدنى للمجموعة.
  • المهن المقصورة (scope = restricted) تُفحص لكل موظف: أي غير سعودي عليها مخالفة.
  • عند تداخل قرارين على المسمى نفسه تُطبَّق النسبة الأعلى السارية.

كل الأرقام تأتي من ملف القواعد؛ لا توجد قيم ثابتة في الدوال.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import rules_store as R

EPS = 1e-9


@dataclass
class Settings:
    reference_date: pd.Timestamp
    wage_tier: str = "bachelor"               # bachelor | diploma — للمجموعات ذات حدّين للأجر
    below_min_weight: float | None = None     # None = من القواعد (calculation.below_min_wage_weight)
    include_activity_specific: bool = False   # تضمين المجموعات الخاصة بنشاط محدد
    category: str | None = None               # None = تلقائي حسب عدد الموظفين
    repeat_multiplier: float | None = None    # None = من القواعد


# ==================================================================
# 1) ربط كل موظف بمجموعته المهنية
# ==================================================================
def assign_groups(gosi: pd.DataFrame, rules: dict, s: Settings) -> pd.DataFrame:
    """يضيف لكل موظف: المجموعة، الوحدة (مجموعة أو مجموعة فرعية)، الحد الأدنى للأجر، وزن الاحتساب،
    وأي قرار قادم أعلى نسبة سينطبق على مسماه لاحقاً."""
    ref = pd.Timestamp(s.reference_date)
    idx, gmap = R.build_title_index(rules), R.groups_by_id(rules)
    weight_below = rules["calculation"].get("below_min_wage_weight", 0.0) if s.below_min_weight is None else s.below_min_weight
    rows = []
    for _, e in gosi.iterrows():
        cands = [p for p in idx.get(e["_key"], [])
                 if s.include_activity_specific or not gmap[p["group"]].get("activity_specific")]
        rec = {"group_id": None, "group": None, "scope": None, "subgroup": None, "unit_id": None, "unit": None, "unit_en": None,
               "profession": None, "code": None, "min_wage": np.nan, "member_enforced": False, "member_date": pd.NaT,
               "upcoming_group_id": None, "upcoming_group": None, "upcoming_date": pd.NaT, "upcoming_ratio": np.nan}
        if cands:
            evals = [(p, R.phase_at(gmap[p["group"]], ref, p)) for p in cands]
            active = [x for x in evals if x[1]["enforced"]]
            p, ph = max(active or evals, key=lambda x: x[1]["ratio"])          # سياسة: النسبة الأعلى
            g = gmap[p["group"]]
            sub = p.get("subgroup") if g["scope"] == "subgroup" else None
            unit_id = f'{g["id"]}::{sub}' if sub else g["id"]
            name_en = g.get("name_en") or g["name"]
            sub_en = (g.get("subgroups", {}).get(sub, {}).get("name_en") or sub) if sub else None
            rec.update({"group_id": g["id"], "group": g["name"], "scope": g["scope"], "subgroup": sub, "unit_id": unit_id,
                        "unit": f'{g["name"]} — {sub}' if sub else g["name"],
                        "unit_en": f"{name_en} — {sub_en}" if sub else name_en, "profession": p["title"], "code": p.get("code"),
                        "min_wage": R.min_wage(g, s.wage_tier, sub), "member_enforced": ph["enforced"], "member_date": ph["effective"]})
            later = [x for x in evals if not x[1]["enforced"] and x[1]["ratio"] > ph["ratio"] + EPS]
            if later:
                q, qph = max(later, key=lambda x: x[1]["ratio"])
                rec.update({"upcoming_group_id": q["group"], "upcoming_group": gmap[q["group"]]["name"],
                            "upcoming_date": qph["effective"], "upcoming_ratio": qph["ratio"]})
        rows.append(rec)
    out = pd.concat([gosi.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    has_min = out["min_wage"].notna()
    out["أجر مطابق"] = ~has_min | (out["الاجر الخاضع للاشتراك"] + EPS >= out["min_wage"])
    out["وزن الاحتساب"] = np.where(out["سعودي"], np.where(out["أجر مطابق"], 1.0, weight_below), 0.0)
    out["الفرق عن الحد الأدنى"] = np.where(has_min, (out["min_wage"] - out["الاجر الخاضع للاشتراك"]).clip(lower=0), 0.0)
    return out


# ==================================================================
# 2) المستوى الأول: الامتثال لكل مجموعة مهنية
# ==================================================================
def _required(rules: dict, ratio: float, n: int) -> int:
    return n if ratio >= 1 - EPS else R.round_required(ratio * n, rules["calculation"]["rounding"])


def compute_units(df: pd.DataFrame, rules: dict, s: Settings) -> pd.DataFrame:
    ref, gmap = pd.Timestamp(s.reference_date), R.groups_by_id(rules)
    est_total = len(df)                                   # إجمالي عمال المنشأة (count_scope = entity)
    rows = []
    for unit_id, m in df[df["unit_id"].notna()].groupby("unit_id"):
        g = gmap[m["group_id"].iloc[0]]
        est_thr = int(g.get("min_establishment_size") or 0)
        est_ok = est_total >= est_thr
        n, saudi = len(m), int(m["سعودي"].sum())
        s_eff, non = float(m["وزن الاحتساب"].sum()), n - int(m["سعودي"].sum())
        under = int((m["سعودي"] & ~m["أجر مطابق"]).sum())
        base = {"unit_id": unit_id, "unit": m["unit"].iloc[0], "unit_en": m["unit_en"].iloc[0], "group_id": g["id"], "group": g["name"], "scope": g["scope"],
                "source_url": g.get("source_url", ""), "source_title": g.get("source_title", ""), "decision": g.get("decision", ""), "decision_en": g.get("decision_en", ""),
                "accreditation": g.get("accreditation", ""), "verified": g.get("verified", False),
                "n": n, "saudi": saudi, "counted": s_eff, "non_saudi": non, "under_wage": under,
                "current_pct": s_eff / n if n else 0.0, "min_wage": m["min_wage"].max(), "threshold": int(g["min_headcount"]),
                "establishment_total": est_total, "establishment_threshold": est_thr, "establishment_ok": est_ok}
        if g["scope"] == "restricted":
            viol = m[~m["سعودي"] & m["member_enforced"]] if est_ok else m.iloc[0:0]
            soon = df[~df["سعودي"] & (((df["unit_id"] == unit_id) & ~df["member_enforced"]) | (df["upcoming_group_id"] == g["id"]))] if est_ok else df.iloc[0:0]
            base.update({"ratio": 1.0, "required": n, "shortfall": len(viol), "upcoming_violations": len(soon),
                         "violator_ids": viol["رقم الهوية"].tolist(), "upcoming_ids": soon["رقم الهوية"].tolist(),
                         "applicable": est_ok, "enforced": True, "effective": m["member_date"].min(),
                         "compliant": viol.empty, "hire_only": None, "headroom": 0, "surplus": 0,
                         "next_ratio": np.nan, "next_date": pd.NaT, "next_shortfall": np.nan, "at_threshold": None,
                         "fixed_shortfall": len(viol),
                         "status": "na" if not est_ok else ("risk" if len(viol) else ("grace" if len(soon) else "ok"))})
            rows.append(base)
            continue
        ph = R.phase_at(g, ref)
        r = ph["ratio"]
        req = _required(rules, r, n)
        short = max(0, int(np.ceil(req - s_eff - EPS)))
        applicable = est_ok and n >= int(g["min_headcount"])
        hire = 0
        while s_eff + hire + EPS < _required(rules, r, n + hire) and hire < 10_000:
            hire += 1
        room = 0
        if short == 0:
            while s_eff + EPS >= _required(rules, r, n + room + 1) and room < 10_000:
                room += 1
        w_below = float(m.loc[m["سعودي"] & ~m["أجر مطابق"], "وزن الاحتساب"].mean()) if under else 0.0
        fixed = max(0, int(np.ceil(req - (s_eff + under * (1 - w_below)) - EPS)))   # بعد تصحيح أجور من هم دون الحد
        nr = ph["next_ratio"]
        nshort = max(0, int(np.ceil(_required(rules, nr, n) - s_eff - EPS))) if not pd.isna(nr) else np.nan
        thr = int(g["min_headcount"])
        at_thr = None if applicable or not est_ok else {"n": thr, "required": _required(rules, r, thr),
                                          "shortfall": max(0, int(np.ceil(_required(rules, r, thr) - s_eff - EPS)))}
        compliant = short == 0
        status = "na" if not applicable else ("ok" if compliant else ("risk" if ph["enforced"] else "grace"))
        base.update({"ratio": r, "required": req, "shortfall": short, "upcoming_violations": 0, "violator_ids": [], "upcoming_ids": [],
                     "applicable": applicable, "enforced": ph["enforced"], "effective": ph["effective"],
                     "compliant": compliant or not applicable, "hire_only": hire, "headroom": room if compliant else 0,
                     "surplus": max(0.0, s_eff - req), "next_ratio": nr, "next_date": ph["next_date"], "next_shortfall": nshort,
                     "at_threshold": at_thr, "fixed_shortfall": fixed, "status": status})
        rows.append(base)
    order = {"risk": 0, "grace": 1, "ok": 2, "na": 3}
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_o"] = out["status"].map(order)
    return out.sort_values(["_o", "n"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


# ==================================================================
# 3) المستوى الثاني والثالث: تفصيل المسميات والموظفين (أرقام توضيحية فقط)
# ==================================================================
def occupation_breakdown(df: pd.DataFrame, unit_id: str) -> pd.DataFrame:
    m = df[df["unit_id"] == unit_id]
    out = m.groupby("profession").agg(
        العاملون=("رقم الهوية", "count"), سعوديون=("سعودي", "sum"), محتسبون=("وزن الاحتساب", "sum"),
        دون_الحد=("أجر مطابق", lambda x: int((~x & m.loc[x.index, "سعودي"]).sum()))).reset_index()
    out["غير سعوديين"] = out["العاملون"] - out["سعوديون"]
    return out.rename(columns={"profession": "المسمى الوظيفي", "دون_الحد": "سعوديون دون الحد الأدنى"}).sort_values("العاملون", ascending=False)


def employees_of(df: pd.DataFrame, unit_id: str | None = None, profession: str | None = None,
                 ids: list[str] | None = None) -> pd.DataFrame:
    m = df
    if unit_id is not None:
        m = m[m["unit_id"] == unit_id]
    if profession is not None:
        m = m[m["profession"] == profession]
    if ids is not None:
        m = m[m["رقم الهوية"].isin(ids)]
    out = m[["اسم المشترك", "رقم الهوية", "الجنسية", "المهنة", "الأجر الأساسي", "إجمالي الأجر",
             "الاجر الخاضع للاشتراك", "min_wage", "وزن الاحتساب"]].copy()
    out["يُحتسب في النسبة"] = np.where(m["سعودي"], np.where(m["أجر مطابق"], "نعم", "لا — أجره دون الحد"), "غير سعودي")
    return out.drop(columns="وزن الاحتساب").rename(columns={"min_wage": "الحد الأدنى للأجر"}).sort_values("الجنسية")


# ==================================================================
# 4) الغرامات والتوصيات
# ==================================================================
def compute_penalties(units: pd.DataFrame, rules: dict, s: Settings, category: str) -> pd.DataFrame:
    pen = rules["penalties"]
    rates = pen["per_category"][category]
    mult = pen.get("repeat_multiplier", 1.0) if s.repeat_multiplier is None else s.repeat_multiplier
    rows = []
    for _, u in units.iterrows():
        if u["scope"] == "restricted":
            for cnt, active in ((u["shortfall"], True), (u["upcoming_violations"], False)):
                if cnt:
                    rows.append({"المجموعة": u["unit"], "نوع المخالفة": "تشغيل غير سعودي في مهنة مقصورة على السعوديين",
                                 "العدد": int(cnt), "الغرامة للعامل": rates["restricted"] * mult,
                                 "الإجمالي": cnt * rates["restricted"] * mult, "سارية": active})
        elif u["applicable"] and not u["compliant"]:
            rows.append({"المجموعة": u["unit"], "نوع المخالفة": "عدم تحقيق نسبة التوطين", "العدد": int(u["shortfall"]),
                         "الغرامة للعامل": rates["ratio"] * mult, "الإجمالي": u["shortfall"] * rates["ratio"] * mult,
                         "سارية": bool(u["enforced"])})
    return pd.DataFrame(rows, columns=["المجموعة", "نوع المخالفة", "العدد", "الغرامة للعامل", "الإجمالي", "سارية"])


def _d(x) -> str:
    return "—" if pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d")


def build_recommendations(units: pd.DataFrame, df: pd.DataFrame) -> list[dict]:
    """توصيات على مستوى المجموعة فقط؛ لا تنبيه لمسمى مفرد ما دامت مجموعته ممتثلة."""
    recs = []
    for _, u in units.iterrows():
        if u["scope"] == "restricted":
            for ids, active in ((u["violator_ids"], True), (u["upcoming_ids"], False)):
                for _, e in df[df["رقم الهوية"].isin(ids)].iterrows():
                    when = _d(e["member_date"] if active else (e["upcoming_date"] if pd.notna(e["upcoming_date"]) else e["member_date"]))
                    recs.append({"priority": "عاجل" if active else "استباقي", "group": u["unit"],
                                 "text": f"{e['اسم المشترك']} ({e['الجنسية']}، {e['رقم الهوية']}) مسجّل بمهنة «{e['المهنة']}» "
                                         f"المقصورة على السعوديين {'منذ' if active else 'اعتباراً من'} {when}.",
                                 "detail": "إن كان عمله الفعلي في هذه المهنة: انقله إلى دور حقيقي غير مقصور وعدّل مهنته في قوى والتأمينات، "
                                           "أو أحلّ سعودياً مكانه. وإن كان المسمى خاطئاً: صحّحه إلى ما يطابق عمله الفعلي."})
            continue
        if u["applicable"] and not u["compliant"]:
            d = (f"المطلوب {u['required']} = {u['ratio']:.0%} × {u['n']} مقرّباً، والمحتسبون {u['counted']:g}. "
                 f"إن كان بالتوظيف دون استغناء فالمطلوب {u['hire_only']}.")
            if u["under_wage"]:
                d += f" تصحيح أجور {u['under_wage']} سعوديين إلى {u['min_wage']:,.0f} ريال يخفض العجز إلى {u['fixed_shortfall']}."
            if not u["enforced"]:
                d += f" يبدأ الإلزام في {_d(u['effective'])}."
            recs.append({"priority": "عاجل" if u["enforced"] else "استباقي", "group": u["unit"],
                         "text": f"تحتاج {u['shortfall']} سعوديين إضافيين محتسبين في مجموعة «{u['unit']}».", "detail": d})
        elif u["applicable"] and u["headroom"] <= 1 and u["ratio"] < 1:
            recs.append({"priority": "استباقي", "group": u["unit"],
                         "text": f"هامش الأمان في «{u['unit']}» ضيق: يمكن إضافة {u['headroom']} غير سعودي فقط قبل المخالفة.",
                         "detail": f"خروج سعودي أو نزول أجره عن {u['min_wage']:,.0f} ريال قد يُسقط الامتثال." if pd.notna(u["min_wage"])
                                   else "خروج سعودي واحد قد يُسقط الامتثال."})
        if u["applicable"] and pd.notna(u["next_ratio"]) and u["next_shortfall"] and u["next_shortfall"] > 0:
            recs.append({"priority": "استباقي", "group": u["unit"],
                         "text": f"نسبة «{u['unit']}» سترتفع إلى {u['next_ratio']:.0%} في {_d(u['next_date'])}: ستحتاج {u['next_shortfall']} سعوديين إضافيين.",
                         "detail": ""})
        if not u["establishment_ok"]:
            recs.append({"priority": "استباقي", "group": u["unit"],
                         "text": f"«{u['unit']}» غير خاضعة لأن المنشأة لديها {u['establishment_total']} عاملاً، "
                                 f"والقرار يسري على المنشآت ذات {u['establishment_threshold']} عاملاً فأكثر.",
                         "detail": f"عند بلوغ المنشأة {u['establishment_threshold']} عاملاً تلزم نسبة {u['ratio']:.0%} في هذه المجموعة."})
        if not u["applicable"] and u["at_threshold"]:
            left = u["threshold"] - u["n"]
            recs.append({"priority": "استباقي", "group": u["unit"],
                         "text": f"«{u['unit']}» غير خاضعة ({u['n']} من {u['threshold']}). توظيف {left} إضافي يُخضعها للقرار.",
                         "detail": f"عندها يلزم {u['at_threshold']['required']} سعوديين محتسبين، ولديك {u['counted']:g}."})
        if u["applicable"] and u["accreditation"]:
            recs.append({"priority": "استباقي", "group": u["unit"],
                         "text": f"تحقق من الاعتماد المهني للسعوديين في «{u['unit']}» ({u['accreditation']}).",
                         "detail": "ملف التأمينات لا يبيّن الاعتماد، وغير المعتمد لا يُحتسب."})
    return sorted(recs, key=lambda r: r["priority"] != "عاجل")


# ==================================================================
# 5) التشغيل الكامل
# ==================================================================
def run(gosi: pd.DataFrame, rules: dict, s: Settings) -> dict:
    df = assign_groups(gosi, rules, s)
    category = s.category or R.category_for(rules, len(df))
    units = compute_units(df, rules, s)
    pens = compute_penalties(units, rules, s, category) if not units.empty else compute_penalties(pd.DataFrame(columns=["scope"]), rules, s, category)
    recs = build_recommendations(units, df) if not units.empty else []
    appl = units[units["applicable"]] if not units.empty else units
    summary = {
        "category": category, "total": len(df), "saudi": int(df["سعودي"].sum()),
        "in_scope": int(df["unit_id"].notna().sum()),
        "out_of_scope": int(df["unit_id"].isna().sum()),          # total = in_scope + out_of_scope
        "units": len(units), "applicable": len(appl),
        "noncompliant": int((~appl["compliant"]).sum()) if len(appl) else 0,
        "shortfall": int(appl.loc[appl["scope"] != "restricted", "shortfall"].sum()) if len(appl) else 0,
        "restricted_violations": int(units.loc[units["scope"] == "restricted", "shortfall"].sum()) if len(units) else 0,
        "restricted_upcoming": int(units.loc[units["scope"] == "restricted", "upcoming_violations"].sum()) if len(units) else 0,
        "penalty_active": float(pens.loc[pens["سارية"], "الإجمالي"].sum()) if len(pens) else 0.0,
        "penalty_upcoming": float(pens.loc[~pens["سارية"].astype(bool), "الإجمالي"].sum()) if len(pens) else 0.0,
    }
    return {"df": df, "units": units, "penalties": pens, "recommendations": recs, "summary": summary}
