
import asyncio
import random
import string
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


# ==========================================
# WORLD WAR COMMAND
# Online Multiplayer Server
# ==========================================

MAX_PLAYERS = 55
ROOM_CODE_LENGTH = 6
STARTING_GOLD = 100
ECONOMY_INTERVAL = 10
ECONOMY_REWARD = 5

# ==========================================
# 국가 데이터
# ==========================================

COUNTRIES = {
    "USA": {
        "name": "미국",
        "x": -100,
        "y": 40,
        "neighbors": ["CAN", "BRA"]
    },
    "CAN": {
        "name": "캐나다",
        "x": -105,
        "y": 58,
        "neighbors": ["USA"]
    },
    "BRA": {
        "name": "브라질",
        "x": -50,
        "y": -10,
        "neighbors": ["USA"]
    },
    "GBR": {
        "name": "영국",
        "x": -3,
        "y": 53,
        "neighbors": ["FRA"]
    },
    "FRA": {
        "name": "프랑스",
        "x": 2,
        "y": 47,
        "neighbors": ["GBR", "DEU"]
    },
    "DEU": {
        "name": "독일",
        "x": 10,
        "y": 51,
        "neighbors": ["FRA", "RUS"]
    },
    "RUS": {
        "name": "러시아",
        "x": 90,
        "y": 60,
        "neighbors": ["DEU", "CHN"]
    },
    "CHN": {
        "name": "중국",
        "x": 105,
        "y": 35,
        "neighbors": ["RUS", "IND", "KOR"]
    },
    "IND": {
        "name": "인도",
        "x": 78,
        "y": 22,
        "neighbors": ["CHN"]
    },
    "KOR": {
        "name": "대한민국",
        "x": 127,
        "y": 36,
        "neighbors": ["CHN", "JPN"]
    },
    "JPN": {
        "name": "일본",
        "x": 139,
        "y": 37,
        "neighbors": ["KOR"]
    },
    "AUS": {
        "name": "호주",
        "x": 134,
        "y": -25,
        "neighbors": ["IND"]
    }
}


# ==========================================
# 국가 연결 관계 양방향 보정
# ==========================================

for country_id, country in COUNTRIES.items():
    for neighbor in country["neighbors"]:
        if neighbor in COUNTRIES:
            if country_id not in COUNTRIES[neighbor]["neighbors"]:
                COUNTRIES[neighbor]["neighbors"].append(country_id)


# ==========================================
# 서버 상태
# ==========================================

rooms = {}
economy_task = None


# ==========================================
# FastAPI
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global economy_task

    economy_task = asyncio.create_task(economy_loop())

    yield

    if economy_task:
        economy_task.cancel()

        try:
            await economy_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="WORLD WAR COMMAND",
    version="2.0.0",
    lifespan=lifespan
)


# ==========================================
# 요청 데이터
# ==========================================

class JoinRequest(BaseModel):
    name: str
    room: str = ""


# ==========================================
# 방 코드 생성
# ==========================================

def new_room_code():
    while True:
        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=ROOM_CODE_LENGTH
            )
        )

        if code not in rooms:
            return code


# ==========================================
# 새 게임 방
# ==========================================

def create_room():
    code = new_room_code()

    rooms[code] = {
        "host": None,
        "players": {},
        "connections": {},
        "countries": {
            country_id: {
                "owner": None,
                "units": 0
            }
            for country_id in COUNTRIES
        }
    }

    return code


# ==========================================
# 국가 배정
# ==========================================

def assign_nation(room):
    counts = {
        country_id: 0
        for country_id in COUNTRIES
    }

    for player in room["players"].values():
        nation = player["nation"]

        if nation in counts:
            counts[nation] += 1

    return min(counts, key=counts.get)


# ==========================================
# 공개 게임 상태
# ==========================================

def public_state(room_code):
    room = rooms[room_code]

    players = {}

    for player_id, player in room["players"].items():
        players[player_id] = {
            "name": player["name"],
            "nation": player["nation"],
            "gold": player["gold"],
            "online": player["online"]
        }

    return {
        "room": room_code,
        "host": room["host"],
        "countries": room["countries"],
        "players": players,
        "map": COUNTRIES
    }


# ==========================================
# 전체 플레이어에게 상태 전송
# ==========================================

