
# WORLD WAR COMMAND

브라우저에서 실행하는 현대전 세계 전략 시뮬레이션 프로토타입입니다.
DEAD SECTOR와는 별개의 프로젝트입니다.

## 기능
- 세계 지도와 국가 선택
- 국가 통제 상태 표시
- 보병, 전차, 공군, 해군 편성
- 턴 기반 자금 및 안정도
- 작전 및 외교 제안
- 싱글플레이
- 방 코드 기반 최대 4인 멀티플레이
- Three.js 기반 3D 전장 미리보기

## Render 배포

Build Command:
pip install -r requirements.txt

Start Command:
uvicorn server:app --host 0.0.0.0 --port $PORT

## 로컬 실행

pip install -r requirements.txt
uvicorn server:app --reload

브라우저에서 http://127.0.0.1:8000 을 엽니다.

## 참고
초기 프로토타입입니다. 국가별 대표 좌표를 사용하며 실제 국경 데이터는 없습니다.
온라인 게임 상태는 서버 메모리에 저장되므로 서버가 재시작되면 사라집니다.
