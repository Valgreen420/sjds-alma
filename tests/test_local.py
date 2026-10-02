# tests/test_local.py — Chat de prueba en la terminal
# Generado por AgentKit
"""
Habla con Alma sin WhatsApp. Usa una base de datos temporal aparte para no ensuciar la real.

  python tests/test_local.py            # chat interactivo
  python tests/test_local.py --demo     # preguntas de ejemplo, no interactivo
Comandos en el chat: 'limpiar' borra el historial, 'salir' termina.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_local.db"

from agent.brain import generar_respuesta  # noqa: E402
from agent.memory import (  # noqa: E402
    guardar_mensaje,
    inicializar_db,
    limpiar_historial,
    listar_contactos,
    obtener_historial,
)

sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no sabe imprimir emojis

TELEFONO = "test-local-001"

PREGUNTAS_DEMO = [
    "Hola, cuanto cuesta el envio a Maderas?",
    "Y como pago? Hay que poner la tarjeta en la app?",
    "Quiero vender mis baleadas en la plataforma, que tengo que hacer?",
    "Me llamo Marta, tengo un comedor en Marsella, el nombre es Comedor Marta",
    "El restaurante Ines tiene sopa de mondongo hoy?",
    "Me llego mal un pedido, quiero mi plata de vuelta",
    "Do you have an email I can write to?",
]


async def turno(texto: str):
    historial = await obtener_historial(TELEFONO)
    respuesta = await generar_respuesta(texto, historial, TELEFONO)
    await guardar_mensaje(TELEFONO, "user", texto)
    await guardar_mensaje(TELEFONO, "assistant", respuesta)
    print(f"Alma: {respuesta}\n")


async def main():
    await inicializar_db()
    await limpiar_historial(TELEFONO)

    if "--demo" in sys.argv:
        for p in PREGUNTAS_DEMO:
            print(f"Tu: {p}")
            await turno(p)
        print("Contactos guardados:", await listar_contactos())
        return

    print("Chat con Alma. 'limpiar' borra el historial, 'salir' termina.\n")
    while True:
        try:
            texto = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto.lower() == "salir":
            break
        if texto.lower() == "limpiar":
            await limpiar_historial(TELEFONO)
            print("Historial borrado.\n")
            continue
        await turno(texto)


if __name__ == "__main__":
    asyncio.run(main())
