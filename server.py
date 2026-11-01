
import asyncio
import random
import string
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="WORLD WAR COMMAND")

MAX_PLAYERS = 55

COUNTRIES = {
    "USA": {"name": "미국", "x": -100, "y": 40, "neighbors": ["CAN", "BRA"]},
    "CAN": {"name": "캐나다", "x": -105, "y": 58, "neighbors": ["USA"]},
    "BRA": {"name": "브라질", "x": -50, "y": -10, "neighbors": ["USA"]},
    "GBR": {"name": "영국", "x": -3, "y": 53, "neighbors": ["FRA"]},
    "FRA": {"name": "프랑스", "x": 2, "y": 47, "neighbors": ["GBR", "DEU"]},
    "DEU": {"name": "독일", "x": 10, "y": 51, "neighbors": ["FRA", "RUS"]},
    "RUS": {"name": "러시아", "x": 90, "y": 60, "neighbors": ["DEU", "CHN"]},
    "CHN": {"name": "중국", "x": 105, "y": 35, "neighbors": ["RUS", "IND", "KOR"]},
    "IND": {"name": "인도", "x": 78, "y": 22, "neighbors": ["CHN"]},
    "KOR": {"name": "대한민국", "x": 127, "y": 36, "neighbors": ["CHN", "JPN"]},
    "JPN": {"name": "일본", "x": 139, "y": 37, "neighbors": ["KOR"]},
    "AUS": {"name": "호주", "x": 134, "y": -25, "neighbors": ["IND"]}
}

rooms = {}


class JoinRequest(BaseModel):
    name: str
    room: str = ""


def new_room_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_room():
    code = new_room_code()

    while code in rooms:
        code = new_room_code()

    rooms[code] = {
        "players": {},
        "connections": {},
        "countries": {
            key: {
                "owner": None,
                "units": 0
            }
            for key in COUNTRIES
        }
    }

    return code


def public_state(room):
    data = rooms[room]

    return {
        "room": room,
        "countries": data["countries"],
        "players": {
            pid: {
                "name": p["name"],
                "nation": p["nation"],
                "gold": p["gold"],
                "online": p["online"]
            }
            for pid, p in data["players"].items()
        },
        "map": COUNTRIES
    }


async def broadcast(room):
    if room not in rooms:
        return

    message = {
        "type": "state",
        "data": public_state(room)
    }

    disconnected = []

    for pid, ws in list(rooms[room]["connections"].items()):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(pid)

    for pid in disconnected:
        rooms[room]["connections"].pop(pid, None)

        if pid in rooms[room]["players"]:
            rooms[room]["players"][pid]["online"] = False


@app.get("/")
async def home():
    return FileResponse(Path("index.html"))


@app.get("/api/health")
async def health():
    return {"status": "online", "game": "WORLD WAR COMMAND"}


@app.post("/api/join")
async def join_game(req: JoinRequest):
    name = req.name.strip()[:20]

    if not name:
        raise HTTPException(400, "닉네임을 입력하세요.")

    code = req.room.strip().upper()

    if not code:
        code = create_room()
    elif code not in rooms:
        raise HTTPException(404, "존재하지 않는 방입니다.")

    room = rooms[code]
    players = room["players"]

    if len(players) >= MAX_PLAYERS:
        raise HTTPException(400, "방이 가득 찼습니다.")

    player_id = "".join(
        random.choices(string.ascii_letters + string.digits, k=24)
    )

    # 국가별 플레이어 수를 계산하여 인원이 적은 국가에 배정
    nation_counts = {key: 0 for key in COUNTRIES}

    for player in players.values():
        nation_counts[player["nation"]] += 1

    nation = min(nation_counts, key=nation_counts.get)

    players[player_id] = {
        "name": name,
        "nation": nation,
        "gold": 100,
        "online": False
    }

    # 시작 국가 확보
    country = room["countries"][nation]

    if country["owner"] is None:
        country["owner"] = nation
        country["units"] = 10

    await broadcast(code)

    return {
        "room": code,
        "player_id": player_id,
        "nation": nation,
        "state": public_state(code)
    }


@app.websocket("/ws/{room}/{player_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room: str,
    player_id: str
):
    if room not in rooms:
        await websocket.close(code=4004)
        return

    if player_id not in rooms[room]["players"]:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    data = rooms[room]
    data["connections"][player_id] = websocket
    data["players"][player_id]["online"] = True

    await websocket.send_json({
        "type": "state",
        "data": public_state(room)
    })

    await broadcast(room)

    try:
        while True:
            message = await websocket.receive_json()
            action = message.get("action")

            player = data["players"].get(player_id)

            if not player:
                continue

            nation = player["nation"]

            if action == "train":
                if player["gold"] < 10:
                    await websocket.send_json({
                        "type": "error",
                        "message": "금이 부족합니다."
                    })
                    continue

                owned = [
                    c for c, info in data["countries"].items()
                    if info["owner"] == nation
                ]

                if not owned:
                    continue

                target = message.get("country")

                if target not in owned:
                    continue

                player["gold"] -= 10
                data["countries"][target]["units"] += 5

            elif action == "attack":
                origin = message.get("origin")
                target = message.get("target")

                if origin not in COUNTRIES or target not in COUNTRIES:
                    continue

                if origin not in COUNTRIES[target]["neighbors"]:
                    continue

                source = data["countries"][origin]
                destination = data["countries"][target]

                if source["owner"] != nation:
                    continue

                if destination["owner"] == nation:
                    continue

                if source["units"] < 6:
                    await websocket.send_json({
                        "type": "error",
                        "message": "공격할 병력이 부족합니다."
                    })
                    continue

                attack_units = 5
                source["units"] -= attack_units

                if destination["owner"] is None:
                    destination["owner"] = nation
                    destination["units"] = attack_units

                elif attack_units > destination["units"]:
                    destination["owner"] = nation
                    destination["units"] = attack_units - destination["units"]

                else:
                    destination["units"] -= attack_units

            await broadcast(room)

    except WebSocketDisconnect:
        pass

    finally:
        if room in rooms:
            data = rooms[room]

            if data["connections"].get(player_id) is websocket:
                data["connections"].pop(player_id, None)
                data["players"][player_id]["online"] = False

            await broadcast(room)


async def economy_loop():
    while True:
        await asyncio.sleep(10)

        for room, data in list(rooms.items()):
            for pid, player in data["players"].items():
                player["gold"] += 5

            for country in data["countries"].values():
                if country["owner"] is not None:
                    country["units"] += 1

            await broadcast(room)


@app.on_event("startup")
async def startup():
    asyncio.create_task(economy_loop())
                        room["host"] = next(iter(room["players"]))
                    await broadcast(code)