async def broadcast(room_code):
    room = rooms.get(room_code)

    if room is None:
        return

    message = {
        "type": "state",
        "data": public_state(room_code)
    }

    disconnected = []

    for player_id, websocket in list(
        room["connections"].items()
    ):
        try:
            await websocket.send_json(message)

        except Exception:
            disconnected.append(player_id)

    for player_id in disconnected:
        if room["connections"].get(player_id):
            room["connections"].pop(player_id, None)

        if player_id in room["players"]:
            room["players"][player_id]["online"] = False


# ==========================================
# 오류 메시지 전송
# ==========================================

async def send_error(websocket, message):
    try:
        await websocket.send_json({
            "type": "error",
            "message": message
        })
    except Exception:
        pass


# ==========================================
# 플레이어 퇴장 처리
# ==========================================

async def remove_player(room_code, player_id):
    room = rooms.get(room_code)

    if room is None:
        return

    room["connections"].pop(player_id, None)

    player = room["players"].pop(player_id, None)

    if player is None:
        return

    nation = player["nation"]

    # 해당 국가에 남은 플레이어가 있는지 확인
    nation_still_used = any(
        p["nation"] == nation
        for p in room["players"].values()
    )

    # 마지막 플레이어가 나간 경우 국가를 중립으로 변경
    if not nation_still_used:
        for country in room["countries"].values():
            if country["owner"] == nation:
                country["owner"] = None
                country["units"] = 0

    # 방장이 나간 경우 온라인 플레이어에게 방장 이전
    if room["host"] == player_id:
        online_players = [
            pid
            for pid, p in room["players"].items()
            if p["online"]
        ]

        room["host"] = (
            online_players[0]
            if online_players
            else next(iter(room["players"]), None)
        )

    # 플레이어가 전혀 없으면 방 삭제
    if not room["players"]:
        rooms.pop(room_code, None)
        return

    await broadcast(room_code)


# ==========================================
# 홈페이지
# ==========================================

@app.get("/")
async def home():
    return FileResponse("index.html")


# ==========================================
# 서버 상태 확인
# ==========================================

@app.get("/api/health")
async def health():
    return {
        "status": "online",
        "game": "WORLD WAR COMMAND",
        "version": "2.0.0",
        "rooms": len(rooms),
        "max_players": MAX_PLAYERS
    }


# ==========================================
# 방 목록
# ==========================================

@app.get("/api/rooms")
async def room_list():
    result = []

    for code, room in rooms.items():
        online_count = sum(
            1
            for player in room["players"].values()
            if player["online"]
        )

        result.append({
            "code": code,
            "players": online_count,
            "max_players": MAX_PLAYERS
        })

    return {"rooms": result}


# ==========================================
# 게임 참가 및 방 생성
# ==========================================

@app.post("/api/join")
async def join_game(req: JoinRequest):
    name = req.name.strip()[:20]

    if not name:
        raise HTTPException(
            status_code=400,
            detail="닉네임을 입력하세요."
        )

    room_code = req.room.strip().upper()

    if not room_code:
        room_code = create_room()

    elif room_code not in rooms:
        raise HTTPException(
            status_code=404,
            detail="존재하지 않는 방입니다."
        )

    room = rooms[room_code]

    if len(room["players"]) >= MAX_PLAYERS:
        raise HTTPException(
            status_code=400,
            detail="방이 가득 찼습니다."
        )

    player_id = "".join(
        random.choices(
            string.ascii_letters + string.digits,
            k=32
        )
    )

    nation = assign_nation(room)

    room["players"][player_id] = {
        "name": name,
        "nation": nation,
        "gold": STARTING_GOLD,
        "online": False
    }

    # 첫 번째 참가자를 방장으로 지정
    if room["host"] is None:
        room["host"] = player_id

    # 시작 국가 확보
    country = room["countries"][nation]

    if country["owner"] is None:
        country["owner"] = nation
        country["units"] = 10

    await broadcast(room_code)

    return {
        "room": room_code,
        "player_id": player_id,
        "nation": nation,
        "state": public_state(room_code)
    }


# ==========================================
# WebSocket 실시간 멀티플레이
# ==========================================

