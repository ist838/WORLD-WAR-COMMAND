
import asyncio
import json
import random
import string
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="WORLD WAR COMMAND")
ROOT = Path(__file__).parent

app.mount("/static", StaticFiles(directory=ROOT), name="static")

# 게임에서 사용하는 국가 목록과 지도상의 대표 좌표
COUNTRIES = {
    "USA": {"name": "미국", "lat": 39, "lon": -98, "color": "#4da3ff"},
    "CAN": {"name": "캐나다", "lat": 56, "lon": -106, "color": "#ff7777"},
    "MEX": {"name": "멕시코", "lat": 23, "lon": -102, "color": "#6dd59b"},
    "BRA": {"name": "브라질", "lat": -10, "lon": -52, "color": "#6dd59b"},
    "GBR": {"name": "영국", "lat": 54, "lon": -2, "color": "#4da3ff"},
    "FRA": {"name": "프랑스", "lat": 46, "lon": 2, "color": "#4da3ff"},
    "DEU": {"name": "독일", "lat": 51, "lon": 10, "color": "#4da3ff"},
    "POL": {"name": "폴란드", "lat": 52, "lon": 19, "color": "#ff7777"},
    "UKR": {"name": "우크라이나", "lat": 49, "lon": 32, "color": "#ff7777"},
    "TUR": {"name": "튀르키예", "lat": 39, "lon": 35, "color": "#6dd59b"},
    "EGY": {"name": "이집트", "lat": 26, "lon": 30, "color": "#6dd59b"},
    "ZAF": {"name": "남아프리카공화국", "lat": -29, "lon": 24, "color": "#6dd59b"},
    "IND": {"name": "인도", "lat": 21, "lon": 78, "color": "#6dd59b"},
    "CHN": {"name": "중국", "lat": 35, "lon": 103, "color": "#ff7777"},
    "KOR": {"name": "대한민국", "lat": 36.5, "lon": 127.8, "color": "#4da3ff"},
    "JPN": {"name": "일본", "lat": 36, "lon": 138, "color": "#4da3ff"},
    "AUS": {"name": "호주", "lat": -25, "lon": 133, "color": "#4da3ff"},
    "IDN": {"name": "인도네시아", "lat": -2, "lon": 118, "color": "#6dd59b"},
    "SAU": {"name": "사우디아라비아", "lat": 24, "lon": 45, "color": "#6dd59b"},
    "RUS": {"name": "러시아", "lat": 60, "lon": 90, "color": "#ff7777"},
}


def fresh_state(country="KOR"):
    return {
        "turn": 1,
        "funds": 120,
        "stability": 100,
        "units": {
            "infantry": 4,
            "armor": 2,
            "air": 1,
            "navy": 1,
        },
        "owned": [country],
        "alliances": [],
        "wars": [],
        "events": ["작전 개시: 국가를 선택하고 부대를 편성하세요."],
        "battles": [],
        "country_owner": {country: "player"},
        "players": {},
    }


rooms: dict[str, dict[str, Any]] = {}
clients: dict[str, set[WebSocket]] = {}
lock = asyncio.Lock()


def room_code():
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=5)
    )


def public_room(room):
    state = room["state"]

    return {
        "code": room["code"],
        "host": room["host"],
        "started": room["started"],
        "players": [
            {
                "id": pid,
                "name": player["name"],
                "country": player["country"],
            }
            for pid, player in room["players"].items()
        ],
        "state": state,
        "countries": COUNTRIES,
    }


async def send_error(ws, message):
    await ws.send_text(
        json.dumps(
            {"type": "error", "message": message},
            ensure_ascii=False,
        )
    )


async def broadcast(code):
    room = rooms.get(code)
    if not room:
        return

    payload = json.dumps(
        {"type": "state", "room": public_room(room)},
        ensure_ascii=False,
    )

    dead = []

    for ws in list(clients.get(code, set())):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        clients.get(code, set()).discard(ws)


