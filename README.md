# Notification API

**Una API pequeña para demostrar integración empresarial y entrega asíncrona de notificaciones.**

Python · FastAPI · PostgreSQL · Telegram · Docker · GitHub Actions

[![CI](https://github.com/arregui26/notification-api/actions/workflows/ci.yml/badge.svg)](https://github.com/arregui26/notification-api/actions/workflows/ci.yml)

API protegida por clave, cola persistente, idempotencia, reintentos y un worker independiente.
El modo de demostración funciona sin bot ni cuenta de Telegram y **no envía mensajes reales**.

*A compact portfolio project demonstrating a durable notification queue, request idempotency,
Telegram integration, controlled retries and PostgreSQL worker concurrency.*

## El problema que resuelve

Un sistema de inventario, RR. HH. o reportes necesita notificar un evento sin esperar al proveedor.
Si repite la petición por un error de red, no debería crear dos trabajos. Si Telegram falla,
el trabajo debe permanecer en la base y volver a intentarse de forma controlada.

Este proyecto implementa ese recorrido con un alcance concreto: un canal, una API y una cola.
Es un desarrollo independiente de portafolio; no contiene código ni datos de empleadores.

## Arquitectura

```mermaid
flowchart LR
    C[Aplicación cliente] -->|Clave + Idempotency-Key| A[FastAPI]
    A -->|Guardar trabajo| D[(PostgreSQL)]
    W[Worker] -->|Bloqueo de fila / SKIP LOCKED| D
    W --> P{Modo de entrega}
    P --> M[Simulación local]
    P --> T[Telegram Bot API]
    C -->|Consultar estado| A
```

## Ejecutar en pocos pasos

Requisitos: Git, Docker y Docker Compose. Los comandos siguientes usan Bash/WSL.

```bash
git clone https://github.com/arregui26/notification-api.git
cd notification-api
cp .env.example .env
docker compose up --build -d
docker compose ps
```

- Documentación interactiva: **http://localhost:8009/docs**
- OpenAPI: **http://localhost:8009/openapi.json**
- Estado del proceso: **http://localhost:8009/health/live**

Los valores incluidos en `.env.example` son exclusivamente de demostración local.
En Swagger, pulsa **Authorize** e introduce la clave de tu `.env`.
La API y PostgreSQL publican puertos únicamente en la interfaz local.

### Crear una notificación

```bash
export API_KEY=demo-only-change-this-key-before-use-0001
curl -sS http://localhost:8009/v1/notifications \
  -H "X-API-Key: $API_KEY" \
  -H "Idempotency-Key: inventory-report-001" \
  -H "Content-Type: application/json" \
  -d '{"recipient":"demo","text":"El reporte de inventario está listo."}'
```

Devuelve `202 Accepted` y un identificador. El worker procesa el trabajo en segundo plano.
En modo `mock`, `sent` significa simulación completada y el ID del proveedor empieza por `mock-`.

```bash
curl -sS http://localhost:8009/v1/notifications/REEMPLAZA_CON_EL_ID \
  -H "X-API-Key: $API_KEY"
```

Repetir la petición inicial con la misma clave y contenido devuelve `200` y el mismo ID.
Usar esa clave con otro contenido devuelve `409 Conflict`.

## Contrato y estados

| Endpoint | Acceso | Función |
|---|---|---|
| `GET /health/live` | Público | Comprobar que el proceso responde |
| `GET /health/ready` | Clave API | Comprobar conexión y tabla migrada |
| `POST /v1/notifications` | Clave API + Idempotency-Key | Encolar un mensaje |
| `GET /v1/notifications/{id}` | Clave API | Consultar estado sin exponer el texto |

```text
pending -> sent
pending -> retry -> sent
pending / retry -> failed
```

- Mensajes de 1 a 4096 caracteres; mensajes vacíos o solo espacios se rechazan.
- Destinatarios mediante alias configurados: el cliente no elige un `chat_id` arbitrario.
- Errores de conexión, respuestas 5xx y límites 429 pueden reintentarse.
- Los errores 4xx, salvo 429, terminan el trabajo. Máximo de intentos configurable.
- Espera exponencial entre reintentos; se respeta `retry_after` de Telegram hasta una hora.
- API y worker usan migraciones explícitas, no creación automática de tablas al iniciar.

## Activar Telegram

1. Crea tu propio bot con BotFather y abre una conversación con él desde tu cuenta de prueba.
2. Obtén el identificador del chat autorizado y configura los valores en tu `.env` local:

```dotenv
DELIVERY_MODE=telegram
TELEGRAM_BOT_TOKEN=tu-token-local
TELEGRAM_DESTINATIONS={"personal":"tu-chat-id"}
```

3. Recrea API y worker: `docker compose up -d --force-recreate api worker`.
4. Crea una notificación usando `"recipient":"personal"` y una nueva clave de idempotencia.

**Activar este modo permite envíos reales.** Las pruebas usan transporte simulado y nunca
contactan Telegram. Los trabajos guardan el modo de entrega de su creación; no se convierten
silenciosamente de simulados a reales al cambiar la configuración.

## Garantías y límites, sin promesas de "exactly once"

La restricción única de PostgreSQL evita duplicar trabajos con la misma clave de idempotencia,
incluso con peticiones concurrentes. `FOR UPDATE SKIP LOCKED` evita que dos workers procesen
simultáneamente la misma fila. El bloqueo se mantiene durante una llamada de red con timeout.

**Telegram no ofrece idempotencia para `sendMessage`.** Si acepta el mensaje y se pierde la
respuesta, o el worker cae antes de confirmar la transacción, un reintento puede enviarlo otra vez.
La entrega es de tipo *al menos una vez*, limitada por el máximo de intentos; no garantiza lectura
del mensaje ni entrega final. `sent` significa que el proveedor aceptó la petición.

La clave de idempotencia tiene alcance global en esta instalación de un solo cliente.
Los registros se conservan hasta su eliminación administrativa: no reutilices claves antiguas
para eventos distintos. No hay multiusuario, panel web, adjuntos ni recuperación manual en v0.1.

## Desarrollo y pruebas

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
ruff check .
ruff format --check .
pytest -q
```

Las pruebas rápidas usan SQLite temporal. Las pruebas de concurrencia real necesitan una base
**desechable cuyo nombre termine en `_test`**, migrada previamente:

```bash
export API_KEY=test-only-not-a-real-secret-1234567890
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5409/notifications_test
export TEST_DATABASE_URL="$DATABASE_URL"
alembic upgrade head
alembic check
pytest -q
```

Las pruebas PostgreSQL limpian la tabla de notificaciones de esa base de pruebas.
GitHub Actions levanta PostgreSQL desechable, aplica las migraciones, comprueba el esquema,
ejecuta las pruebas y construye la imagen Docker.

## Operación

```bash
docker compose logs --tail=50 worker
docker compose stop                  # conserva datos
docker compose up -d                 # vuelve a iniciar
```

No uses `docker compose down -v` si necesitas conservar las notificaciones.
Para ejecutar sin contenedores: configura PostgreSQL, aplica `alembic upgrade head`, inicia
`uvicorn notification_api.api:create_app --factory --port 8009` y, en otra terminal,
`python -m notification_api.worker`.

## Seguridad y decisiones

- Clave API obligatoria, comparación constante y destinos permitidos en configuración.
- Token de Telegram y claves excluidos de Git y de la imagen Docker.
- Los registros operativos no incluyen texto, chat ID, clave API ni URL del bot.
- Texto plano: no se interpreta HTML/Markdown enviado por el cliente.
- Contenedores de aplicación sin root, sin capacidades adicionales y con sistema de archivos de solo lectura.
- La base contiene el texto en claro para entregarlo: usa datos ficticios en la demo. Una instalación
  real requiere política de retención, respaldo y controles de acceso adecuados.
- No se publica un servidor de Internet con este repositorio. Antes de exponerlo, configura TLS,
  límites de tráfico/tamaño en el proxy, credenciales propias y monitoreo. Swagger es público y no
  permite operar sin clave.

Más detalles: [decisiones de arquitectura](docs/architecture.md).

## Autor y licencia

**Carlos Arregui Torres** · [Perfil profesional](https://perfil.arregui26.chatgpt.site)
· [LinkedIn](https://linkedin.com/in/carlos-arregui-torres)

Licencia MIT. Consulta [LICENSE](LICENSE).
