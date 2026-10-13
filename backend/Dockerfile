FROM python:3.12-slim

WORKDIR /app

# postgresql-client 설치
RUN apt-get update && apt-get install -y postgresql-client libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# startup.sh 복사
COPY backend/startup.sh /app/
RUN chmod +x /app/startup.sh

# 전체 백엔드 앱 복사
COPY backend/app /app/app

# Schema migrations run exclusively in Spring/Flyway.

CMD ["/app/startup.sh"]
