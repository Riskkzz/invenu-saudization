# INVENU — نسخة سيرفر الشركة الداخلي.
# ضعها خلف بوابة دخول الشركة (SSO / VPN). لا تعرضها للإنترنت العام: لا يوجد تسجيل دخول داخل الأداة.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    INVENU_DATA_DIR=/data INVENU_RULES_READONLY=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend backend
COPY frontend frontend
COPY rules rules
COPY run.py .

# مستخدم بلا صلاحيات root، ومجلد البيانات (القواعد ونسخها الاحتياطية) مملوك له
RUN useradd --system --uid 10001 --home /app invenu && mkdir -p /data && chown invenu /data
USER invenu
VOLUME /data
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status == 200 else 1)"

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
