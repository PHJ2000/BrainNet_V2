FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.116.1 uvicorn==0.35.0 sqlalchemy==2.0.43 asyncpg==0.30.0 httpx==0.28.1 websockets==15.0.1
COPY app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--no-access-log"]
