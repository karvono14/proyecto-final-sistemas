"""TODO(OpenAPI): todo lo que depende del protocolo del profesor está AQUÍ.
Cuando llegue la especificación oficial, se ajusta este archivo (y models.py)."""
from . import config

# Rutas del central: vienen del enunciado (sección 4).
REGISTER_PATH = "/register"
MESSAGES_PATH = "/messages"
HISTORY_PATH = "/history"
HEALTH_PATH = "/health"

# HIPÓTESIS H3: historial completo y deduplicar por id.
HISTORY_SINCE = 0


def register_body() -> dict:
    return {"server": config.GROUP_NAME, "url": config.PUBLIC_URL}  # enunciado, sec. 4


def message_body(msg: dict) -> dict:
    return msg  # el formato del mensaje lo da el enunciado


def fed_health_body(lamport: int) -> dict:
    return {"server": config.GROUP_NAME, "lamport": lamport}  # HIPÓTESIS H1


def parse_history(payload) -> list:
    """HIPÓTESIS H2: una lista directa o {"messages": [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        return payload["messages"]
    raise ValueError("formato de /history no reconocido")
