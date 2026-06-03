# WildRoute — by Wild Lama
> Planning & Logistics · Mayo 2026

Sistema de gestión logística que combina estimación de bultos por IA, programación semanal de despachos y visualización de costos de transporte.

---

## Módulos principales

| Módulo | Descripción |
|--------|-------------|
| **Estimador** | Estima bultos para órdenes de tiendas propias y Paris (XDB / Stock) usando histórico real de BigQuery |
| **Despachos** | Historial de despachos con costos comparativos 99min vs. Shipper |
| **Programación** | Vista semanal de despachos con drag & drop, OCs por tienda y costos calculados |
| **Admin** | Gestión de usuarios, roles y diagnóstico de tablas BQ |

---

## Stack

| Componente | Tecnología |
|------------|------------|
| Backend | Python 3.11 · FastAPI · Uvicorn (puerto 8080) |
| Frontend | HTML/CSS/JS estático (sin frameworks) |
| Modelo | pandas · rapidfuzz · ratios históricos sobre BigQuery |
| Auth | JWT (python-jose) · bcrypt (passlib — **fijar bcrypt<4.0**) |
| Infra | Cloud Run · BigQuery · Cloud Scheduler |

---

## Estructura del proyecto

```
estimador_bultos/
├── app.py               # Backend FastAPI — endpoints REST
├── modelo.py            # Modelo de estimación + cliente BQ
├── auth.py              # JWT, bcrypt, gestión de usuarios
├── bultos_reales.py     # Consulta bultos reales desde BQ (base_embalaje)
├── programacion.py      # Lógica de schedule semanal (JSON)
├── despachos.py         # Historial de despachos desde BQ
├── tarifario_99min.py   # Cálculo de costos 99 Minutos
├── tarifario_shipper.py # Cálculo de costos Shipper Logistic
├── index.html           # Frontend completo (SPA vanilla JS)
├── requirements.txt
├── .env.example         # Variables de entorno requeridas
├── DEPLOY.md            # Guía de deploy para Tech
└── mejoras-estimador-bultos.md  # Checklist pre go-live
```

---

## Variables de entorno

Ver `.env.example` para el listado completo. Las críticas:

| Variable | Descripción | Requerida |
|----------|-------------|-----------|
| `BQ_PROJECT` | ID del proyecto GCP (`prj-wlcl-p-data-share`) | Sí |
| `BQ_KEY_PATH` | Path al JSON de la service account | Sí |
| `JWT_SECRET` | Clave para firmar tokens JWT (mínimo 32 chars) | Sí |
| `CRON_SECRET` | Secreto para el endpoint de Cloud Scheduler | Sí (prod) |
| `FECHA_HISTORICO_DESDE` | Inicio del histórico del modelo (default: `2025-01-01`) | No |

---

## Tablas BigQuery

**Proyecto:** `prj-wlcl-p-data-share` · **Dataset principal:** `sandbox`

| Tabla | Operación | Actualización |
|-------|-----------|---------------|
| `sandbox.log_embalaje` | Lectura | 3×/día (pipeline externo) |
| `sandbox.documento_salida` | Lectura | 3×/día (pipeline externo) |
| `sandbox.log_recepcion` | Lectura | 3×/día (pipeline externo) |
| `sandbox.base_embalaje` | Lectura + **Escritura** | 3×/día via Cloud Scheduler → `/cron/rebuild-base-embalaje` |
| `sandbox.stock_actual` | **Escritura** (WRITE_TRUNCATE) | 1×/día a las 03:00 CLT via GitHub Actions |
| `sandbox.comex_importaciones` | **Escritura** (carga manual) | Al actualizar el Excel fuente |
| `dims.product_dim` | Lectura | Sin cambios frecuentes |

### Permisos necesarios para la service account

- `roles/bigquery.dataViewer` sobre `sandbox` y `dims`
- `roles/bigquery.dataEditor` sobre `sandbox` (para reconstruir `base_embalaje`)
- `roles/bigquery.jobUser` sobre el proyecto

### ¿Qué es base_embalaje?

Es un JOIN pre-computado de `documento_salida` + `log_embalaje` que el TMS usa para mostrar bultos reales en la vista de programación. Se reconstruye con:

```sql
SELECT ds.nom_cliente, ds.fechacompromiso, le.caja_origen,
       le.item, le.q_revisada, ds.nroordencliente, ds.nro_referencia
FROM sandbox.documento_salida ds
JOIN sandbox.log_embalaje le ON le.nro_orden_salida = ds.orden_salida
WHERE le.caja_origen IS NOT NULL AND ds.fechacompromiso IS NOT NULL
```

Ver `bultos_reales.py → reconstruir_base_embalaje()`.

---

## Sistema de autenticación

Implementado en `auth.py`. JWT con expiración de 7 días.

### Roles

