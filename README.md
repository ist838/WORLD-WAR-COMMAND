
# WORLD WAR COMMAND

온라인 실시간 세계 정복 전략 게임

## 주요 기능

- 온라인 멀티플레이
- 방 생성 및 방 코드 참가
- 최대 55명 접속 제한
- 실시간 국가 소유권 동기화
- 병력 생산
- 국가 공격 및 점령
- 금 생산
- WebSocket 통신

## 기술

- Python
- FastAPI
- WebSocket
- HTML
- JavaScript
- Render
- GitHub

## 실행

설치:

pip install -r requirements.txt

실행:

uvicorn server:app --host 0.0.0.0 --port 8000

## Render 설정

Build Command:

pip install -r requirements.txt

Start Command:

uvicorn server:app --host 0.0.0.0 --port $PORT

## 주의

현재 버전은 프로토타입입니다.
게임 상태는 서버 메모리에 저장됩니다.
서버가 재시작되면 방과 게임 데이터가 초기화됩니다.
