FROM python:3.12-alpine
RUN pip install --no-cache-dir fastapi==0.116.1 uvicorn==0.35.0 httpx==0.28.1 requests==2.32.4 websockets==15.0.1
WORKDIR /app
COPY app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
