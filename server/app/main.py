import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import central, config, models, protocol, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("START group=%s public_url=%s central=%s", config.GROUP_NAME, config.PUBLIC_URL, config.CENTRAL_URL)
    central.start()
    yield
    central.stop()


app = FastAPI(title=f"Servidor de chat {config.GROUP_NAME}", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def on_invalid(request: Request, exc: RequestValidationError):
    # Se registra y se responde 422 (4xx: el central no debe reintentar). Respuesta construida a mano
    # para no depender de cómo se serializan los errores de los validadores.
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    log.warning("DROP_INVALID path=%s errors=%s", request.url.path, errors[:3])
    return JSONResponse(status_code=422, content={"detail": errors})


# === Conexión 3: central -> mi servidor (API fijada por el profesor) ====================
@app.get("/fed/health")
def fed_health():
    return protocol.fed_health_body(store.get_lamport())


@app.post("/fed/messages")
def fed_messages(m: models.IncomingMessage):
    store.receive(m.to_dict(), via="fed")
    return {"status": "ok"}  # misma respuesta para nuevo y duplicado ("responde igual", Fig. 3)


# === Conexión 1: cliente -> mi servidor (API libre) ======================================
USER_RE = r"^[a-z0-9_]{1,32}$"


class NewUser(BaseModel):
    name: str = Field(pattern=USER_RE)


class NewMessage(BaseModel):
    user: str = Field(pattern=USER_RE)
    body: str = Field(min_length=1, max_length=config.MAX_BODY_CHARS)


@app.get("/api/info")
def info():
    return {"group": config.GROUP_NAME}


@app.get("/api/status")
def status():
    return {"group": config.GROUP_NAME, "lamport": store.get_lamport(),
            "central_down": central.state["down"], "outbox": store.outbox_size(),
            "rejected": store.rejected_size(), "messages": store.r.hlen(store.K_MESSAGES)}


@app.post("/api/users", status_code=201)
def create_user(u: NewUser):
    if not store.r.sadd(store.K_USERS, u.name):
        raise HTTPException(409, "el usuario ya existe")
    log.info("USER created %s@%s", u.name, config.GROUP_NAME)
    return {"user": f"{u.name}@{config.GROUP_NAME}"}


@app.post("/api/messages", status_code=201)
def send_message(m: NewMessage):
    if not store.r.sismember(store.K_USERS, m.user):
        raise HTTPException(404, "usuario desconocido")
    msg = {
        "id": str(uuid.uuid4()),
        "from": f"{m.user}@{config.GROUP_NAME}",
        "origin": config.GROUP_NAME,
        "lamport": store.next_lamport(),
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": m.body,
    }
    store.save_local(msg)  # queda en el outbox; el hilo emisor lo entrega al central
    return msg


@app.get("/api/messages")
def list_messages(since: int = Query(0, ge=0)):
    return store.history_since(since)
