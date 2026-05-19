# Guía de deploy — Wild Lama TMS
> Para el equipo de Tech · Mayo 2026

---

## Qué hace esta app

API REST (FastAPI) + frontend estático (HTML/JS) para gestión logística:
estimación de bultos por IA, programación semanal de despachos, costos de transporte y autenticación con roles.

**Tier 3 — crítica** (conecta a GCP/BigQuery con credenciales de servicio).

---

## Stack

| Componente | Tecnología |
|---|---|
| Backend | Python 3.11 · FastAPI · Uvicorn (puerto 8080) |
| Frontend | HTML/JS estático — servido desde el mismo contenedor |
| Auth | JWT (python-jose 3.5.0) · bcrypt (passlib 1.7.4 + **bcrypt 3.2.2**) |
| Modelo | pandas · rapidfuzz · ratios históricos desde BigQuery |
| Infra destino | Cloud Run (backend + frontend) |

> **CRÍTICO — versión bcrypt:** `passlib 1.7.4` es incompatible con `bcrypt>=4.0`.
> El `requirements.txt` pina `bcrypt==3.2.2`. No actualizar.

---

## Variables de entorno requeridas

| Variable | Descripción | Ejemplo |
|---|---|---|
| `BQ_PROJECT` | ID del proyecto GCP | `prj-wlcl-p-data-share` |
| `BQ_KEY_PATH` | Path al JSON de la service account | `/secrets/bq_key.json` |
| `JWT_SECRET` | Clave secreta para firmar JWT (≥32 chars) | *(generar con `secrets.token_hex(32)`)* |
| `CRON_SECRET` | Secreto para el endpoint de Cloud Scheduler | *(generar con `secrets.token_hex(32)`)* |
| `FECHA_HISTORICO_DESDE` | Inicio del histórico del modelo | `2025-01-01` *(default)* |

Generar secretos:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Almacenar `BQ_KEY_PATH`, `JWT_SECRET` y `CRON_SECRET` en **Secret Manager**, no como variables de texto plano.

---

## Permisos service account

La service account necesita los siguientes roles IAM en `prj-wlcl-p-data-share`:

| Rol | Para qué |
|---|---|
| `roles/bigquery.dataViewer` en `sandbox` y `dims` | Leer todas las tablas fuente |
| `roles/bigquery.dataEditor` en `sandbox` | Reconstruir `base_embalaje` |
| `roles/bigquery.jobUser` sobre el proyecto | Ejecutar jobs de query |

---

## Pasos para el deploy en Cloud Run

### 1. Build y push de imagen

```bash
docker build -t wl-tms-estimador .
docker tag wl-tms-estimador gcr.io/prj-wlcl-p-data-share/wl-tms-estimador
docker push gcr.io/prj-wlcl-p-data-share/wl-tms-estimador
```

*(Dockerfile pendiente — punto de entrada: `uvicorn app:app --host 0.0.0.0 --port 8080`)*

### 2. Deploy en Cloud Run

```bash
gcloud run deploy wl-tms-estimador \
  --image gcr.io/prj-wlcl-p-data-share/wl-tms-estimador \
  --region us-central1 \
  --platform managed \
  --no-allow-unauthenticated \
  --set-env-vars BQ_PROJECT=prj-wlcl-p-data-share,FECHA_HISTORICO_DESDE=2025-01-01 \
  --set-secrets BQ_KEY_PATH=bq-service-account-key:latest \
  --set-secrets JWT_SECRET=tms-jwt-secret:latest \
  --set-secrets CRON_SECRET=tms-cron-secret:latest
```

### 3. Actualizar API_URL en el frontend

Una vez obtenida la URL de Cloud Run, reemplazar en `index.html`:
```javascript
const API_URL = "https://<url-cloud-run>.run.app";
```

### 4. Persistencia de users.json

Los usuarios del TMS se guardan en `users.json`. En Cloud Run las escrituras al filesystem son efímeras. Opciones:
- **Opción A (rápida):** montar un volumen Cloud Storage FUSE sobre el directorio de la app
- **Opción B (robusta):** migrar `auth.py` para usar Firestore en lugar de JSON

---

## Cloud Scheduler — Actualización de base_embalaje

`base_embalaje` es un JOIN pre-computado de `documento_salida + log_embalaje`.
Debe reconstruirse cada vez que esas tablas se actualizan (3 veces al día).

### Por qué es necesario

Las tablas `documento_salida`, `log_embalaje` y `log_recepcion` se actualizan 3×/día via pipeline externo. `base_embalaje` es una materialización de ese JOIN que el TMS usa para mostrar bultos reales en la programación semanal. Sin esta actualización, los bultos reales quedan desactualizados.

### Endpoint