| Rol | Estimador | Despachos | Programación | Admin | Editar | Ver costos |
|-----|-----------|-----------|--------------|-------|--------|------------|
| `admin` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `logistica` | ✓ | ✓ | ✓ | — | ✓ | ✓ |
| `readonly` | ✓ | ✓ | ✓ | — | — | ✓ |
| `bodega` | ✓ | — | — | — | — | — |
| `transportes` | — | ✓ | ✓ | — | — | ✓ |

### Usuario inicial

Al iniciar la app por primera vez se crea automáticamente:
- **Usuario:** `admin` · **Contraseña:** `admin123`
- **Cambiar la contraseña inmediatamente en producción.**

Los usuarios se almacenan en `users.json` (local). En Cloud Run, este archivo debe persistirse en un volumen o migrar a Firestore/Secret Manager.

---

## GitHub Actions — stock_actual diario

El workflow `.github/workflows/stock_actual_diario.yml` corre todos los días a las **03:00 CLT (07:00 UTC)** y reemplaza la tabla `sandbox.stock_actual` con el snapshot vigente de Valgreti → Stock por Item.

### Secrets requeridos en el repo

Ir a `Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Valor |
|--------|-------|
| `VALGRETI_USER` | Usuario de Valgreti |
| `VALGRETI_PASS` | Contraseña de Valgreti |
| `BQ_PROJECT` | `prj-wlcl-p-data-share` |
| `BQ_KEY_JSON` | Contenido completo del archivo `bq_service_account.json` |

### Trigger manual

Desde **Actions → Stock Actual Diario → Run workflow** para ejecutar fuera de horario.

### Lógica del scraper

```
valgreti_scraper/valgreti_scraper.py --mode stock-actual --headless
```

Navega a `ConsultaStockItem.aspx`, hace clic en Buscar sin filtros, descarga el Excel y lo carga a BQ con `WRITE_TRUNCATE`.

---

## Cloud Scheduler — Actualización de base_embalaje

El endpoint `POST /cron/rebuild-base-embalaje` se llama 3 veces al día para mantener `base_embalaje` sincronizada con las tablas fuente.

Ver instrucciones completas de configuración en `DEPLOY.md`.

**Horarios sugeridos** (UTC, equivale a 07:30 / 12:30 / 18:00 hora Chile en verano):
- `30 10 * * *`
- `30 15 * * *`
- `0 21 * * *`

---

## Correr localmente

```bash
pip install -r requirements.txt
cp .env.example .env
# Editar .env con los valores reales
uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

Abrir `index.html` en el browser (o servir con `python -m http.server`).

> **Nota bcrypt:** mantener `bcrypt<4.0`. La versión 4.x rompe passlib 1.7.4.
> Si aparece `AttributeError: module 'bcrypt' has no attribute '__about__'`, correr:
> `pip install "bcrypt<4.0"`

---

## Changelog (rama actual)

### Junio 2026

#### Estimador — modo múltiples tiendas
- Nuevo tipo **"Múltiples tiendas"** en el estimador: sube N archivos (uno por tienda, mismo formato que tienda propia) y obtiene bultos + desglose por línea para cada una
- Soporte de **carga multi-archivo**: cada click en "+ Agregar archivo" abre un selector independiente, permitiendo seleccionar archivos desde distintas carpetas
- Endpoint `POST /estimar/multi-archivos` en el backend (`app.py`)
- Función `estimar_multi_tienda()` en `modelo.py` — agrupa por `"Punto de venta"` y corre el modelo por tienda
- **Guardado por tienda**: selector de semana compartido en el encabezado; cada fila tiene un botón **Guardar** que guarda directo y se pone verde (✓) al confirmar. Botón secundario **→ Prog manual** para ajustes finos antes de guardar

#### Bultos reales — match por fecha de compromiso
- Cuando una tienda tiene **dos casillas en la misma semana**, los bultos reales ya no se asignan al total semanal en ambas — se matchean por `fechacompromiso` contra la fecha exacta de `dia_salida` de cada casilla
- Las queries BQ ahora incluyen `fecha_compromiso` en el GROUP BY (`bultos_reales.py`)

#### Programación — fix persistencia de cambios
- Corregido bug crítico: `guardarOverride` y `eliminarOverride` llamaban `cargarSemana(_editCtx.lunesISO)` en lugar de `cargarSemana(progLunesISO)`. En vista **envío repo** esto desplazaba el display una semana hacia adelante después de cada guardado, haciendo parecer que los cambios se habían perdido
- Agregados checks `response.ok` en todos los fetch de escritura — los errores del servidor ahora se muestran como alert en lugar de fallar silenciosamente

