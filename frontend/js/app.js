/* app.js — INVENU Saudization compliance (frontend)
   Talks to the local FastAPI backend (/api/*), or — in the browser build — to the same engine via web/bridge.js. No external network calls. */
"use strict";
// رابط مستودع المشروع على GitHub (يظهر في الصفحة لمن يريد مراجعة الكود)
const REPO_URL = "https://github.com/INVENU/saudization-tool";
const $ = id => document.getElementById(id);
const SEP = () => S.lang === "en" ? ", " : "، ";
const ICON_INFO = `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 7.2v4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="4.9" r=".9" fill="currentColor"/></svg>`;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }};

// مفتاح API للمستشار الذكي (AI): ذاكرة الجلسة فقط (sessionStorage يُمسح بإغلاق التبويب)؛ لا localStorage ولا ملف قواعد ولا تقارير
const sess = {get: k => { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
              set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
              del: k => { try { sessionStorage.removeItem(k); } catch (e) { /* storage unavailable */ } }};
const S = {
  aiKey: sess.get("inv-ai-key") || "", aiProv: sess.get("inv-ai-provider") || "", aiModel: sess.get("inv-ai-model") || "", aiDefaults: {anthropic: "claude-opus-5-5", openai: "gpt-4.1"}, ai: {text: "", draft: null, warnings: [], busy: false, err: ""},
  lang: store.get("inv-lang") === "en" ? "en" : "ar",
  token: null, data: null, rules: null, tab: "comp", open: new Set(),
  settings: {reference_date: new Date().toISOString().slice(0, 10), wage_tier: "bachelor", below_min_weight: null,
             include_activity_specific: false, category: null, repeat_multiplier: null},
  profPage: 60, profQuery: "",
};
const t = (k, vars) => { let s = (STR[S.lang][k] ?? STR.ar[k] ?? k); if (vars) for (const [a, b] of Object.entries(vars)) s = s.replaceAll(`{${a}}`, b); return s; };
const uname = u => (u && typeof u === "object") ? (S.lang === "en" ? (u.en || u.ar) : u.ar) : (u ?? "");
const gname = g => S.lang === "en" ? (g.unit_en || g.unit) : g.unit;
const sar = v => `${N(Math.round(v || 0))} ${t("sar")}`;
const CAT_EN = {"أ": "A", "ب": "B", "ج": "C"};
const cat = c => S.lang === "en" ? (CAT_EN[c] || c) : c;
const pill = st => `<span class="pill ${st}"><span class="dot ${st}"></span>${t("st_" + st)}</span>`;

/* ------------------------------------------------------------------ API */
// نسخة المتصفح (web/bridge.js) تعرّف INVENU_FETCH لتشغيل المحرك داخل المتصفح بدل الخادم
async function api(path, body, opts = {}) {
  const r = await (window.INVENU_FETCH || fetch)(path, {method: opts.method || (body ? "POST" : "GET"), headers: body && !(body instanceof FormData) ? {"Content-Type": "application/json"} : {},
                               body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined});
  if (!r.ok) { let m = t("err"); try { const j = await r.json(); const d = j.detail; m = typeof d === "string" ? d : (d && (d[S.lang] || d.ar)) || (d?.errors || []).join(" ؛ ") || m; } catch (e) {} throw new Error(m); }
  return opts.raw ? r : r.json();
}
function showMsg(html, err) { $("msg").innerHTML = html ? `<div class="banner ${err ? "err" : ""}">${html}</div>` : ""; }
function toast(text) { const d = document.createElement("div"); d.className = "toast"; d.textContent = text; document.body.appendChild(d); setTimeout(() => d.remove(), 2600); }

async function analyze() {
  if (!S.token) return;
  try { S.data = await api("/api/analyze", {token: S.token, settings: S.settings, lang: S.lang}); render(); }
  catch (e) { showMsg(esc(e.message), true); }
}
async function loadDemo() { try { const r = await api("/api/demo", {}); S.token = r.token; await analyze(); } catch (e) { showMsg(esc(e.message), true); } }
async function uploadFile(f) {
  if (!/\.xlsx$/i.test(f.name)) { showMsg(esc(t("err_xlsx")), true); return; }      // .xls وغيرها: رسالة واضحة قبل أي معالجة
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/upload", fd); S.token = r.token; S.open.clear(); await analyze(); }
  catch (e) { showMsg(esc(e.message), true); }
}

/* ------------------------------------------------------------------ i18n + theme */
function applyLang() {
  const L = STR[S.lang], root = document.documentElement;
  root.lang = S.lang; root.dir = L.dir;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
  $("langBtn").textContent = L.lang_btn;
  document.title = S.lang === "en" ? "Saudization compliance — INVENU" : "امتثال التوطين — INVENU";
  applyThemeLabel();
}
function currentTheme() { const d = document.documentElement.dataset.theme; return d || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
function applyThemeLabel() { $("themeBtn").textContent = currentTheme() === "dark" ? t("theme_light") : t("theme_dark"); }
$("langBtn").onclick = () => { S.lang = S.lang === "ar" ? "en" : "ar"; store.set("inv-lang", S.lang); applyLang(); render(); };
$("themeBtn").onclick = () => { const n = currentTheme() === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = n; store.set("inv-theme", n); applyThemeLabel(); };

/* ------------------------------------------------------------------ render */
function render() {
  const d = S.data;
  if (!d) { $("fileName").textContent = t("no_file"); showMsg(t("start_hint")); return; }
  const s = d.summary;
  $("fileName").textContent = d.file.demo ? t("demo_name") : t("file_rows", {name: d.file.name, n: N(d.file.rows)});
  showMsg("");
  document.querySelector(".filechip").classList.toggle("demo", !!d.file.demo);
  const b = v => `<b class="num">${N(v)}</b>`;
  $("facts").innerHTML = [[t("f_date"), d.reference_date], [t("f_cat"), cat(s.category)]]
    .map(([k, v]) => `<span class="fact">${k}: <b class="num">${esc(v)}</b></span>`).join("")
    + `<span class="fact">${t("f_split", {total: b(s.total), in: b(s.in_scope), out: b(s.out_of_scope)})}</span>`;
  $("alertsSub").textContent = t("alerts_sub", {total: N(s.total), scope: N(s.in_scope)});
  renderAnswer(d);
  renderAlerts(); renderComp(); renderRecs(); renderIns(); renderSim(); renderData(); renderUncovered();
  if (S.tab === "rules") renderRules();
  if (S.tab === "ai") renderAI();
}

// الصفحة تجيب على سؤال العنوان: الجملة كلها بلون حالتها (مخالف / قادم / ممتثل)
function renderAnswer(d) {
  const G = d.groups.filter(g => g.status !== "na"), risk = G.filter(g => g.status === "risk").length, grace = G.filter(g => g.status === "grace").length;
  const [st, head, detail] = risk ? ["risk", t("ans_risk"), t("ans_d_risk", {n: N(risk), total: N(G.length), fine: N(Math.round(d.summary.penalty_active))})]
    : grace ? ["grace", t("ans_grace"), t("ans_d_grace", {n: N(grace)})]
    : G.length ? ["ok", t("ans_ok"), t("ans_d_ok", {total: N(G.length)})] : ["ok", t("ans_none"), t("ans_d_none")];
  const el = $("answer");
  el.className = `answer ${st}`; el.hidden = false;
  el.innerHTML = `<p class="answer-h">${head}</p><p class="answer-d">${detail}</p>${d.file.demo ? `<p class="answer-d demo-note">${t("ans_demo")}</p>` : ""}`;
}

function renderAlerts() {
  const d = S.data, s = d.summary, total = s.penalty_active + s.penalty_upcoming, cls = (v, c) => v > 0 ? c : "ok";
  $("cards").innerHTML = `
    <div class="card hero-card"><div class="lbl"><span class="dot ${cls(total, "risk")}"></span>${t("k_total")}</div><div class="val">${N(Math.round(total))}<small>${t("sar")}</small></div><div class="foot">${t("k_total_f", {cat: esc(cat(s.category))})}</div></div>
    <div class="card ${cls(s.penalty_active, "risk")}"><div class="lbl"><span class="dot ${cls(s.penalty_active, "risk")}"></span>${t("k_active")}</div><div class="val">${N(Math.round(s.penalty_active))}<small>${t("sar")}</small></div><div class="foot">${t("k_active_f", {nc: s.noncompliant, appl: s.applicable})}</div></div>
    <div class="card ${s.restricted_violations ? "risk" : s.restricted_upcoming ? "grace" : "ok"}"><div class="lbl"><span class="dot ${s.restricted_violations ? "risk" : s.restricted_upcoming ? "grace" : "ok"}"></span>${t("k_restricted")}</div><div class="val">${N(s.restricted_violations)}</div><div class="foot">${s.restricted_upcoming ? t("k_restricted_f", {up: s.restricted_upcoming}) : t("k_restricted_f0")}</div></div>
    <div class="card ${cls(s.shortfall, "risk")}"><div class="lbl"><span class="dot ${cls(s.shortfall, "risk")}"></span>${t("k_short")}</div><div class="val">${N(s.shortfall)}</div><div class="foot">${t("k_short_f")}</div></div>`;
  const act = [], up = [];
  d.groups.filter(g => g.scope === "restricted").forEach(g => { act.push(...g.violator_ids); up.push(...g.upcoming_ids); });
  if (!act.length && !up.length) { $("restrictedAlert").innerHTML = ""; return; }
  const li = id => { const e = d.employees[id]; return `<li><bdi><b>${esc(e.name)}</b></bdi>${SEP()}<bdi>${esc(e.nationality)}</bdi>${SEP()}<bdi>${esc(e.occupation)}</bdi> <span class="num">(${esc(e.id)})</span></li>`; };
  $("restrictedAlert").innerHTML = `<div class="strip ${act.length ? "risk" : "grace"}"><div class="strip-h">${act.length ? t("strip_active") : t("strip_up")}</div>
    <ul>${[...act, ...up].map(li).join("")}</ul><button class="linkbtn" type="button" id="goRecs">${t("what_to_do")}</button></div>`;
  $("goRecs").onclick = () => selectTab("recs");
}

function statCell(l, v, f = "") { return `<div class="stat"><span class="l">${l}</span><span class="v"><bdi dir="ltr">${v}</bdi></span><span class="f">${f}</span></div>`; }

function renderComp() {
  const G = S.data.groups;
  if (!G.length) { $("p-comp").innerHTML = `<div class="empty">${t("no_groups")}</div>`; return; }
  $("p-comp").innerHTML = `<div class="method">${t("method")}</div><div class="groups">${G.map(groupCard).join("")}</div>`;
  G.forEach(g => {
    const root = document.querySelector(`[data-unit="${CSS.escape(g.unit_id)}"]`);
    root.querySelector(".group-title").onclick = () => { S.open.has(g.unit_id) ? S.open.delete(g.unit_id) : S.open.add(g.unit_id); renderComp(); };
    root.querySelector(".emp-btn").onclick = () => openEmployees(gname(g), g.employee_ids);
    root.querySelectorAll(".occ-row").forEach(tr => {
      const o = g.occupations[+tr.dataset.i];
      const open = () => openEmployees(`${gname(g)}: ${o.title}`, o.employee_ids);
      tr.onclick = open; tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
    });
  });
}

function groupCard(g) {
  const open = S.open.has(g.unit_id), restricted = g.scope === "restricted";
  const thrNote = t("s_threshold", {n: g.threshold}) + (g.establishment_threshold ? `${SEP()}${t("s_est", {n: g.establishment_threshold})}` : "");
  const stats = [statCell(t("s_workers"), N(g.n), thrNote),
                 statCell(t("s_counted"), N(g.counted), t("s_of_saudi", {n: g.saudi})),
                 statCell(t("s_pct"), `${P(g.current_pct)} / ${P(g.ratio)}`)];
  if (restricted) stats.push(statCell(t("s_non"), N(g.non_saudi), t("s_non_f")), statCell(t("s_since"), g.effective || "—"));
  else stats.push(statCell(t("s_req"), g.applicable ? `${N(g.required)} / ${N(g.shortfall)}` : "—", g.applicable ? "" : (g.establishment_ok ? t("s_below") : t("s_below_est"))),
                  g.next_ratio ? statCell(t("s_next"), P(g.next_ratio), g.next_date) :
                  statCell(t("s_room"), g.applicable && g.compliant ? N(g.headroom) : "—", g.applicable && g.compliant ? t("s_room_f") : ""));
  const detail = open ? `<div class="detail"><div class="section-h" style="margin-bottom:8px"><h3>${t("occ_h")}</h3><span class="sub">${t("occ_note")}</span></div>
    <div class="tbl-wrap"><table><thead><tr><th>${t("c_title")}</th><th>${t("c_code")}</th><th>${t("c_n")}</th><th>${t("c_saudi")}</th><th>${t("c_counted")}</th><th>${t("c_non")}</th><th>${t("c_under")}</th></tr></thead><tbody>
    ${g.occupations.map((o, i) => `<tr class="occ-row" data-i="${i}" tabindex="0" role="button"><td>${esc(o.title)}</td><td class="n">${esc(o.code || "—")}</td><td class="n">${N(o.n)}</td><td class="n">${N(o.saudi)}</td><td class="n">${N(o.counted)}</td><td class="n">${N(o.non_saudi)}</td><td class="n">${N(o.under_wage)}</td></tr>`).join("")}
    </tbody></table></div></div>` : "";
  return `<article class="group ${g.status}" data-unit="${esc(g.unit_id)}" aria-expanded="${open}">
    <div class="group-head">
      <div><button class="group-title" type="button" aria-expanded="${open}"><span class="chev" aria-hidden="true">›</span><h3>${esc(gname(g))}</h3>${pill(g.status)}</button>
        <div class="group-sub">${esc(S.lang === "en" ? (g.decision_en || g.decision) : g.decision)}${g.verified ? "" : ` <span class="tag">${t("to_verify")}</span>`}</div></div>
      <div class="group-actions">
        ${g.source_url ? `<a class="btn ghost sm" href="${esc(g.source_url)}" target="_blank" rel="noopener" title="${esc(g.source_title)}">${ICON_INFO}${t("guide")}</a>` : ""}
        <button class="btn sm emp-btn" type="button">${t("employees_btn", {n: g.n})}</button>
      </div>
    </div>
    <div class="track" role="img" aria-label="${P(g.current_pct)} / ${P(g.ratio)}"><div class="fill ${g.status}" style="width:${Math.min(100, g.current_pct * 100)}%"></div><div class="tick" style="inset-inline-start:${Math.min(100, g.ratio * 100)}%"></div></div>
    <div class="stats">${stats.join("")}</div>${detail}</article>`;
}

/* ------------------------------------------------------------------ modal (level 3) */
function openEmployees(title, ids) {
  const E = ids.map(i => S.data.employees[i]).filter(Boolean);
  const sa = E.filter(e => e.saudi), payroll = E.reduce((a, e) => a + (e.subject || 0), 0);
  $("modalTitle").textContent = `${title} (${E.length})`;
  const status = e => !e.saudi ? `<span class="pill">${t("non_saudi")}</span>` : e.wage_ok ? `<span class="pill ok">${t("yes")}</span>` : `<span class="pill risk">${t("no_wage")}</span>`;
  $("modalBody").innerHTML = `<div class="mini-stats">${statCell(t("m_saudi"), N(sa.length))}${statCell(t("m_non"), N(E.length - sa.length))}${statCell(t("m_payroll"), sar(payroll))}${statCell(t("m_avg"), sar(E.length ? payroll / E.length : 0))}</div>
    <div class="tbl-wrap"><table><thead><tr><th>${t("c_name")}</th><th>${t("c_id")}</th><th>${t("c_nat")}</th><th>${t("c_occ")}</th><th>${t("c_basic")}</th><th>${t("c_total")}</th><th>${t("c_subject")}</th><th>${t("c_minw")}</th><th>${t("c_is_counted")}</th></tr></thead><tbody>
    ${E.sort((a, b) => (b.saudi - a.saudi) || (b.subject - a.subject)).map(e => `<tr><td>${esc(e.name)}</td><td class="n">${esc(e.id)}</td><td>${esc(e.nationality)}</td><td>${esc(e.occupation)}</td><td class="n">${N(e.basic)}</td><td class="n">${N(e.total)}</td><td class="n">${N(e.subject)}</td><td class="n">${N(e.min_wage)}</td><td>${status(e)}</td></tr>`).join("")}
    </tbody></table></div><div><button class="btn ghost sm" id="csvBtn" type="button">${t("copy_csv")}</button></div>`;
  $("csvBtn").onclick = () => {
    const head = [t("c_name"), t("c_id"), t("c_nat"), t("c_occ"), t("c_basic"), t("c_total"), t("c_subject"), t("c_minw")];
    const rows = E.map(e => [e.name, e.id, e.nationality, e.occupation, e.basic, e.total, e.subject, e.min_wage ?? ""]);
    const csv = "﻿" + [head, ...rows].map(r => r.map(v => `"${String(v).replaceAll('"', '""')}"`).join(",")).join("\n");
    download(new Blob([csv], {type: "text/csv"}), `${title}.csv`);
  };
  $("modal").showModal();
}
$("modalClose").onclick = () => $("modal").close();
$("modal").addEventListener("click", e => { if (e.target === $("modal")) $("modal").close(); });
function download(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }

/* ------------------------------------------------------------------ recommendations */
function escParams(p) { const o = {}; for (const [k, v] of Object.entries(p || {})) o[k] = typeof v === "string" ? esc(v) : v; return o; }
function renderRecs() {
  const R = S.data.recommendations;
  $("c-recs").textContent = R.length; $("c-recs").className = "count" + (R.some(r => r.priority === "urgent") ? " risk" : "");
  $("p-recs").innerHTML = R.length ? `<div class="recs">${R.map(r => {
    const [txt, sub] = REC[S.lang][r.kind](escParams(r.params), esc(uname(r.unit)));
    return `<div class="rec ${r.priority}"><span class="tag">${t(r.priority)}</span><div><div class="txt">${txt}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div></div>`;
  }).join("")}</div>` : `<div class="empty good">${t("no_recs")}</div>`;
}

/* ------------------------------------------------------------------ insights */
function table(head, rows, empty, emptyCls = "good") {
  if (!rows.length) return `<div class="empty ${emptyCls}">${empty}</div>`;
  return `<div class="tbl-wrap"><table><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => typeof c === "number" || c === null || c === undefined ? `<td class="n">${N(c)}</td>` : `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderIns() {
  const d = S.data;
  $("p-ins").innerHTML = `
    <div class="section-h"><h3>${t("ins_cal")}</h3></div>
    ${table([t("c_date"), t("c_event"), t("c_impact")], d.calendar.map(c => { const [ev, im] = CAL[S.lang][c.kind](c, esc(uname(c.unit))); return [c.date, ev, im]; }), t("none_cal"), "")}
    <div class="section-h"><h3>${t("ins_gap")}</h3></div>
    ${table([t("c_group"), t("c_short"), t("c_refw"), t("c_monthly"), t("c_annual"), t("c_fine")], d.gap_cost.map(r => [esc(uname(r.unit)), r.shortfall, r.ref_wage, r.monthly, r.annual, r.fine]), t("none_gap"))}
    <div class="section-h"><h3>${t("ins_cap")}</h3><span class="sub">${t("ins_cap_note")}</span></div>
    ${table([t("c_group"), t("c_n"), t("c_counted"), t("c_required"), t("c_room"), t("c_to_thr")], d.capacity.map(r => [esc(uname(r.unit)), r.n, r.counted, r.required, r.room, r.to_threshold]), "—", "")}
    <div class="section-h"><h3>${t("ins_wage")}</h3></div>
    ${table([t("c_name"), t("c_id"), t("c_occ"), t("c_subject"), t("c_minw"), t("c_monthly")], d.wage_fixes.map(r => [esc(r.name), esc(r.id), esc(r.occupation), r.subject, r.min_wage, r.monthly]), t("none_wage"))}
    <div class="section-h"><h3>${t("ins_pen")}</h3></div>
    ${table([t("c_group"), t("c_type"), t("c_count"), t("c_rate"), t("c_sum"), t("c_state")], d.penalties.map(p => [esc(uname(p.unit)), t("pen_" + p.type), p.count, p.rate, p.total, p.active ? `<span class="pill risk">${t("active")}</span>` : `<span class="pill grace">${t("expected")}</span>`]), t("none_pen"))}
    ${d.penalties_verified ? "" : `<p class="note">${t("pen_unverified")}</p>`}`;
}

/* ------------------------------------------------------------------ simulator */
function renderSim() {
  const titles = [...new Set([...(S.rules?.professions || []).map(p => p.title), ...Object.values(S.data.employees).map(e => e.occupation)])].sort();
  const emps = Object.values(S.data.employees).sort((a, b) => a.occupation.localeCompare(b.occupation, "ar"));
  const prev = S.sim || {occupation: "أخصائي تسويق", saudi: false, wage: 7000, count: 1, remove: ""};
  $("p-sim").innerHTML = `<div class="section-h"><h3>${t("sim_h")}</h3></div>
    <form id="simForm" class="form-grid">
      <div class="field" style="grid-column:span 2"><label for="sim_occ">${t("sim_occ")}</label><input id="sim_occ" list="titles" value="${esc(prev.occupation)}"><datalist id="titles">${titles.map(x => `<option value="${esc(x)}">`).join("")}</datalist></div>
      <div class="field"><span class="lab">${t("sim_nat")}</span><div class="seg"><label><input type="radio" name="sim_nat" value="1" ${prev.saudi ? "checked" : ""}><span>${t("saudi")}</span></label><label><input type="radio" name="sim_nat" value="0" ${prev.saudi ? "" : "checked"}><span>${t("non")}</span></label></div></div>
      <div class="field"><label for="sim_wage">${t("sim_wage")}</label><input id="sim_wage" type="number" min="0" step="500" value="${prev.wage}"></div>
      <div class="field"><label for="sim_count">${t("sim_count")}</label><input id="sim_count" type="number" min="0" max="100" value="${prev.count}"></div>
      <div class="field" style="grid-column:span 2"><label for="sim_rm">${t("sim_remove")}</label><select id="sim_rm"><option value="">—</option>${emps.map(e => `<option value="${esc(e.id)}" ${prev.remove === e.id ? "selected" : ""}>${esc(e.name)} — ${esc(e.occupation)}</option>`).join("")}</select></div>
      <div class="field"><button class="btn" type="submit">${t("sim_run")}</button></div>
    </form><div id="simOut"></div>`;
  $("simForm").onsubmit = async e => {
    e.preventDefault();
    S.sim = {occupation: $("sim_occ").value.trim(), saudi: document.querySelector('input[name="sim_nat"]:checked').value === "1",
             wage: +$("sim_wage").value || 0, count: +$("sim_count").value || 0, remove: $("sim_rm").value};
    try {
      const r = await api("/api/simulate", {token: S.token, settings: S.settings, occupation: S.sim.occupation, saudi: S.sim.saudi,
                                            wage: S.sim.wage, count: S.sim.count, remove_ids: S.sim.remove ? [S.sim.remove] : []});
      const worse = r.after.penalty_active > r.before.penalty_active || r.after.restricted_violations > r.before.restricted_violations || r.after.shortfall > r.before.shortfall;
      const cell = x => x ? t("sim_cell", {st: t("st_" + x.status), c: N(x.counted), r: N(x.required)}) : "—";
      $("simOut").innerHTML = `<div class="banner ${worse ? "err" : ""}" style="margin-bottom:12px">${worse ? t("sim_bad") : t("sim_good")}</div>
        <div class="mini-stats" style="margin-bottom:12px">${statCell(t("k_active"), sar(r.after.penalty_active), `${t("before")}: ${sar(r.before.penalty_active)}`)}${statCell(t("k_restricted"), N(r.after.restricted_violations), `${t("before")}: ${N(r.before.restricted_violations)}`)}${statCell(t("k_short"), N(r.after.shortfall), `${t("before")}: ${N(r.before.shortfall)}`)}</div>
        ${table([t("c_group"), t("before"), t("after")], r.comparison.map(c => [esc(uname(c.unit)), cell(c.before), cell(c.after)]), "—", "")}`;
    } catch (err) { $("simOut").innerHTML = `<div class="banner err">${esc(err.message)}</div>`; }
  };
}

/* ------------------------------------------------------------------ rules editor */
const SCOPES = ["group", "subgroup", "restricted"];
function phasesToText(ph) { return ph.map(p => `${p.effective_date}=${Math.round(p.ratio * 1000) / 10}`).join("; "); }
function textToPhases(s) { return s.split(/[;؛]/).map(x => x.trim()).filter(Boolean).map(x => { const [d, r] = x.split("="); return {effective_date: d.trim(), ratio: parseFloat(r) / 100}; }); }
function wageText(w) { if (!w) return ""; return w.default ? String(w.default) : [w.bachelor, w.diploma].filter(Boolean).join("/"); }
function textToWage(s) { s = s.trim(); if (!s) return null; const [a, b] = s.split("/").map(x => parseFloat(x)); return b ? {bachelor: a, diploma: b} : {default: a}; }

function renderRules() {
  if (!S.rules) { $("p-rules").innerHTML = "…"; return; }
  const R = S.rules, gids = R.groups.map(g => g.id);
  const q = S.profQuery.trim(), plist = R.professions.map((p, i) => ({p, i})).filter(({p}) => !q || p.title.includes(q) || (p.code || "").includes(q) || p.group.includes(q));
  const scopeLbl = s => ({group: t("r_group_scope"), subgroup: t("r_subgroup"), restricted: t("r_restricted")}[s]);
  $("p-rules").innerHTML = `<div class="section-h"><h3>${t("rules_h")}</h3><span class="sub">v${esc(R.version || "")}</span></div><p class="note">${t("rules_note")}</p>
    <div class="section-h"><h3>${t("r_groups")}</h3><button class="btn ghost sm" id="addGroup" type="button">${t("r_add_group")}</button></div>
    <div class="tbl-wrap"><table style="min-width:1350px"><thead><tr><th>${t("r_on")}</th><th>${t("r_id")}</th><th>${t("r_name")}</th><th>${t("r_name_en")}</th><th>${t("r_scope")}</th><th>${t("r_thr")}</th><th>${t("r_est")}</th><th>${t("r_wage")}</th><th>${t("r_phases")}</th><th>${t("r_url")}</th></tr></thead><tbody>
    ${R.groups.map((g, i) => `<tr data-g="${i}"><td><input type="checkbox" data-k="enabled" ${g.enabled !== false ? "checked" : ""}></td>
      <td><input class="cell-in" data-k="id" value="${esc(g.id)}" style="width:140px"></td><td><input class="cell-in" data-k="name" value="${esc(g.name)}" style="width:190px"></td>
      <td><input class="cell-in" data-k="name_en" value="${esc(g.name_en || "")}" style="width:190px"></td>
      <td><select class="cell-in" data-k="scope">${SCOPES.map(s => `<option value="${s}" ${g.scope === s ? "selected" : ""}>${scopeLbl(s)}</option>`).join("")}</select></td>
      <td><input class="cell-in num" type="number" min="1" data-k="min_headcount" value="${g.min_headcount}"></td>
      <td><input class="cell-in num" type="number" min="0" data-k="min_establishment_size" value="${g.min_establishment_size || ""}" placeholder="—"></td>
      <td><input class="cell-in" data-k="min_wage" value="${esc(wageText(g.min_wage))}" style="width:100px" placeholder="5500 | 6000/4500"></td>
      <td><input class="cell-in" data-k="phases" value="${esc(phasesToText(g.phases))}" style="width:260px"></td>
      <td><input class="cell-in" data-k="source_url" value="${esc(g.source_url || "")}" style="width:260px" dir="ltr"></td></tr>`).join("")}
    </tbody></table></div>
    <div class="section-h"><h3>${t("r_profs")} (${R.professions.length})</h3><div style="display:flex;gap:8px;flex-wrap:wrap"><input class="cell-in" id="profSearch" placeholder="${t("r_search")}" value="${esc(S.profQuery)}" style="width:220px"><button class="btn ghost sm" id="addProf" type="button">${t("r_add_prof")}</button></div></div>
    <div class="tbl-wrap"><table style="min-width:900px"><thead><tr><th>${t("c_title")}</th><th>${t("c_code")}</th><th>${t("r_group")}</th><th>${t("r_eff")}</th><th>${t("r_alias")}</th><th></th></tr></thead><tbody>
    ${plist.slice(0, S.profPage).map(({p, i}) => `<tr data-p="${i}"><td><input class="cell-in" data-k="title" value="${esc(p.title)}" style="width:230px"></td>
      <td><input class="cell-in" data-k="code" value="${esc(p.code || "")}" style="width:90px"></td>
      <td><select class="cell-in" data-k="group">${gids.map(x => `<option ${x === p.group ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></td>
      <td><input class="cell-in" type="date" data-k="effective_date" value="${esc(p.effective_date || "")}"></td>
      <td><input class="cell-in" data-k="aliases" value="${esc((p.aliases || []).join("، "))}" style="width:180px"></td>
      <td><button class="linkbtn" type="button" data-del="${i}">${t("r_del")}</button></td></tr>`).join("")}
    </tbody></table></div>
    ${plist.length > S.profPage ? `<div><button class="btn ghost sm" id="moreProf" type="button">${t("r_more")} (${plist.length - S.profPage})</button></div>` : ""}
    <div class="section-h"><h3>${t("r_pen")}</h3></div>
    <div class="form-grid">${Object.entries(R.penalties.per_category).map(([c, v]) => `<div class="field"><span class="lab">${esc(c)} — ${t("pen_restricted")}</span><input type="number" data-pen="${esc(c)}" data-k="restricted" value="${v.restricted}"></div><div class="field"><span class="lab">${esc(c)} — ${t("pen_ratio")}</span><input type="number" data-pen="${esc(c)}" data-k="ratio" value="${v.ratio}"></div>`).join("")}</div>
    <div class="section-h"><h3>${t("key_h")}</h3></div><p class="note">${t("key_note")}</p>
    <div class="form-grid"><div class="field" style="grid-column:span 2"><label for="aiKey">${t("key_label")}</label><input id="aiKey" type="password" autocomplete="off" spellcheck="false" dir="ltr" placeholder="${S.aiKey ? "••••••••" : ""}"></div>
      <div class="field"><label for="aiProv">${t("key_provider")}</label><select id="aiProv"><option value="">${t("key_auto")}</option><option value="anthropic" ${S.aiProv === "anthropic" ? "selected" : ""}>Anthropic (Claude)</option><option value="openai" ${S.aiProv === "openai" ? "selected" : ""}>OpenAI</option></select></div>
      <div class="field"><label for="aiModel">${t("key_model")}</label><input id="aiModel" dir="ltr" value="${esc(S.aiModel)}" placeholder="${esc(t("key_model_ph", S.aiDefaults))}"></div>
      <div class="field" style="flex-direction:row;gap:8px"><button class="btn ghost sm" id="keySave" type="button">${t("key_save")}</button><button class="btn ghost sm" id="keyClear" type="button" ${S.aiKey ? "" : "disabled"}>${t("key_clear")}</button></div></div>
    <p class="note">${S.aiKey ? t("key_saved") : t("key_none")}</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="saveRules" type="button">${t("r_save")}</button><button class="btn ghost" id="exportRules" type="button">${t("r_export")}</button>
      ${document.documentElement.dataset.mode === "web" ? `<button class="btn ghost" id="defaultRules" type="button">${t("r_defaults")}</button>` : ""}
      <label class="btn ghost" for="importRules">${t("r_import")}</label><input type="file" id="importRules" accept=".json" hidden></div><div id="rulesMsg"></div>`;
  const pane = $("p-rules");
  pane.querySelectorAll("tr[data-g]").forEach(tr => tr.querySelectorAll("[data-k]").forEach(inp => inp.onchange = () => {
    const g = R.groups[+tr.dataset.g], k = inp.dataset.k;
    if (k === "enabled") g.enabled = inp.checked; else if (k === "min_headcount") g.min_headcount = parseInt(inp.value, 10) || 1;
    else if (k === "min_establishment_size") { const v = parseInt(inp.value, 10); if (v > 0) g.min_establishment_size = v; else delete g.min_establishment_size; }
    else if (k === "phases") g.phases = textToPhases(inp.value); else if (k === "min_wage") g.min_wage = textToWage(inp.value); else g[k] = inp.value.trim();
  }));
  pane.querySelectorAll("tr[data-p]").forEach(tr => tr.querySelectorAll("[data-k]").forEach(inp => inp.onchange = () => {
    const p = R.professions[+tr.dataset.p], k = inp.dataset.k;
    if (k === "aliases") p.aliases = inp.value.split(/[،,]/).map(x => x.trim()).filter(Boolean); else if (k === "effective_date") p.effective_date = inp.value || null; else p[k] = inp.value.trim();
  }));
  pane.querySelectorAll("[data-del]").forEach(b => b.onclick = () => { R.professions.splice(+b.dataset.del, 1); renderRules(); });
  pane.querySelectorAll("[data-pen]").forEach(inp => inp.onchange = () => { R.penalties.per_category[inp.dataset.pen][inp.dataset.k] = +inp.value || 0; });
  $("profSearch").oninput = e => { S.profQuery = e.target.value; S.profPage = 60; renderRules(); $("profSearch").focus(); $("profSearch").setSelectionRange(9e9, 9e9); };
  if ($("moreProf")) $("moreProf").onclick = () => { S.profPage += 200; renderRules(); };
  $("addGroup").onclick = () => { R.groups.push({id: "new_group", name: "مجموعة جديدة", name_en: "New group", scope: "group", min_headcount: 1, enabled: true,
    phases: [{effective_date: S.settings.reference_date, ratio: 0.5}], min_wage: null, source_url: "", source_title: "", decision: "", verified: false, notes: "", accreditation: "", activity_specific: false}); renderRules(); };
  $("addProf").onclick = () => { R.professions.unshift({title: "", code: "", group: gids[0], effective_date: null, subgroup: null, aliases: []}); S.profQuery = ""; renderRules(); };
  $("saveRules").onclick = async () => {
    R.professions = R.professions.filter(p => p.title);
    try { S.rules = await api("/api/rules", R, {method: "PUT"}); toast(t("r_saved")); await analyze(); renderRules(); }
    catch (e) { $("rulesMsg").innerHTML = `<div class="banner err">${esc(e.message)}</div>`; }
  };
  if ($("defaultRules")) $("defaultRules").onclick = async () => {
    try { S.rules = await api("/api/rules/defaults", {}); toast(t("r_defaults_done")); await analyze(); renderRules(); }
    catch (e) { $("rulesMsg").innerHTML = `<div class="banner err">${esc(e.message)}</div>`; }
  };
  $("aiProv").onchange = e => { S.aiProv = e.target.value; S.aiProv ? sess.set("inv-ai-provider", S.aiProv) : sess.del("inv-ai-provider"); };
  $("aiModel").onchange = e => { S.aiModel = e.target.value.trim(); S.aiModel ? sess.set("inv-ai-model", S.aiModel) : sess.del("inv-ai-model"); };
  $("keySave").onclick = () => { const v = $("aiKey").value.trim(); if (!v) return; setAiKey(v); toast(t("key_done")); renderRules(); };
  $("keyClear").onclick = () => { setAiKey(""); toast(t("key_cleared")); renderRules(); };
  $("exportRules").onclick = () => download(new Blob([JSON.stringify(R, null, 1)], {type: "application/json"}), "saudization_rules.json");
  $("importRules").onchange = async e => { const f = e.target.files[0]; if (!f) return; try { S.rules = JSON.parse(await f.text()); renderRules(); } catch (err) { $("rulesMsg").innerHTML = `<div class="banner err">${esc(err.message)}</div>`; } };
}

/* ------------------------------------------------------------------ uncovered professions */
function renderUncovered() {
  const n = S.data.summary.out_of_scope, sec = $("uncovered");
  sec.hidden = false;
  sec.innerHTML = `<button class="unc" type="button" id="uncBtn" ${n ? "" : "disabled"}><span><span class="h" id="uncH">${t("unc_h")}</span><p>${n ? t("unc_card", {n: N(n)}) : t("unc_none")}</p></span><span class="val">${N(n)}</span></button>`;
  if (n) $("uncBtn").onclick = openUncovered;
}
function openUncovered() {
  const L = [...S.data.uncovered].sort((a, b) => a.occupation.localeCompare(b.occupation, "ar") || a.name.localeCompare(b.name, "ar"));
  const sa = L.filter(e => e.saudi).length, titles = new Set(L.map(e => e.occupation)).size;
  $("modalTitle").textContent = `${t("unc_h")} (${L.length})`;
  $("modalBody").innerHTML = `<p class="note">${t("unc_note")}</p>
    <div class="mini-stats">${statCell(t("m_saudi"), N(sa))}${statCell(t("m_non"), N(L.length - sa))}${statCell(t("unc_titles"), N(titles))}</div>
    <input class="cell-in" id="uncSearch" placeholder="${t("unc_search")}" style="max-width:300px">
    <div class="tbl-wrap"><table><thead><tr><th>${t("c_name")}</th><th>${t("c_id")}</th><th>${t("c_nat")}</th><th>${t("c_occ")}</th><th>${t("c_suggest")}</th></tr></thead><tbody id="uncBody"></tbody></table></div>
    <div><button class="btn ghost sm" id="uncCsv" type="button">${t("copy_csv")}</button></div>`;
  const draw = q => { $("uncBody").innerHTML = L.filter(e => !q || `${e.name} ${e.occupation} ${e.id}`.includes(q))
    .map(e => `<tr><td>${esc(e.name)}</td><td class="n">${esc(e.id)}</td><td>${esc(e.nationality)}</td><td>${esc(e.occupation)}</td><td>${esc(e.suggestion)}</td></tr>`).join(""); };
  draw(""); $("uncSearch").oninput = e => draw(e.target.value.trim());
  $("uncCsv").onclick = () => {
    const rows = L.map(e => [e.name, e.id, e.nationality, e.occupation, e.suggestion]);
    const csv = "﻿" + [[t("c_name"), t("c_id"), t("c_nat"), t("c_occ"), t("c_suggest")], ...rows].map(r => r.map(v => `"${String(v).replaceAll('"', '""')}"`).join(",")).join("\n");
    download(new Blob([csv], {type: "text/csv"}), `${t("unc_h")}.csv`);
  };
  $("modal").showModal();
}

/* ------------------------------------------------------------------ Smart Advisor (AI): decision text → draft → review → approve */
function setAiKey(v) { S.aiKey = v; v ? sess.set("inv-ai-key", v) : sess.del("inv-ai-key"); }
const blankDraft = () => ({group: {id: "new_group", name: "", name_en: "", scope: "group", min_headcount: 1, min_establishment_size: null, phases: [], min_wage: null,
  decision: "", decision_en: "", source_title: "", source_url: "", notes: "", accreditation: "", activity_specific: false, enabled: true, verified: false}, professions: []});

function draftForm(a) {
  const g = a.draft.group, fld = (id, lab, val, extra = "", span = 1, ltr = false) =>
    `<div class="field" style="grid-column:span ${span}"><label for="${id}">${lab}</label><input class="cell-in" id="${id}" value="${esc(val ?? "")}" ${extra} ${ltr ? 'dir="ltr"' : ""}></div>`;
  const scopes = {group: t("r_group_scope"), subgroup: t("r_subgroup"), restricted: t("r_restricted")};
  return `<div class="section-h"><h3>${t("ai_review_h")}</h3><span class="tag">${t("to_verify")}</span></div><p class="note">${t("ai_review_note")}</p>
    ${a.warnings.length ? `<ul class="draft-warn">${a.warnings.map(w => `<li>${t("ai_w_" + w)}</li>`).join("")}</ul>` : ""}
    <div class="form-grid">
      ${fld("d_id", t("r_id"), g.id, "", 1, true)}${fld("d_name", t("r_name"), g.name, "", 1)}${fld("d_name_en", t("r_name_en"), g.name_en, "", 1, true)}
      <div class="field"><label for="d_scope">${t("r_scope")}</label><select class="cell-in" id="d_scope">${Object.entries(scopes).map(([k, v]) => `<option value="${k}" ${g.scope === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      ${fld("d_thr", t("r_thr"), g.min_headcount, 'type="number" min="1"')}${fld("d_est", t("r_est"), g.min_establishment_size || "", 'type="number" min="0" placeholder="—"')}
      ${fld("d_wage", t("r_wage"), wageText(g.min_wage), `placeholder="${t("ai_wage_hint")}"`, 1, true)}
      ${fld("d_phases", t("r_phases"), phasesToText(g.phases), `placeholder="${t("ai_phases_hint")}"`, 2, true)}
      ${fld("d_dec", t("ai_decision"), g.decision, "", 2)}${fld("d_dec_en", t("ai_decision_en"), g.decision_en, "", 2, true)}
      ${fld("d_url", t("r_url"), g.source_url, "", 2, true)}${fld("d_notes", t("ai_notes"), g.notes, "", 2)}
    </div>
    <div class="field"><label for="d_profs">${t("ai_profs")}</label><textarea class="cell-in" id="d_profs" rows="6">${esc(a.draft.professions.map(p => p.code ? `${p.title} | ${p.code}` : p.title).join("\n"))}</textarea></div>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="aiApprove" type="button">${t("ai_approve")}</button><button class="btn ghost" id="aiDiscard" type="button">${t("ai_discard")}</button></div>`;
}

function renderAI() {
  const a = S.ai, pane = $("p-ai");
  pane.innerHTML = `<div class="section-h"><h3>${t("ai_h")}</h3></div><p class="note">${t("ai_note")}</p><p class="note">${t("ai_privacy")}</p>
    ${S.aiKey ? "" : `<div class="banner"><span>${t("ai_need_key")}</span><button class="linkbtn" id="aiGoKey" type="button">${t("ai_go_key")}</button></div>`}
    <div class="field"><label for="ai_text">${t("ai_text")}</label><textarea class="cell-in" id="ai_text" rows="10" placeholder="${t("ai_text_ph")}">${esc(a.text)}</textarea></div>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="aiRun" type="button" ${a.busy ? "disabled" : ""}>${a.busy ? t("ai_running") : t("ai_run")}</button>
      <button class="btn ghost" id="aiManual" type="button">${t("ai_manual")}</button></div>
    <div id="aiMsg">${a.err ? `<div class="banner err">${esc(a.err)}</div>` : ""}</div>
    ${a.draft ? draftForm(a) : ""}`;
  $("ai_text").oninput = e => { a.text = e.target.value; };
  if ($("aiGoKey")) $("aiGoKey").onclick = () => selectTab("rules");
  $("aiManual").onclick = () => { a.draft = blankDraft(); a.warnings = []; a.err = ""; renderAI(); };
  $("aiRun").onclick = async () => {
    a.busy = true; a.err = ""; renderAI();
    try { const r = await api("/api/ai/extract", {text: a.text, api_key: S.aiKey, provider: S.aiProv || null, model: S.aiModel || null}); a.draft = r.draft; a.warnings = r.warnings; }
    catch (e) { a.err = e.message; }
    a.busy = false; renderAI();
  };
  if (!a.draft) return;
  $("aiDiscard").onclick = () => { a.draft = null; a.warnings = []; renderAI(); };
  $("aiApprove").onclick = async () => {
    const v = id => $(id).value.trim(), g = {...a.draft.group, id: v("d_id"), name: v("d_name"), name_en: v("d_name_en"), scope: v("d_scope"),
      min_headcount: parseInt(v("d_thr"), 10) || 1, phases: textToPhases(v("d_phases")), min_wage: textToWage(v("d_wage")),
      decision: v("d_dec"), decision_en: v("d_dec_en"), source_url: v("d_url"), notes: v("d_notes"), verified: false};
    const est = parseInt(v("d_est"), 10); if (est > 0) g.min_establishment_size = est; else delete g.min_establishment_size;
    const professions = v("d_profs").split("\n").map(l => { const [title, code = ""] = l.split("|").map(x => x.trim()); return {title, code}; }).filter(p => p.title);
    try { S.rules = await api("/api/rules/groups", {group: g, professions}); toast(t("ai_added")); a.draft = null; a.warnings = []; a.text = ""; await analyze(); renderAI(); }
    catch (e) { $("aiMsg").innerHTML = `<div class="banner err">${esc(e.message)}</div>`; }
  };
}

/* ------------------------------------------------------------------ data */
function renderData() {
  const d = S.data, unitName = Object.fromEntries(d.groups.map(g => [g.unit_id, gname(g)]));
  $("p-data").innerHTML = `<div class="section-h"><h3>${t("data_unmatched")}</h3><span class="sub">${t("data_unmatched_note")}</span></div>
    ${table([t("c_occ"), t("c_n"), t("c_saudi"), t("c_suggest")], d.unmatched.map(u => [esc(u.occupation), u.n, u.saudi, esc(u.suggestion)]), "—", "")}
    <div class="section-h"><h3>${t("data_all")}</h3><input class="cell-in" id="empSearch" placeholder="${t("search_emp")}" style="width:260px"></div>
    <div class="tbl-wrap" style="max-height:520px;overflow:auto"><table><thead><tr><th>${t("c_name")}</th><th>${t("c_id")}</th><th>${t("c_nat")}</th><th>${t("c_occ")}</th><th>${t("c_unit")}</th><th>${t("c_subject")}</th><th>${t("c_minw")}</th></tr></thead><tbody id="empBody"></tbody></table></div>`;
  const all = Object.values(d.employees), draw = q => {
    $("empBody").innerHTML = all.filter(e => !q || `${e.name} ${e.occupation} ${e.id}`.includes(q)).map(e => `<tr><td>${esc(e.name)}</td><td class="n">${esc(e.id)}</td><td>${esc(e.nationality)}</td><td>${esc(e.occupation)}</td><td>${e.unit_id ? esc(unitName[e.unit_id] || e.unit_id) : `<span class="pill">${t("not_targeted")}</span>`}</td><td class="n">${N(e.subject)}</td><td class="n">${N(e.min_wage)}</td></tr>`).join("");
  };
  draw(""); $("empSearch").oninput = e => draw(e.target.value.trim());
}

/* ------------------------------------------------------------------ tabs, drawer, files, export */
const TABS = ["comp", "recs", "ins", "sim", "rules", "ai", "data"];
function selectTab(k) {
  S.tab = k; TABS.forEach(x => { const on = x === k; $("t-" + x).setAttribute("aria-selected", on); $("t-" + x).tabIndex = on ? 0 : -1; $("p-" + x).hidden = !on; });
  if (k === "rules") renderRules();
  if (k === "ai") renderAI();
}
TABS.forEach((x, i) => { $("t-" + x).onclick = () => selectTab(x); $("t-" + x).onkeydown = e => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const dir = (e.key === "ArrowLeft") === (document.documentElement.dir === "rtl") ? 1 : -1, n = TABS[(i + dir + TABS.length) % TABS.length];
  selectTab(n); $("t-" + n).focus(); }; });

function fillSettings() {
  const s = S.settings; $("s_date").value = s.reference_date; $(s.wage_tier === "diploma" ? "s_tier_d" : "s_tier_b").checked = true;
  $("s_weight").value = s.below_min_weight ?? ""; $("s_activity").checked = s.include_activity_specific; $("s_cat").value = s.category ?? ""; $("s_rep").value = s.repeat_multiplier ?? "";
}
function openDrawer() { fillSettings(); $("scrim").hidden = false; $("drawer").hidden = false; $("closeSettings").focus(); }
function closeDrawer() { $("scrim").hidden = true; $("drawer").hidden = true; $("openSettings").focus(); }
$("openSettings").onclick = openDrawer; $("closeSettings").onclick = closeDrawer; $("scrim").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("drawer").hidden) closeDrawer(); });
$("applySettings").onclick = () => {
  const v = id => $(id).value;
  S.settings = {reference_date: v("s_date") || S.settings.reference_date, wage_tier: document.querySelector('input[name="s_tier"]:checked').value,
                below_min_weight: v("s_weight") === "" ? null : +v("s_weight"), include_activity_specific: $("s_activity").checked,
                category: v("s_cat") || null, repeat_multiplier: v("s_rep") === "" ? null : +v("s_rep")};
  closeDrawer(); analyze();
};

$("gosiInput").onchange = e => { const f = e.target.files[0]; if (f) uploadFile(f); e.target.value = ""; };
const drop = $("drop");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });
$("demoBtn").onclick = loadDemo;

$("exportBtn").onclick = async () => {
  if (!S.token) return;
  try {
    const r = await api("/api/report", {token: S.token, settings: S.settings, lang: S.lang}, {raw: true});
    const cd = r.headers.get("Content-Disposition") || "", m = cd.match(/filename\*=UTF-8''([^;]+)/);
    download(await r.blob(), m ? decodeURIComponent(m[1]) : "report.xlsx"); $("exportMsg").textContent = t("exported");
  } catch (e) { $("exportMsg").textContent = e.message; }
};

/* ------------------------------------------------------------------ boot */
(async function boot() {
  document.querySelectorAll("[data-repo]").forEach(a => { a.href = REPO_URL; });
  applyLang();
  try { S.rules = await api("/api/rules"); } catch (e) { /* rules tab will retry */ }
  await loadDemo();
})();
