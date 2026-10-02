# agent/tools.py — Herramientas de Alma
# Generado por AgentKit

"""
Herramientas de Alma.

La informacion de la plataforma (zonas, tarifas, planes, reglas) le llega a Alma por el system
prompt (config/prompts.yaml), asi que para CONTESTAR preguntas no hace falta ninguna herramienta.

Una sola accion esta conectada al ciclo de tool use de Claude (en brain.py): `registrar_contacto`.
Guarda en la base de datos a quien quiere vender o ser motorizado, y las preguntas que Alma
no supo responder, para que el director les de seguimiento.
"""

import logging
from pathlib import Path

import yaml

from agent.memory import guardar_contacto

logger = logging.getLogger("agentkit")

CARPETA_KNOWLEDGE = Path("knowledge")

TIPOS_CONTACTO = (
    "negocio",              # quiere vender comida o productos
    "servicio_o_hospedaje", # clases, tours, masajes, hospedaje
    "motorizado",           # quiere ser motorizado
    "pregunta_sin_respuesta",
    "otro",
)

# Definicion que ve Claude. El modelo decide solo cuando llamarla.
DEFINICION_REGISTRAR_CONTACTO = {
    "name": "registrar_contacto",
    "description": (
        "Guarda los datos de una persona para que el equipo de San Juan Delivery le escriba despues. "
        "Usala cuando alguien quiere vender en la plataforma, ofrecer un servicio u hospedaje, ser motorizado, "
        "o cuando hizo una pregunta que no puedes responder con tu informacion. "
        "Llamala una sola vez por persona y tema, y solo despues de tener su nombre (o como llamarla) "
        "y el detalle. No pidas cedula, contrasenas ni datos de pago."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": list(TIPOS_CONTACTO)},
            "nombre": {"type": "string", "description": "Como se llama la persona"},
            "detalle": {
                "type": "string",
                "description": (
                    "Resumen breve: nombre del negocio o servicio, zona, que necesita o la pregunta exacta. "
                    "Escrito en espanol aunque la persona hable otro idioma."
                ),
            },
        },
        "required": ["tipo", "nombre", "detalle"],
    },
}


async def ejecutar_herramienta(nombre: str, argumentos: dict, telefono: str) -> str:
    """Ejecuta una herramienta pedida por Claude y devuelve el texto del resultado."""
    if nombre == "registrar_contacto":
        tipo = argumentos.get("tipo") if argumentos.get("tipo") in TIPOS_CONTACTO else "otro"
        contacto_id = await guardar_contacto(
            telefono=telefono,
            tipo=tipo,
            nombre=str(argumentos.get("nombre", "")).strip(),
            detalle=str(argumentos.get("detalle", "")).strip(),
        )
        logger.info(f"NUEVO CONTACTO #{contacto_id} ({tipo}) de {telefono}: {argumentos.get('detalle', '')[:120]}")
        return "Listo: el equipo ya tiene sus datos y le escribira en cuanto pueda. No prometas horas ni dias."
    return f"Herramienta desconocida: {nombre}"


def cargar_info_negocio() -> dict:
    """Carga la informacion del negocio desde config/business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}
