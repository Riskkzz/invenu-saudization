/* bridge.js — نسخة المتصفح: يشغّل محرك الامتثال (Python) داخل المتصفح عبر Pyodide.
   يستبدل fetch("/api/...") بالواجهة نفسها دون خادم، فلا يغادر ملف التأمينات جهاز المستخدم.
   كل الملفات (Pyodide والمكتبات) تُحمَّل من نفس الموقع؛ سياسة CSP تمنع أي اتصال آخر، عدا مزوّدي الذكاء الاصطناعي
   (backend/ai_service.PROVIDERS) لميزة المستشار الذكي، ولا يُرسل إليهم إلا نص القرار. */
"use strict";
(function () {
  const root = document.documentElement;
  root.dataset.mode = "web";
  const RULES_KEY = "inv-rules";
  let py = null;

  const proof = () => document.getElementById("proof");
  const setState = st => { const p = proof(); if (p) p.dataset.state = st; };
  const setNet = () => { const p = proof(); if (p) p.dataset.net = navigator.onLine ? "online" : "offline"; };
  window.addEventListener("online", setNet);
  window.addEventListener("offline", setNet);

  const storage = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* private mode */ } },
  };

  const ready = (async () => {
    setState("loading"); setNet();
    const pyodide = await loadPyodide({indexURL: new URL("pyodide/", location.href).href});
    await pyodide.loadPackage(["numpy", "pandas", "python-dateutil", "pytz", "six"]);
    const zip = await (await fetch("py/app.zip")).arrayBuffer();
    pyodide.unpackArchive(zip, "zip", {extractDir: "/home/pyodide/app"});
    pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
    py = pyodide.pyimport("invenu_web_bridge");
    // قواعد عدّلها المستخدم في هذا المتصفح سابقاً — تُهمل إن صدرت نسخة قواعد جديدة من INVENU
    const saved = JSON.parse(storage.get(RULES_KEY) || "null");
    if (saved && saved.base === py.default_rules_version()) py.restore_saved_rules(JSON.stringify(saved.rules));
    else if (saved) storage.del(RULES_KEY);
    setState("ready");
  })().catch(err => { console.error(err); setState("error"); throw err; });

  const json = out => {
    const {status, body} = JSON.parse(out);
    return new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
  };

  window.INVENU_FETCH = async function (path, init = {}) {
    await ready;
    const method = (init.method || "GET").toUpperCase();
    if (path === "/api/upload") {
      const f = init.body.get("file");
      return json(py.upload(new Uint8Array(await f.arrayBuffer()), f.name));
    }
    if (path === "/api/report") {
      const {status, body} = JSON.parse(py.report(init.body));
      if (status !== 200) return new Response(JSON.stringify(body), {status});
      const bin = Uint8Array.from(atob(body.b64), c => c.charCodeAt(0));
      return new Response(bin, {status, headers: {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(body.name)}`}});
    }
    if (path === "/api/ai/extract") {   // المستشار الذكي: نص القرار فقط إلى المزوّد (CSP تسمح بأصوله وحدها)
      const req = JSON.parse(py.ai_request(init.body || "{}"));
      if (req.status !== 200) return new Response(JSON.stringify(req.body), {status: req.status, headers: {"Content-Type": "application/json"}});
      const {provider, url, headers, body} = req.body;
      let status = 0, text = "";
      try { const r = await fetch(url, {method: "POST", headers, body: JSON.stringify(body), credentials: "omit", referrerPolicy: "no-referrer"}); status = r.status; text = await r.text(); }
      catch (e) { /* network or CSP: status 0 */ }
      return json(py.ai_response(provider, status, text));
    }
    if (path === "/api/rules/defaults") { storage.del(RULES_KEY); return json(py.restore_defaults()); }
    const res = json(py.call(method, path, init.body || ""));
    if (path === "/api/rules" && method === "PUT" && res.ok) {
      storage.set(RULES_KEY, JSON.stringify({base: py.default_rules_version(), rules: JSON.parse(init.body)}));
    }
    if (path === "/api/rules/groups" && method === "POST" && res.ok) {   // مجموعة معتمدة من مولّد القواعد: احفظ القواعد كاملة
      storage.set(RULES_KEY, JSON.stringify({base: py.default_rules_version(), rules: JSON.parse(py.call("GET", "/api/rules", "")).body}));
    }
    return res;
  };
})();
