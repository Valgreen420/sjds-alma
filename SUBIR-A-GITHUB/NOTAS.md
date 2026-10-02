# Alma · asistente de WhatsApp de San Juan Delivery · estado del proyecto

Última actualización: 2 de octubre de 2026.

## Decisiones de la entrevista (Fase 2)
1. **Negocio:** San Juan Delivery (SJDS Connect), operado por Palma Web Studio.
2. **Alcance:** Alma atiende las preguntas dirigidas al director de la plataforma. NO habla de menús, precios de platos ni horarios de un restaurante; manda a la app o al WhatsApp de ese negocio.
3. **Casos de uso:** (1) responder preguntas frecuentes de la plataforma y (3) tomar datos de quien quiere vender o ser motorizado (nombre, negocio o zona, WhatsApp) para dar seguimiento. NO atiende reclamos (van con el negocio o proveedor), NO toma pedidos de comida ni de mandados.
4. **Nombre del agente:** Alma. Se presenta como la asistente de San Juan Delivery.
5. **Tono:** amigable y casual. Responde en español o en inglés, según el idioma de quien escribe.
6. **Horario:** sin horario fijo. Nunca promete horas ni días: "te escribimos en cuanto podamos".
7. **Conocimiento:** `knowledge/plataforma.md` (zonas y tarifas, planes, mandados, cuentas y verificación, reclamos, privacidad, contacto).
8. **Anthropic:** clave creada y probada (modelo `claude-sonnet-5`). **Vence el 1 de noviembre de 2026**: renovarla antes. Va solo en `.env`.
9. **WhatsApp:** Zernio (plan gratis; número de pruebas compartido para empezar).

## Falta
- **Pregunta 10:** crear la cuenta de Zernio y guardar en `.env`: `WHATSAPP_PROVIDER=zernio`, `ZERNIO_API_KEY=` y `ZERNIO_WEBHOOK_SECRET=` (un texto largo inventado). Nunca pegar claves en el chat.
- **Fase 3:** generar `config/business.yaml`, `config/prompts.yaml`, `agent/` (main, brain, memory, tools, providers/zernio), `tests/test_local.py`, Dockerfile y docker-compose.
- **Fase 4:** probar en la terminal con `tests/test_local.py`.
- **Fase 5 (opcional):** desplegar en Railway y configurar el webhook de Zernio.

## Reglas
- Este proyecto es independiente de la app Next.js de San Juan Delivery.
- El `.env` nunca se sube a GitHub. Instalar, borrar y usar git solo con permiso del usuario.