@app.get("/", response_class=HTMLResponse)
async def home():
    index_file = ROOT / "index.html"
    return index_file.read_text(encoding="utf-8")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "rooms": len(rooms),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    pid = "".join(
        random.choices(string.ascii_lowercase + string.digits, k=9)
    )
    code = None

    await ws.send_text(
        json.dumps({"type": "hello", "id": pid})
    )

    try:
        while True:
            data = json.loads(await ws.receive_text())
            action = data.get("action")

            async with lock:
                if action == "create":
                    code = room_code()

                    while code in rooms:
                        code = room_code()

                    name = str(data.get("name", "지휘관"))[:18]
                    name = name or "지휘관"

                    country = data.get("country", "KOR")
                    if country not in COUNTRIES:
                        country = "KOR"

                    state = fresh_state(country)
                    state["players"][pid] = {
                        "name": name,
                        "country": country,
                    }

                    rooms[code] = {
                        "code": code,
                        "host": pid,
                        "started": False,
                        "players": {
                            pid: {
                                "name": name,
                                "country": country,
                            }
                        },
                        "state": state,
                    }

                    clients[code] = {ws}

                    await ws.send_text(
                        json.dumps(
                            {"type": "created", "code": code},
                            ensure_ascii=False,
                        )
                    )
                    await broadcast(code)

                elif action == "join":
                    wanted = str(data.get("code", "")).upper()[:5]

                    if wanted not in rooms:
                        await send_error(
                            ws, "방을 찾을 수 없습니다."
                        )
                        continue

                    room = rooms[wanted]

                    if room["started"]:
                        await send_error(
                            ws, "이미 시작한 방입니다."
                        )
                        continue

                    if len(room["players"]) >= 4:
                        await send_error(
                            ws, "방 인원이 가득 찼습니다. 최대 4명입니다."
                        )
                        continue

                    name = str(data.get("name", "지휘관"))[:18]
                    name = name or "지휘관"

                    country = data.get("country", "JPN")
                    if country not in COUNTRIES:
                        country = "JPN"

                    room["players"][pid] = {
                        "name": name,
                        "country": country,
                    }

                    room["state"]["players"][pid] = {
                        "name": name,
                        "country": country,
                    }

                    clients.setdefault(wanted, set()).add(ws)
                    code = wanted

                    await ws.send_text(
                        json.dumps(
                            {"type": "joined", "code": code},
                            ensure_ascii=False,
                        )
                    )
                    await broadcast(code)

                elif action == "start":
                    if code not in rooms:
                        await send_error(
                            ws, "먼저 방을 만들거나 참가하세요."
                        )
                        continue

                    room = rooms[code]

                    if room["host"] != pid:
                        await send_error(
                            ws, "방장만 게임을 시작할 수 있습니다."
                        )
                        continue

                    room["started"] = True
                    room["state"]["events"].insert(
                        0,
                        "게임 시작! 매 턴 자금과 병력을 관리하세요.",
                    )
                    await broadcast(code)

                elif action == "leave":
                    if code in rooms:
                        room = rooms[code]
                        room["players"].pop(pid, None)
                        room["state"]["players"].pop(pid, None)
                        clients.get(code, set()).discard(ws)

                        if not room["players"]:
                            rooms.pop(code, None)
                            clients.pop(code, None)
                        else:
                            if room["host"] == pid:
                                room["host"] = next(iter(room["players"]))
                            await broadcast(code)

                    code = None

                elif action == "command":
                    if code not in rooms:
                        await send_error(
                            ws, "게임 방에 먼저 참가하세요."
                        )
                        continue

                    room = rooms[code]

                    if not room["started"]:
                        await send_error(
                            ws, "방장이 게임을 시작해야 합니다."
                        )
                        continue

                    state = room["state"]
                    player = room["players"].get(pid)

                    if not player:
                        continue

                    cmd = data.get("command")
                    target = data.get("target")
                    country = player["country"]

                    if cmd == "recruit":
                        kind = data.get("unit", "infantry")
                        costs = {
                            "infantry": 15,
                            "armor": 35,
                            "air": 50,
                            "navy": 45,
                        }

                        if kind not in costs:
                            continue

                        if state["funds"] < costs[kind]:
                            await send_error(ws, "자금이 부족합니다.")
                            continue

                        state["funds"] -= costs[kind]
                        state["units"][kind] += 1
                        state["events"].insert(
                            0,
                            f"{kind.upper()} 부대 1개를 편성했습니다. "
                            f"(-{costs[kind]} 자금)",
                        )

                    elif cmd == "end_turn":
                        state["turn"] += 1
                        state["funds"] += 25 + len(state["owned"]) * 5
                        state["stability"] = max(
                            0,
                            min(
                                100,
                                state["stability"]
                                + random.randint(-2, 3),
                            ),
                        )

                        if random.random() < 0.35:
                            state["events"].insert(
                                0,
                                "정보 보고: 국경 지역의 긴장이 높아지고 있습니다.",
                            )

                        state["events"].insert(
                            0,
                            f"{state['turn']}턴 시작: 예산이 지급되었습니다.",
                        )

                    elif cmd == "attack":
                        if target not in COUNTRIES or target == country:
                            await send_error(
                                ws, "공격할 다른 국가를 선택하세요."
                            )
                            continue

                        if state["country_owner"].get(target) == "player":
                            await send_error(
                                ws, "이미 통제 중인 국가입니다."
                            )
                            continue

                        power = (
                            state["units"]["infantry"]
                            + state["units"]["armor"] * 2
                            + state["units"]["air"] * 2
                        )

                        chance = max(
                            0.18,
                            min(
                                0.82,
                                0.25 + power * 0.025
                                + random.uniform(-0.12, 0.12),
                            ),
                        )

                        if random.random() < chance:
                            state["country_owner"][target] = "player"

                            if target not in state["owned"]:
                                state["owned"].append(target)

                            state["funds"] += 10
                            result = (
                                f"작전 성공: {COUNTRIES[target]['name']} "
                                "지역을 통제했습니다. 보급 자금 +10."
                            )
                        else:
                            state["stability"] = max(
                                0, state["stability"] - 8
                            )
                            result = (
                                f"작전 실패: {COUNTRIES[target]['name']} "
                                "지역 확보에 실패했습니다. 안정도 -8."
                            )

                        state["battles"].insert(
                            0,
                            {
                                "turn": state["turn"],
                                "target": target,
                                "result": result,
                            },
                        )
                        state["events"].insert(0, result)

                    elif cmd == "alliance":
                        if target not in COUNTRIES or target == country:
                            await send_error(
                                ws, "다른 국가를 선택하세요."
                            )
                            continue

                        if target not in state["alliances"]:
                            state["alliances"].append(target)

                        state["events"].insert(
                            0,
                            f"{COUNTRIES[target]['name']}에 외교 제안을 보냈습니다. "
                            "(게임 내 시뮬레이션)",
                        )

                    state["events"] = state["events"][:12]
                    state["battles"] = state["battles"][:8]

                    await broadcast(code)

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await send_error(ws, "서버 처리 중 오류가 발생했습니다.")
        except Exception:
            pass
    finally:
        async with lock:
            if code in rooms:
                room = rooms[code]
                room["players"].pop(pid, None)
                room["state"]["players"].pop(pid, None)
                clients.get(code, set()).discard(ws)

                if not room["players"]:
                    rooms.pop(code, None)
                    clients.pop(code, None)
                else:
                    if room["host"] == pid:
                        room["host"] = next(iter(room["players"]))
                    await broadcast(code)
