
import os
import sys

from fastapi import FastAPI


def require_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o termina con un mensaje claro."""
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"[config] Falta la variable de entorno obligatoria: {name}")
    return value


# Configuración: todo viene del entorno, nada de URLs escritas en el código.
GROUP_NAME = require_env("GROUP_NAME")
PUBLIC_URL = require_env("PUBLIC_URL")
CENTRAL_URL = require_env("CENTRAL_URL")  # aún no se usa; la etapa 3 la consume

app = FastAPI(title=f"Servidor de chat {GROUP_NAME}")

# Reloj de Lamport. En memoria por ahora; en la etapa 2 se persiste.
lamport = 0


@app.get("/fed/health")
def fed_health():
    # HIPÓTESIS: nombres de campos provisionales. Ajustar a la OpenAPI.
    return {"server": GROUP_NAME, "lamport": lamport}