#### Programación — mejoras de calendario
- Vistas **salida** y **entrega**: siempre Lun–Vie
- Vista **envío repo**: muestra la semana siguiente (los envíos de esta semana preparan las salidas de la próxima)
- Fechas cruzadas entre semanas calculadas correctamente (ej. Antofagasta: carga jueves S21 → salida lunes S22)
- Número de semana (`S21`, `S22`) visible en las tarjetas como dato secundario
- Nuevos campos editables **Día Carga Repo** y **Hora Carga Repo** en los modales, sincronizados automáticamente con `dia_salida`
- Fecha exacta visible dentro de cada tarjeta (junto a la hora)

#### Tablas BigQuery — nuevas
- `sandbox.stock_actual`: snapshot diario del stock por item desde Valgreti (GitHub Actions, 03:00 CLT)
- `sandbox.comex_importaciones`: 4.574 filas desde `BBDD Comex - Looker.xlsx` (carga manual)

#### Scraper Valgreti
- Nuevo modo `--mode stock-actual`: descarga Stock por Item sin filtros y reemplaza `sandbox.stock_actual`
- Workflow `.github/workflows/stock_actual_diario.yml` para ejecución automática diaria
- Credenciales via GitHub Secrets (nunca en el repo)

#### Auto-commit users.json a GitHub
- Al crear/editar/eliminar usuarios, `auth.py` commitea `users.json` al repo via GitHub Contents API
- Variables `GITHUB_TOKEN`, `GITHUB_REPO`, `GITHUB_BRANCH` en `.env`

---

### Autenticación y roles
- `auth.py` nuevo: JWT + bcrypt, 5 roles, CRUD de usuarios, usuario admin inicial
- Fetch interceptor global en el frontend que inyecta `Authorization: Bearer` en todas las llamadas a la API
- Panel de administración de usuarios (tab Admin)
- CSS `body.no-edit` y `body.no-costos` para ocultar elementos según rol

### Programación semanal — mejoras
- **Órdenes de Compra por tarjeta**: Paris, Ripley y Falabella muestran OCs con bultos estimados/reales y hora de cita por OC
- **Hora de cita**: visible en la tarjeta cuando la propiedad OC está activa; se calcula como la más temprana entre las OCs
- **Costo con bultos reales**: cuando hay `bultos_reales`, el costo 99min se calcula con ese valor en lugar del estimado
- **Override de costo manual**: campo en el modal de edición para ingresar un costo diferente al calculado; se indica con `✎` en la tarjeta
- **Drag & drop entre columnas**: arrastrar una tarjeta a otro día actualiza `dia_salida`
- **Filtro por canal**: selector para mostrar solo un canal logístico
- **Propiedades ocultables**: selector de qué campos mostrar en las tarjetas (OC, costo, ruta, etc.)

### Integración estimador Paris → Programación
- Al guardar desde el estimador de Paris, detecta si la OC ya existe en la tarjeta y actualiza `bultos_estimados`; si no existe, la agrega automáticamente

### Bultos reales desde BigQuery
- `bultos_reales.py` nuevo: consulta `base_embalaje` (o fallback a `documento_salida + log_embalaje`) por semana
- Se inyectan automáticamente en el schedule al cargar cada semana
- Para GT: se mapean a la OC correspondiente dentro de `ordenes_compra`
- Para otras tiendas: se asignan directamente a `bultos_reales` de la entry
- `MAPEO_CLIENTES` en `bultos_reales.py` para traducir `nom_cliente` BQ → nombre de tienda

### Admin — diagnóstico BQ
- Sección "Mapeo clientes BQ": ver qué `nom_cliente` vienen de BQ y si tienen mapeo
- Sección "Estado tablas BQ": fecha_min/max y volumen de `base_embalaje` y `documento_salida`
- Botón "Reconstruir base_embalaje": dispara `CREATE OR REPLACE TABLE` desde las tablas fuente

### Cloud Scheduler
- Endpoint `POST /cron/rebuild-base-embalaje` para reconstrucción automática 3×/día
- Protegido con header `X-Cron-Secret` contra variable de entorno `CRON_SECRET`

### UX y control de acceso
- **Nombre de tienda más prominente** en las tarjetas (14px / 700 weight)
- **Hora sin día**: la tarjeta muestra solo la hora (ej. `09:00`) — el día es implícito por la columna del calendario
- **Roles read-only realmente sin interacción**: `bodega` y `transportes` ya tenían `edit: false`; ahora las tarjetas tampoco abren el modal al hacer click ni muestran cursor pointer
- **Panel de propiedades filtrado por rol**: la opción "Costo estimado" no aparece para roles sin permiso de costos (`bodega`)
- **Warning BQ solo para admin**: el aviso de clientes sin mapear solo se muestra al rol `admin`
- **Timeout de inactividad**: cierre de sesión automático tras 12 horas sin interacción; se detecta en cualquier click, tecla, scroll o touch; también se verifica al volver a la pestaña

---

## Autor
Ezequiel Ortiz — Planning & Logistics · Wild Lama
