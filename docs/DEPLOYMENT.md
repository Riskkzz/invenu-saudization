# INVENU — دليل المطورين والنشر (v5.2)

## التشغيل للتطوير
```bash
pip install -r requirements-dev.txt
python run.py                 # --port 9000 --no-browser
python -m pytest tests        # الاختبارات (بيانات وهمية فقط)
```

## الهيكلة
```
├── run.py                     مشغّل: يبدأ الخادم على 127.0.0.1 ويفتح المتصفح
├── web/                       نسخة المتصفح: bridge.js + invenu_web_bridge.py (تُبنى بـ packaging/build_web.py)
├── run.bat · run.sh · run.command   تشغيل بنقرة واحدة (ويندوز · لينكس · ماك)
├── backend/                   الخادم ومنطق العمل (Python / FastAPI)
│   ├── service.py             منطق الطلبات المشترك (الخادم + المتصفح)
│   ├── api.py                 طبقة HTTP: /api/upload · /api/demo · /api/analyze · /api/simulate · /api/report · /api/rules · /api/health
│   ├── engine.py              محرك الامتثال: المجموعة المهنية، المهن المقصورة، حد حجم المنشأة، سياسة النسبة الأعلى
│   ├── rules_store.py         قراءة القواعد والتحقق منها وحفظها (مع نسخة احتياطية)
│   ├── insights.py            تكلفة الفجوة، الطاقة الاستيعابية، التقويم، تصحيح الأجور، المحاكي
│   ├── presenter.py           تحويل النتائج إلى JSON للواجهة
│   ├── reports.py             تقرير Excel عربي / إنجليزي
│   ├── data_loader.py         قراءة ملف GOSI وتنظيفه
│   └── textutils.py · config.py
├── frontend/                  الواجهة (بدون أي مكتبات أو روابط خارجية)
│   ├── index.html · css/styles.css · js/app.js · js/i18n.js
│   ├── fonts/                 IBM Plex Sans Arabic (محلي، رخصة OFL)
│   └── img/wordmark.svg
├── rules/saudization_rules.json   مصدر القواعد الوحيد (لا قيم ثابتة في الكود)
├── tests/                     اختبارات المحرك والخادم
├── packaging/                 بناء النسخة التنفيذية (PyInstaller)
├── .github/workflows/          pages.yml: نشر نسخة المتصفح · build.yml: نسخ ويندوز وماك
├── Dockerfile · docker-compose.yml   سيرفر الشركة الداخلي
└── docs/DEPLOYMENT.md         هذا الملف
```

## هوية INVENU في الواجهة
- الألوان في أعلى `frontend/css/styles.css` كمتغيرات: `--bg:#E7E6E4` · `--ink:#100F0D` · البنفسجي `--mauve:#7B5AB7` / `--mauve-ink:#5E4291` / `--mauve-soft:#EEE7F8`.
- **الأصفر ممنوع**؛ البنفسجي يحل محله في كل موضع تمييز.
- الخط `IBM Plex Sans Arabic` لكل النصوص، محمَّل محلياً من `frontend/fonts/`.
- الوضع الليلي يعيد تعريف المتغيرات نفسها (`data-theme="dark"` أو تفضيل النظام).

