# 실행순서

## 실행
cp .env.example .env
JWT_SECRET_VALUE="$(openssl rand -hex 32)"
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET_VALUE}/" .env
docker compose up --build -d

## container제거
docker compose down --volumes --remove-orphans

## 중지 및 재시작
docker compose stop
docker compose start

## ADR 전환 rollback 원칙
서비스 rollback은 proxy route를 legacy FastAPI로 되돌리고 expand schema는 유지합니다.
Alembic downgrade는 version/idempotency/outbox 데이터를 삭제하므로 빈 개발·CI DB에서만 사용합니다.


## 기본 주소

brainnet-frontend   localhost:3000
brainnet-backend    localhost:8000
postgres:15         localhost:5432
