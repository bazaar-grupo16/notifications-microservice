# Bazaar — Notifications Microservice

Microservicio de notificaciones para el ecosistema **Bazaar**. Recibe eventos
internos desde otros microservicios, los persiste en PostgreSQL como cola e
historial, los procesa con un worker liviano y expone endpoints para que la app
pueda consultar y marcar notificaciones como leídas.

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic, SQLAlchemy |
| Base de datos | PostgreSQL (configurable por env vars) |
| Contenedor | Docker (multi-stage, non-root) |
| Orquestación | Kubernetes (DigitalOcean) |
| CI/CD | GitHub Actions → GHCR → DOKS |

## Estructura del proyecto

```
├── src/
│   ├── api/
│   │   ├── controllers/    # Lógica de manejo de requests
│   │   ├── routers/        # Definición de rutas FastAPI
│   │   └── health.py       # /livez y /readyz
│   ├── core/           # Configuración, DB, logging
│   │   ├── config.py
│   │   ├── database.py  # Engine, sesión, base, y retry de conexión
│   │   ├── dependencies.py
│   │   ├── logging.py
│   │   └── utils.py    # Utilidades compartidas
│   ├── exceptions/     # Tipos de excepción de dominio
│   ├── models/         # Entidades SQLAlchemy
│   ├── repositories/   # Acceso a datos
│   ├── schemas/        # Modelos Pydantic
│   ├── services/       # Lógica de negocio
│   └── main.py         # Punto de entrada
├── tests/
│   ├── conftest.py
│   └── test_health.py
├── scripts/
│   ├── run_tests.sh    # Wrapper para correr tests (Linux/macOS)
│   └── run_tests.ps1   # Wrapper para correr tests (Windows)
├── k8s/
│   ├── app-deployment.yaml   # Deployment del microservicio
│   ├── app-service.yaml      # Service (ClusterIP) del microservicio
│   ├── db-deployment.yaml    # Deployment de PostgreSQL
│   ├── db-service.yaml       # Service (ClusterIP) de PostgreSQL
│   ├── db-pvc.yaml           # PersistentVolumeClaim para la BD
│   └── secret.yaml           # ⚠️ Template — NO commitear valores reales
├── .github/workflows/
│   ├── ci-dev.yml      # Pipeline CI para la rama dev (lint, SAST, test)
│   └── deploy.yml
├── Dockerfile              # Imagen de producción
├── Dockerfile.test         # Imagen para correr tests
├── docker-compose.test.yml # Levanta PostgreSQL + test runner
├── requirements.txt
└── .env.example
```

## Setup local

```bash
# 1. Clonar y entrar al directorio
git clone <REPO_URL> && cd template-microservice

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con las credenciales de tu base de datos local

# 5. Levantar la aplicación
uvicorn src.main:app --reload
```

## Conectarse al cluster de DigitalOcean

