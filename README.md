# NoteMeeting API

Transcripción de reunión → Claude extrae resumen, decisiones y tareas (ES/EN) → Slack.
Las tareas se guardan y el sistema manda recordatorios diarios al canal hasta que se marcan como hechas.

## Qué hace
- `POST /api/extract`: transcripción en texto (JSON).
- `POST /api/extract-file`: archivo de Zoom, Meet o Teams (`.vtt`, `.srt`, `.txt`, máx. 1 MB).
- Responde en el idioma de la reunión (español o inglés) y convierte "el viernes" en una fecha real.
- Cada tarea en Slack trae un link **Marcar como hecha** (`/t/<código>`: GET muestra la tarea, POST la cierra).
- Recordatorio diario (9:00 America/Chicago por defecto): tareas vencidas, que vencen hoy y mañana; los lunes también las que no tienen fecha.
- Planes: **Básico** (6 reuniones/mes) e **Ilimitado**. `GET /api/me` muestra el uso.
- No se guardan transcripciones: solo resumen, decisiones y tareas.

## Deploy en Render
1. Instance type: **Starter** (no se duerme; necesario para los recordatorios).
2. Crear una base **Postgres** en Render y copiar su *Internal Database URL* a `DATABASE_URL`.
3. Variables: ver `.env.example` (`PUBLIC_BASE_URL`, `ENABLE_SCHEDULER=1`, `REMINDER_TZ`, `REMINDER_HOUR`).
4. Dar de alta un cliente (Shell de Render):
   `python admin.py add "Nombre del cliente" https://hooks.slack.com/services/...` (Básico)
   `python admin.py add "Nombre del cliente" https://hooks.slack.com/services/... --unlimited` (Ilimitado)
   Cambiar de plan: `python admin.py set-limit <id> ilimitado` o `set-limit <id> 6`
   La API key se muestra una sola vez.

## Tests
`pip install -r requirements-dev.txt && pytest`
