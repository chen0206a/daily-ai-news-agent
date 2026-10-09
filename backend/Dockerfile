FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend /app/backend
RUN pip install --no-cache-dir -r /app/backend/requirements.lock && pip install --no-cache-dir --no-deps /app/backend && useradd --create-home agent && mkdir /app/data && chown agent:agent /app/data
USER agent
ENV DATA_DIR=/app/data
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