Requisitos:
- Tener instalado [doctl](https://docs.digitalocean.com/reference/doctl/)
- Tener instalado [kubectl](https://kubernetes.io/docs/tasks/tools/)

```bash
# 1. Iniciar sesión en doctl
doctl auth init --context <NAME>
doctl auth switch --context <NAME>

# 2. Obtener credenciales del cluster
doctl kubernetes cluster kubeconfig save <CLUSTER_ID>
```

## Endpoints disponibles

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/livez` | Liveness probe — siempre 200 |
| GET | `/readyz` | Readiness probe — verifica conexión a DB |
| GET | `/metrics` | Métricas Prometheus |
| POST | `/notifications` | Crea una notificación interna genérica e idempotente |
| POST | `/notifications/order-status-changed` | Crea notificación por cambio de estado de orden |
| POST | `/notifications/low-stock` | Crea notificación de stock bajo para vendedor |
| POST | `/notifications/out-of-stock` | Crea notificación de producto sin stock para vendedor |
| GET | `/notifications/me` | Lista notificaciones del usuario autenticado por `X-User-Id` |
| GET | `/notifications/me/unread-count` | Devuelve cantidad de notificaciones no leídas |
| PATCH | `/notifications/{notification_id}/read` | Marca una notificación propia como leída |
| PATCH | `/notifications/read-all` | Marca todas las notificaciones propias como leídas |
| GET | `/docs` | Swagger UI (auto-generado) |
| GET | `/redoc` | ReDoc (auto-generado) |

## Modelo de notificaciones

Cada notificación se guarda en la tabla `notifications` con:

- `idempotency_key`: evita duplicados ante reintentos.
- `notification_type`: `order_status_changed`, `low_stock` u `out_of_stock`.
- `recipient_id`: usuario comprador o vendedor que debe ver la notificación.
- `status`: estado interno del worker (`pending`, `sent`, `failed`).
- `read_at`: estado de presentación; `NULL` significa no leída.
- `payload`: datos de navegación como `deep_link`, `order_id` o `product_id`.

El worker procesa notificaciones `pending`, simula el envío y las marca como
`sent`. Si falla, reintenta hasta `NOTIFICATION_MAX_ATTEMPTS` y luego marca
`failed`. La lectura por parte del usuario no modifica `status`; solo setea
`read_at`.

### Contratos internos

`orders-service` llama a `/notifications/order-status-changed` cuando una orden
o item cambia de estado. `inventory-service` llama a `/notifications/low-stock`
o `/notifications/out-of-stock` cuando el stock cruza los umbrales configurados.

### Historial para la app

La app consulta `GET /notifications/me` usando el header `X-User-Id` inyectado
por el gateway/auth. Esto permite mostrar campanita, historial y contador de no
leídas aun sin push real.

En Kubernetes, estos endpoints se exponen mediante `k8s/ingress.yaml` como rutas
públicas autenticadas:

- `GET /notifications/me`
- `GET /notifications/me/unread-count`
- `PATCH /notifications/{notification_id}/read`
- `PATCH /notifications/read-all`

El Ingress valida el JWT contra `auth-service /validate` y reenvía `X-User-ID`
al pod. Desde la app se consume con `Authorization: Bearer <token>`:

```bash
curl -H "Authorization: Bearer <token>" \
  "http://bazaar.pib.ar/notifications/me?limit=20&offset=0"
```

Los endpoints `POST /notifications/*` no se exponen por Ingress. Siguen siendo
internos y se consumen únicamente dentro del cluster vía
`http://notifications-service`.

### Camino futuro con FCM

Firebase Cloud Messaging no reemplaza el historial. En una etapa posterior la
app podría registrar device tokens, `notifications-service` asociarlos al usuario
y el worker enviar push vía FCM. Al abrir el push, la app seguiría consultando
`GET /notifications/me` para mostrar el estado persistido.

## Tests

Los tests corren contra una **base de datos PostgreSQL real** usando Docker Compose. No se usa mocking.

El archivo `docker-compose.test.yml` levanta:
1. Un contenedor **PostgreSQL 16** como base de datos.
2. Un contenedor **test-runner** que ejecuta `pytest` contra esa base de datos.

### Correr los tests

```bash
# Linux / macOS
./scripts/run_tests.sh

# Windows (PowerShell)
.\scripts\run_tests.ps1

# O directamente con docker compose
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

> Los contenedores se limpian automáticamente al finalizar.

## Docker

```bash
docker build -t notifications-service .
docker run -p 8000:8000 --env-file .env notifications-service
```

## Kubernetes

Los manifiestos en `k8s/` despliegan el microservicio junto con su propia base de datos PostgreSQL dentro del cluster.

### Variables de entorno requeridas (GitHub Secrets)

| Secret | Descripción |
|--------|-------------|
| `DIGITALOCEAN_ACCESS_TOKEN` | Personal Access Token de DigitalOcean |
| `DB_USER` | Usuario de la base de datos |
| `DB_PASSWORD` | Contraseña de la base de datos |
| `DB_NAME` | Nombre de la base de datos |

`DB_HOST` y `DB_PORT` están fijos en `k8s/secret.yaml` (`notifications-db:5432`) ya que la BD corre dentro del cluster.
Si se utilizase una base de datos externa, se deberían agregar las variables de entorno correspondientes.

### Deploy manual

```bash
# Crear el namespace (solo la primera vez)
kubectl create namespace bazaar-dev

# Aplicar todos los manifiestos en orden
kubectl apply -f k8s/db-pvc.yaml       -n bazaar-dev
kubectl apply -f k8s/db-deployment.yaml -n bazaar-dev
kubectl apply -f k8s/db-service.yaml    -n bazaar-dev
kubectl apply -f k8s/secret.yaml        -n bazaar-dev
kubectl apply -f k8s/app-deployment.yaml -n bazaar-dev
kubectl apply -f k8s/app-service.yaml   -n bazaar-dev
kubectl apply -f k8s/ingress.yaml       -n bazaar-dev
```

### CI/CD automático

Hay dos pipelines de GitHub Actions:

**`ci-dev.yml`** — corre en cada push/PR a `dev`:

| Job | Descripción |
|-----|-------------|
| `lint` | Ruff sobre `src/` y `tests/` |
| `sast` | Bandit (análisis estático de seguridad) sobre `src/` |
| `test` | Tests contra PostgreSQL real vía Docker Compose |

**`deploy.yml`** — corre en cada push a `main`:

| Job | Se ejecuta cuando cambia... |
|-----|----------------------------|
| `lint` | `src/`, `tests/`, archivos de build |
| `test` | `src/`, `tests/`, archivos de build |
| `build` | `src/`, `tests/`, archivos de build (solo push a main) |
| `deploy` | `src/` **o** `k8s/` (solo push a main) |

## Conexión a la base de datos

Al iniciar, la aplicación espera a que la base de datos esté disponible usando **backoff exponencial** (1s → 2s → 4s → … hasta 30s por intento, máximo 5 minutos en total) antes de ejecutar las migraciones y aceptar tráfico. Esto evita crasheos durante el arranque del pod cuando la BD aún está inicializándose.

### Migraciones manuales existentes

Para bases ya desplegadas, aplicar los scripts incrementales cuando corresponda:

```bash
psql "$DATABASE_URL" -f scripts/add_correlation_id_column.sql
psql "$DATABASE_URL" -f scripts/add_read_at_column.sql
```

## Extender el template

Para agregar una nueva entidad al microservicio:

1. Crear el modelo SQLAlchemy en `src/models/`.
2. Crear los schemas Pydantic en `src/schemas/`.
3. Implementar el repositorio de acceso a datos en `src/repositories/`.
4. Definir las excepciones de dominio en `src/exceptions/`.
5. Implementar la lógica de negocio en `src/services/`.
6. Crear el controller en `src/api/controllers/` y el router en `src/api/routers/`; incluir el router en `src/main.py`.
7. Agregar tests en `tests/`.