```
POST https://<url-cloud-run>.run.app/cron/rebuild-base-embalaje
Header: X-Cron-Secret: <valor de CRON_SECRET>
```

El endpoint ejecuta `CREATE OR REPLACE TABLE sandbox.base_embalaje AS SELECT ...` desde las tablas fuente. Tarda ~1-2 minutos.

### Crear los jobs en Cloud Scheduler

Crear **3 jobs** con los siguientes schedules (UTC — equivalen a 07:30, 12:30 y 18:00 hora Chile en horario de verano UTC-3):

```bash
# Job 1 — 07:30 CL
gcloud scheduler jobs create http tms-rebuild-base-embalaje-1 \
  --location us-central1 \
  --schedule "30 10 * * *" \
  --uri "https://<url-cloud-run>.run.app/cron/rebuild-base-embalaje" \
  --http-method POST \
  --headers "X-Cron-Secret=<CRON_SECRET>" \
  --time-zone "America/Santiago"

# Job 2 — 12:30 CL
gcloud scheduler jobs create http tms-rebuild-base-embalaje-2 \
  --location us-central1 \
  --schedule "30 15 * * *" \
  --uri "https://<url-cloud-run>.run.app/cron/rebuild-base-embalaje" \
  --http-method POST \
  --headers "X-Cron-Secret=<CRON_SECRET>" \
  --time-zone "America/Santiago"

# Job 3 — 18:00 CL
gcloud scheduler jobs create http tms-rebuild-base-embalaje-3 \
  --location us-central1 \
  --schedule "0 21 * * *" \
  --uri "https://<url-cloud-run>.run.app/cron/rebuild-base-embalaje" \
  --http-method POST \
  --headers "X-Cron-Secret=<CRON_SECRET>" \
  --time-zone "America/Santiago"
```

> Si el endpoint de Cloud Run requiere autenticación OIDC (IAP), agregar
> `--oidc-service-account-email <sa>@<project>.iam.gserviceaccount.com`
> y otorgar `roles/run.invoker` a esa SA.

### Ajustar horarios por DST

Chile usa UTC-3 en verano y UTC-4 en invierno. Los schedules de arriba son para UTC-3 (verano).
En invierno sumar 1 hora a los valores UTC: `30 11`, `30 16`, `0 22`.
O usar `--time-zone "America/Santiago"` directamente y dejar los horarios locales fijos.

---

## Checklist pre-deploy

### Bloqueantes

- [ ] **Cambiar contraseña del usuario `admin`** — la default es `admin123`
- [ ] Configurar `JWT_SECRET` (mínimo 32 chars, aleatorio) en Secret Manager
- [ ] Configurar `CRON_SECRET` en Secret Manager y en los jobs de Cloud Scheduler
- [ ] Restringir `allow_origins` en `app.py` al dominio real del frontend
- [ ] Reemplazar `API_URL = "http://localhost:8080"` en `index.html` con la URL de Cloud Run
- [ ] Verificar permisos `dataEditor` en `sandbox` para poder reconstruir `base_embalaje`
- [ ] Resolver persistencia de `users.json` (volumen GCS o migrar a Firestore)
- [ ] Crear los 3 jobs de Cloud Scheduler para `base_embalaje`

### Mejoras de calidad (no bloqueantes)

- [ ] Tipar el `except:` desnudo en `modelo.py` línea ~264 → `except (ValueError, TypeError):`
- [ ] Externalizar `'2025-01-01'` como variable de entorno `FECHA_HISTORICO_DESDE`
- [ ] Mover `debug_sku.py` a `.gitignore` o eliminarlo del repo
- [ ] Agregar paginación defensiva en queries BQ grandes (tabla `base_embalaje` ya tiene >1.2M filas)

---

## Mapeo MAPEO_CLIENTES

En `bultos_reales.py` hay un dict `MAPEO_CLIENTES` que traduce `nom_cliente` de BQ al nombre de tienda del schedule:

```python
MAPEO_CLIENTES: dict[str, str] = {
    # "PARIS S.A.": "Paris",
    # "RIPLEY CHILE S.A.": "Ripley",
    # ...
}
```

Para ver los valores reales: iniciar la app, ir a **Admin → Mapeo clientes BQ**, seleccionar una semana con datos y hacer clic en "Consultar". Los `nom_cliente` sin mapeo aparecen en naranja.

---

## Notas

- **Dockerfile:** no existe aún. Punto de entrada: `uvicorn app:app --host 0.0.0.0 --port 8080`.
- **Frontend:** `index.html` puede servirse desde el mismo contenedor con `StaticFiles` de FastAPI, o desde un bucket GCS con acceso interno.
- **Scraper Valgreti:** componente separado en `valgreti_scraper/`, con su propio deploy y schedule.