@app.websocket("/ws/{room_code}/{player_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_code: str,
    player_id: str
):
    room = rooms.get(room_code)

    if room is None:
        await websocket.close(code=4004)
        return

    if player_id not in room["players"]:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # 이전 연결이 있으면 종료
    old_connection = room["connections"].get(player_id)

    if old_connection:
        try:
            await old_connection.close(code=4000)
        except Exception:
            pass

    room["connections"][player_id] = websocket
    room["players"][player_id]["online"] = True

    await websocket.send_json({
        "type": "state",
        "data": public_state(room_code)
    })

    await broadcast(room_code)

    try:
        while True:
            message = await websocket.receive_json()

            if not isinstance(message, dict):
                await send_error(
                    websocket,
                    "잘못된 명령입니다."
                )
                continue

            action = message.get("action")
            player = room["players"].get(player_id)

            if player is None:
                break

            nation = player["nation"]

            # ==================================
            # 병력 생산
            # ==================================

            if action == "train":
                country_id = message.get("country")

                if country_id not in COUNTRIES:
                    await send_error(
                        websocket,
                        "존재하지 않는 국가입니다."
                    )
                    continue

                country = room["countries"][country_id]

                if country["owner"] != nation:
                    await send_error(
                        websocket,
                        "자신이 소유한 국가만 선택할 수 있습니다."
                    )
                    continue

                if player["gold"] < 10:
                    await send_error(
                        websocket,
                        "금이 부족합니다."
                    )
                    continue

                player["gold"] -= 10
                country["units"] += 5

            # ==================================
            # 국가 공격
            # ==================================

            elif action == "attack":
                origin = message.get("origin")
                target = message.get("target")

                if origin not in COUNTRIES:
                    await send_error(
                        websocket,
                        "공격 출발지가 잘못되었습니다."
                    )
                    continue

                if target not in COUNTRIES:
                    await send_error(
                        websocket,
                        "공격 대상이 잘못되었습니다."
                    )
                    continue

                if origin == target:
                    await send_error(
                        websocket,
                        "같은 국가를 공격할 수 없습니다."
                    )
                    continue

                source = room["countries"][origin]
                destination = room["countries"][target]

                # 소유권 확인
                if source["owner"] != nation:
                    await send_error(
                        websocket,
                        "자신의 국가에서만 공격할 수 있습니다."
                    )
                    continue

                # 인접 국가 확인
                if target not in COUNTRIES[origin]["neighbors"]:
                    await send_error(
                        websocket,
                        "인접한 국가만 공격할 수 있습니다."
                    )
                    continue

                if destination["owner"] == nation:
                    await send_error(
                        websocket,
                        "이미 소유한 국가입니다."
                    )
                    continue

                attack_units = 5

                if source["units"] < attack_units:
                    await send_error(
                        websocket,
                        "공격할 병력이 부족합니다."
                    )
                    continue

                source["units"] -= attack_units

                # 중립 국가
                if destination["owner"] is None:
                    destination["owner"] = nation
                    destination["units"] = attack_units

                # 적 국가
                elif attack_units > destination["units"]:
                    remaining = attack_units - destination["units"]

                    destination["owner"] = nation
                    destination["units"] = remaining

                # 공격 실패
                else:
                    destination["units"] -= attack_units

            else:
                await send_error(
                    websocket,
                    "지원하지 않는 명령입니다."
                )
                continue

            await broadcast(room_code)

    except WebSocketDisconnect:
        pass

    except Exception as error:
        print(
            f"WebSocket error: {room_code} / "
            f"{player_id}: {error}"
        )

    finally:
        # 오래된 연결이 새 연결을 제거하지 않도록 확인
        current_room = rooms.get(room_code)

        if current_room is not None:
            if current_room["connections"].get(player_id) is websocket:
                await remove_player(room_code, player_id)


# ==========================================
# 경제 및 병력 생산
# ==========================================

async def economy_loop():
    while True:
        await asyncio.sleep(ECONOMY_INTERVAL)

        for room_code in list(rooms.keys()):
            room = rooms.get(room_code)

            if room is None:
                continue

            # 온라인 플레이어에게 금 지급
            for player in room["players"].values():
                if player["online"]:
                    player["gold"] += ECONOMY_REWARD

            # 소유 국가에 병력 1명 추가
            for country in room["countries"].values():
                if country["owner"] is not None:
                    country["units"] += 1

            await broadcast(room_code)


# ==========================================
# 서버 시작
# ==========================================

@app.get("/api")
async def api_info():
    return {
        "name": "WORLD WAR COMMAND",
        "status": "running",
        "multiplayer": True,
        "max_players": MAX_PLAYERS
    }