## المسار الأول (الموصى به للعامة): نسخة المتصفح
صفحة ثابتة يعمل فيها محرك Python نفسه (`backend/`) داخل متصفح المستخدم عبر [Pyodide](https://pyodide.org) (WebAssembly).
لا خادم ولا قاعدة بيانات، وملف التأمينات لا يغادر المتصفح.

```bash
python packaging/build_web.py                 # الناتج: dist/web/ (نحو 24 م.ب)
python -m http.server -d dist/web 8000        # تجربة محلية: http://127.0.0.1:8000
```
- **النشر التلقائي على GitHub Pages:** `.github/workflows/pages.yml` يشغّل الاختبارات ويبني وينشر عند كل دفع إلى `main`.
  فعّله مرة واحدة: **Settings ← Pages ← Source: GitHub Actions**. الرابط: `https://<المالك>.github.io/<المستودع>/`.
- **أو على موقع INVENU:** ارفع محتوى `dist/web/` كما هو إلى أي استضافة ملفات ثابتة.
- **رابط المستودع** الظاهر في الصفحة: الثابت `REPO_URL` في أول `frontend/js/app.js`.

كيف تعمل:
| الملف | الدور |
|---|---|
| `backend/service.py` | منطق الطلبات المشترك: يستخدمه الخادم المحلي (`api.py`) والمتصفح معاً، فالنتائج متطابقة |
| `web/invenu_web_bridge.py` | نقطة الدخول داخل Pyodide: يستدعي `service.py` ويعيد JSON |
| `web/bridge.js` | يحمّل Pyodide ويعرّف `INVENU_FETCH` بدل `fetch("/api/...")`، فالواجهة نفسها تعمل دون تعديل |
| `packaging/build_web.py` | يجمع الواجهة + Pyodide (numpy، pandas) + openpyxl بإصدارات وبصمات SHA-256 ثابتة، ويضيف سياسة CSP |

الخصوصية تقنياً:
- كل الملفات تُخدَم من نفس الموقع؛ لا CDN ولا مكتبات خارجية ولا أدوات تتبع.
- سياسة CSP في الصفحة: `connect-src 'self'` تمنع أي اتصال بجهة أخرى.
- بعد التحميل لا تحتاج الصفحة الإنترنت إطلاقاً (اختبار «افصل الإنترنت» في الواجهة).
- القواعد التي يعدّلها المستخدم تُحفظ في متصفحه فقط (`localStorage`)، وتُهمل تلقائياً عند صدور نسخة قواعد جديدة.

## المسار الثاني: النسخة التنفيذية (بديل لمن يفضّل برنامجاً على جهازه)
النسخة التنفيذية لا تحتاج Python على جهاز المستخدم:
1. ارفع المشروع على GitHub.
2. أنشئ وسماً: `git tag v5.2.0 && git push --tags`. يشغّل `build.yml` الاختبارات ثم يبني نسختي ويندوز وماك.
3. نزّل الملفات من تبويب **Actions** وانشرها في **GitHub Releases** مع `README.md`.

يدوياً على جهاز ويندوز أو ماك (PyInstaller لا يبني لنظام آخر):
```bash
pip install -r requirements-dev.txt
pyinstaller packaging/invenu_saudization.spec --noconfirm   # الناتج: dist/INVENU-Saudization/
```
النسخة غير موقّعة رقمياً؛ للتوزيع الواسع يُنصح بتوقيعها بشهادة توقيع شيفرة (Windows) وتوثيقها لدى Apple (macOS).

## المسار الثالث: سيرفر الشركة الداخلي (Docker)
```bash
docker compose up -d --build
docker compose ps             # الحالة healthy بعد ثوانٍ (يفحص /api/health)
```
- يستمع على `127.0.0.1:8765` في السيرفر؛ اربطه بالوكيل العكسي للشركة (Nginx / IIS / Traefik) خلف **SSO أو VPN**.
  لا يحتوي النظام على تسجيل دخول خاص به، فلا تعرضه للإنترنت العام.
- الحاوية تعمل بمستخدم بلا صلاحيات root، ونظام ملفاتها للقراءة فقط عدا مجلد البيانات `/data`.
- `INVENU_RULES_READONLY=1` (افتراضي في Docker) يمنع تعديل القواعد من الواجهة.
  لتعديلها: عدّل `/data/rules/saudization_rules.json` داخل الحجم `invenu-data` ثم `docker compose restart`.
- التحديث لإصدار جديد: `docker compose up -d --build` (القواعد في الحجم لا تُستبدل).

بدون compose:
```bash
docker build -t invenu-saudization:5.2.0 .
docker run -d -p 127.0.0.1:8765:8765 -v invenu-data:/data invenu-saudization:5.2.0
```

## تحديث القواعد عند صدور قرار جديد
من تبويب «إعدادات القواعد» (في النسخة المحلية): عدّل النسبة أو حد السريان أو حد حجم المنشأة أو الأجر أو المراحل
(`2026-10-27=50; 2027-10-27=60`) أو رابط الدليل، أو أضف مجموعة أو مسمى، ثم «حفظ القواعد». تُحفظ نسخة احتياطية في `rules/backups/`.

حقول المجموعة الأساسية في `saudization_rules.json`:
| الحقل | المعنى |
|---|---|
| `scope` | `group` (المجموعة كاملة) · `subgroup` (كل مجموعة فرعية) · `restricted` (مقصورة 100%، فحص لكل موظف) |
| `min_headcount` | حد السريان: أقل عدد عاملين في مهن المجموعة ليسري القرار |
| `min_establishment_size` | اختياري: أقل إجمالي عمال في المنشأة ليسري القرار (مثل السلامة والصحة المهنية: 50) |
| `phases` | المراحل: تاريخ السريان والنسبة |
| `min_wage` | الحد الأدنى للأجر: `default` أو `bachelor` / `diploma` |
| `source_url` | رابط الدليل الإجرائي الرسمي (يظهر في زر «ℹ️ الدليل الوزاري») |
| `verified` | `false` يُظهر وسم «للتأكيد» بجانب المجموعة |

## نقاط مفتوحة
- مبالغ الغرامات تقديرية ولم يُتحقق منها من جدول المخالفات المحدّث (فبراير 2026، القرار 112377).
- مجموعتا إدارة المشاريع والقانونية موسومتان «للتأكيد».
- مسميات المهن تبقى بالعربية في الوضع الإنجليزي لأنها كما تُسجّل في التأمينات.
