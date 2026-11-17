"""CENTRAL SIMULADO para pruebas locales. NO es el oficial: es nuestra lectura del enunciado.
Estado solo en memoria: reiniciarlo pierde registro e historial (HIPÓTESIS)."""
import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("central")
app = FastAPI(title="Central simulado (NO OFICIAL)")

FORWARD_RETRIES = int(os.environ.get("FORWARD_RETRIES", "3"))
FORWARD_TIMEOUT = float(os.environ.get("FORWARD_TIMEOUT", "2"))

lock = threading.Lock()
registry: dict = {}   # server -> url
messages: dict = {}   # id -> mensaje (historial de #general)
state = {"down": False, "delay_ms": 0}
pool = ThreadPoolExecutor(max_workers=32)


@app.middleware("http")
async def chaos(request: Request, call_next):
    """Fallos provocados por script: /_admin/down, /_admin/slow."""
    if not request.url.path.startswith("/_admin"):
        if state["delay_ms"]:
            await asyncio.sleep(state["delay_ms"] / 1000)
        if state["down"]:
            return JSONResponse(status_code=503, content={"detail": "central simulado caído"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def on_invalid(request: Request, exc: RequestValidationError):
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    log.warning("REJECT path=%s errors=%s", request.url.path, errors[:3])
    return JSONResponse(status_code=422, content={"detail": errors})


class Reg(BaseModel):
    server: StrictStr
    url: StrictStr


class Msg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: StrictStr
    from_: StrictStr = Field(alias="from")
    origin: StrictStr
    lamport: StrictInt
    sent_at: StrictStr
    body: StrictStr


@app.post("/register")
def register(r: Reg):
    with lock:
        registry[r.server] = r.url
    log.info("REGISTER server=%s url=%s", r.server, r.url)
    return {"status": "registered"}


@app.post("/messages")
def post_message(m: Msg):
    msg = {"id": m.id, "from": m.from_, "origin": m.origin, "lamport": m.lamport,
           "sent_at": m.sent_at, "body": m.body}
    with lock:
        if msg["id"] in messages:
            log.info("DUPLICATE id=%s origin=%s", msg["id"], msg["origin"])
            return {"status": "duplicate"}  # idempotente: 200 sin efectos
        messages[msg["id"]] = msg
        targets = [(s, u) for s, u in registry.items() if s != msg["origin"]]  # todos menos el origen
    log.info("ACCEPT id=%s lamport=%s origin=%s -> %s", msg["id"], msg["lamport"], msg["origin"],
             [s for s, _ in targets])
    for s, u in targets:
        pool.submit(forward, s, u, msg)
    return {"status": "accepted"}


def forward(server: str, url: str, msg: dict) -> None:
    for attempt in range(FORWARD_RETRIES + 1):
        try:
            r = requests.post(f"{url}/fed/messages", json=msg, timeout=FORWARD_TIMEOUT)
            if r.status_code < 300:
                log.info("FORWARD_OK server=%s id=%s", server, msg["id"])
                return
            if r.status_code < 500:  # 4xx: no se reintenta
                log.error("FORWARD_REJECTED server=%s id=%s status=%s", server, msg["id"], r.status_code)
                return
        except requests.RequestException as e:
            log.warning("FORWARD_FAIL server=%s id=%s intento=%d %s", server, msg["id"], attempt + 1, type(e).__name__)
        time.sleep(min(8, 0.5 * 2 ** attempt))
    log.error("FORWARD_GIVEUP server=%s id=%s (el grupo debe recuperarlo por /history)", server, msg["id"])


@app.get("/history")
def history(since: int = 0):
    """HIPÓTESIS: 'since' exclusivo, orden (lamport, origin), forma {"messages": [...]}."""
    with lock:
        items = [m for m in messages.values() if m["lamport"] > since]
    items.sort(key=lambda m: (m["lamport"], m["origin"], m["id"]))
    return {"messages": items}


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Control de fallos para las pruebas (no existen en el central real) ---------------
@app.post("/_admin/down")
def admin_down():
    state["down"] = True
    return state


@app.post("/_admin/up")
def admin_up():
    state["down"], state["delay_ms"] = False, 0
    return state


@app.post("/_admin/slow")
def admin_slow(ms: int = 0):
    state["delay_ms"] = ms
    return state


@app.post("/_admin/forget-registry")
def admin_forget():
    with lock:
        registry.clear()  # simula un reinicio del central que pierde el registro
    return {"registry": {}}


@app.get("/_admin/state")
def admin_state():
    with lock:
        return {**state, "registry": dict(registry), "messages": len(messages)}
