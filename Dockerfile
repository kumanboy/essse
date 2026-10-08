FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8000
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd --create-home appuser
USER appuser
CMD ["sh", "-c", "exec uvicorn bot.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
