# agent/brain.py — Cerebro de Alma
# Generado por AgentKit

"""
Conecta con Claude (Anthropic) y genera las respuestas de Alma.

El conocimiento de la plataforma (knowledge/plataforma.md) se inyecta en el system prompt.
Claude puede llamar a `registrar_contacto` y este modulo ejecuta el ciclo de tool use.
"""

import logging
import os
from pathlib import Path

import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import DEFINICION_REGISTRAR_CONTACTO, ejecutar_herramienta

load_dotenv()
logger = logging.getLogger("agentkit")

# El modelo sale del .env: no se hardcodea.
MODELO = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
ESFUERZO = os.getenv("ANTHROPIC_EFFORT", "low")
MAX_RONDAS_HERRAMIENTAS = 4

# Una sola instancia, creada al primer uso, para que el import no falle si falta la clave.
_cliente: AsyncAnthropic | None = None


def _obtener_cliente() -> AsyncAnthropic:
    global _cliente
    if _cliente is None:
        _cliente = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _cliente


def cargar_config_prompts() -> dict:
    """Carga config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_conocimiento() -> str:
    """Junta todos los .md de knowledge/ en un solo texto."""
    carpeta = Path("knowledge")
    if not carpeta.exists():
        return ""
    partes = [a.read_text(encoding="utf-8") for a in sorted(carpeta.glob("*.md"))]
    return "\n\n".join(partes)


def obtener_mensaje_error() -> str:
    return cargar_config_prompts().get(
        "error_message", "Uy, algo fallo de mi lado. Intenta de nuevo en un ratito, por favor."
    )


def obtener_mensaje_fallback() -> str:
    return cargar_config_prompts().get(
        "fallback_message", "Disculpa, no te entendi bien. ¿Me lo repites con otras palabras?"
    )


NOTA_CANAL_WEB = """

## Canal actual: chat de la pagina web
Esta persona te escribe desde el boton de chat del sitio, NO por WhatsApp, asi que NO tienes su numero.
Si va a dejar sus datos con registrar_contacto, pidele tambien un numero de WhatsApp o correo para que el equipo le escriba, y ponlo en el detalle.
"""


def construir_system_prompt(canal: str = "whatsapp") -> str:
    """Arma el system prompt con el conocimiento de la plataforma."""
    plantilla = cargar_config_prompts().get("system_prompt", "Eres un asistente amable.")
    # replace y no format: el conocimiento puede traer llaves y rompería str.format
    prompt = plantilla.replace("{conocimiento}", cargar_conocimiento())
    return prompt + NOTA_CANAL_WEB if canal == "web" else prompt


def _texto_de(respuesta) -> str:
    return "".join(b.text for b in respuesta.content if getattr(b, "type", "") == "text").strip()


async def generar_respuesta(
    mensaje: str, historial: list[dict], telefono: str, canal: str = "whatsapp"
) -> str:
    """
    Genera la respuesta de Alma.

    `historial` son los mensajes anteriores (sin el actual). Si Claude pide la herramienta
    registrar_contacto, se ejecuta y se le devuelve el resultado hasta que responda con texto.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    mensajes = list(historial) + [{"role": "user", "content": mensaje}]
    sistema = construir_system_prompt(canal)

    try:
        for _ in range(MAX_RONDAS_HERRAMIENTAS + 1):
            respuesta = await _obtener_cliente().messages.create(
                model=MODELO,
                max_tokens=1024,
                system=sistema,
                messages=mensajes,
                tools=[DEFINICION_REGISTRAR_CONTACTO],
                extra_body={"output_config": {"effort": ESFUERZO}},
            )

            if respuesta.stop_reason != "tool_use":
                texto = _texto_de(respuesta)
                logger.info(
                    f"Respuesta generada ({respuesta.usage.input_tokens} in / "
                    f"{respuesta.usage.output_tokens} out)"
                )
                return texto or obtener_mensaje_fallback()

            # Claude pidio herramientas: ejecutarlas y devolverle los resultados
            mensajes.append({"role": "assistant", "content": respuesta.content})
            resultados = []
            for bloque in respuesta.content:
                if getattr(bloque, "type", "") == "tool_use":
                    try:
                        salida = await ejecutar_herramienta(bloque.name, bloque.input, telefono)
                    except Exception as e:
                        logger.error(f"Fallo la herramienta {bloque.name}: {e}")
                        salida = "No se pudo guardar. Dile que intente de nuevo mas tarde, sin prometer nada."
                    resultados.append(
                        {"type": "tool_result", "tool_use_id": bloque.id, "content": salida}
                    )
            mensajes.append({"role": "user", "content": resultados})

        logger.error("Demasiadas rondas de herramientas sin respuesta final")
        return obtener_mensaje_error()

    except Exception as e:
        logger.error(f"Error con la API de Anthropic: {e}")
        return obtener_mensaje_error()
