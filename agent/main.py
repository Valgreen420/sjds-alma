# agent/main.py — Servidor FastAPI de Alma
# Generado por AgentKit

"""
Recibe los webhooks de Zernio, responde 200 enseguida y procesa el mensaje en segundo plano:
historial -> Claude -> respuesta por WhatsApp.

Protecciones: firma del webhook, deduplicacion de eventos, un candado por telefono
(mensajes seguidos de la misma persona se atienden en orden) y limite de conversaciones en memoria.
"""

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.brain import generar_respuesta, obtener_mensaje_error
from agent.memory import (
    guardar_mensaje,
    inicializar_db,
    liberar_evento,
    limpiar_eventos_viejos,
    listar_contactos,
    marcar_evento_procesado,
    obtener_historial,
)
from agent.providers import obtener_proveedor

load_dotenv()

ENTORNO = os.getenv("ENVIRONMENT", "development")
logging.basicConfig(
    level=logging.DEBUG if ENTORNO == "development" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agentkit")

PUERTO = int(os.getenv("PORT", "8000"))
LEADS_TOKEN = os.getenv("LEADS_TOKEN", "")
MAX_CARACTERES_ENTRADA = 2000

# El proveedor se crea al arrancar (no al importar) para que un .env mal puesto no tumbe el servidor
proveedor = None
error_proveedor = ""

# Un candado por telefono: dos mensajes seguidos se atienden en orden, no a la vez
_candados: dict[str, asyncio.Lock] = {}


def _candado(telefono: str) -> asyncio.Lock:
    if len(_candados) > 5000:
        for clave in [k for k, v in _candados.items() if not v.locked()]:
            _candados.pop(clave, None)
    return _candados.setdefault(telefono, asyncio.Lock())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global proveedor, error_proveedor
    await inicializar_db()
    await limpiar_eventos_viejos()
    try:
        proveedor = obtener_proveedor()
        ok, detalle = await proveedor.verificar_conexion()
        (logger.info if ok else logger.warning)(f"Conexion WhatsApp: {detalle}")
    except ValueError as e:
        error_proveedor = str(e)
        logger.error(f"Proveedor mal configurado: {e}")
    logger.info(f"Alma lista en el puerto {PUERTO} ({ENTORNO})")
    yield


app = FastAPI(title="Alma · San Juan Delivery", version="1.0.0", lifespan=lifespan)

# El boton de chat vive en otro dominio: solo se permiten las paginas del sitio
ORIGENES = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=ORIGENES, allow_methods=["POST", "GET"], allow_headers=["Content-Type", "Authorization"]
)


@app.get("/")
async def health_check():
    """Chequeo de salud: Railway lo usa para saber que el servidor vive."""
    return {
        "status": "ok" if proveedor else "degradado",
        "service": "alma-sjds",
        "proveedor": type(proveedor).__name__ if proveedor else error_proveedor,
    }


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificacion GET (solo Meta la usa; Zernio no)."""
    if not proveedor:
        raise HTTPException(status_code=503, detail="Proveedor no configurado")
    resultado = await proveedor.validar_webhook(request)
    if resultado is None:
        raise HTTPException(status_code=404, detail="No aplica")
    return int(resultado) if resultado.isdigit() else resultado


@app.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """Recibe el mensaje, valida, responde 200 y procesa aparte."""
    if not proveedor:
        raise HTTPException(status_code=503, detail="Proveedor no configurado")

    if not await proveedor.verificar_firma(request):
        raise HTTPException(status_code=401, detail="Firma invalida")

    try:
        mensajes = await proveedor.parsear_webhook(request)
    except Exception as e:
        # Un cuerpo raro no debe provocar reintentos infinitos
        logger.warning(f"Webhook ilegible: {e}")
        return {"status": "ignorado"}

    for msg in mensajes:
        if msg.es_propio or not msg.texto or not msg.telefono:
            continue
        background_tasks.add_task(procesar_mensaje, msg)

    return {"status": "ok"}


async def procesar_mensaje(msg):
    """Atiende un mensaje: historial, respuesta de Claude, envio y guardado."""
    evento_id = msg.contexto.get("evento_id") or msg.mensaje_id
    try:
        if not await marcar_evento_procesado(evento_id):
            logger.info(f"Evento duplicado ignorado: {evento_id}")
            return

        texto = msg.texto[:MAX_CARACTERES_ENTRADA]
        logger.info(f"Mensaje de {msg.telefono}: {texto[:80]}")

        async with _candado(msg.telefono):
            historial = await obtener_historial(msg.telefono)
            respuesta = await generar_respuesta(texto, historial, msg.telefono)

            enviado = await proveedor.enviar_mensaje(msg.telefono, respuesta, msg.contexto)
            if not enviado:
                # Que el reintento del proveedor SI se procese
                await liberar_evento(evento_id)
                logger.error(f"No se pudo enviar la respuesta a {msg.telefono}")
                return

            # Se guarda recien cuando salio bien: un fallo no deja un historial a medias
            await guardar_mensaje(msg.telefono, "user", texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta[:80]}")
    except Exception as e:
        logger.error(f"Error procesando mensaje: {e}", exc_info=True)
        try:
            await liberar_evento(evento_id)
            await proveedor.enviar_mensaje(msg.telefono, obtener_mensaje_error(), msg.contexto)
        except Exception:
            pass


class ChatEntrada(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=MAX_CARACTERES_ENTRADA)


# Limite por IP: evita que alguien gaste la clave de Anthropic desde el boton publico
_golpes: dict[str, list[float]] = {}
LIMITE_MENSAJES = 20
VENTANA_SEG = 600


def _excede_limite(ip: str) -> bool:
    ahora = time.monotonic()
    if len(_golpes) > 5000:
        for k in [k for k, v in _golpes.items() if not v or ahora - v[-1] > VENTANA_SEG]:
            _golpes.pop(k, None)
    recientes = [t for t in _golpes.get(ip, []) if ahora - t < VENTANA_SEG]
    if len(recientes) >= LIMITE_MENSAJES:
        _golpes[ip] = recientes
        return True
    recientes.append(ahora)
    _golpes[ip] = recientes
    return False


@app.post("/chat")
async def chat_web(entrada: ChatEntrada, request: Request):
    """Chat del boton flotante de la pagina. Misma Alma, otro canal."""
    # Detras de Railway la IP real viene en X-Forwarded-For
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    if _excede_limite(ip):
        raise HTTPException(status_code=429, detail="Muchos mensajes seguidos. Intenta en unos minutos.")

    telefono = f"web-{entrada.session_id}"
    async with _candado(telefono):
        historial = await obtener_historial(telefono)
        respuesta = await generar_respuesta(entrada.message, historial, telefono, canal="web")
        await guardar_mensaje(telefono, "user", entrada.message)
        await guardar_mensaje(telefono, "assistant", respuesta)
    return {"reply": respuesta}


@app.get("/leads")
async def ver_contactos(authorization: str = Header(default="")):
    """
    Contactos que Alma recogio (quieren vender o ser motorizado, preguntas sin respuesta).
    Protegido con LEADS_TOKEN: Authorization: Bearer <token>. Sin token configurado, queda cerrado.
    """
    esperado = f"Bearer {LEADS_TOKEN}"
    if not LEADS_TOKEN or not hmac.compare_digest(authorization.encode(), esperado.encode()):
        raise HTTPException(status_code=401, detail="No autorizado")
    return {"contactos": await listar_contactos()}
