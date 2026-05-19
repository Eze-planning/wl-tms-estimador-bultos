# Mejoras a implementar — wl-tms-estimador-bultos
> Revisión previa al go-live · Mayo 2026

La auditoría de secretos, credenciales y variables de entorno la hace Tech en el proceso de go-live. Lo que está acá son los cambios que hay que resolver antes de mandar el formulario de revisión formal.

---

## Bloqueantes

### 1. Agregar autenticación a los endpoints

Hoy `/estimar` y `/estimar/excel` son accesibles para cualquiera que tenga la URL de Cloud Run. Como es Tier 3, necesita algún control de acceso.

**Opción simple:** validar un header `X-API-Key` contra una variable de entorno en un middleware de FastAPI.  
**Opción recomendada:** configurar IAP (Identity-Aware Proxy) en GCP — protege a nivel de infraestructura sin tocar el código Python.

Coordinar con Tech cuál aplica según el contexto de deploy.

---

### 2. Restringir CORS

```python
# Actual — cambiar esto:
allow_origins=["*"]

# Por esto:
allow_origins=["https://tu-dominio-interno.com"]  # el origen real donde vive el frontend
```

---

### 3. Agregar `rapidfuzz` a `requirements.txt`

Se usa en `modelo.py` pero no está declarado como dependencia. Un fresh install falla en runtime.

```
rapidfuzz
```

---

### 4. URL del backend no puede ser `localhost` en producción

```javascript
// Actual en index.html — esto no funciona en Cloud Run:
const API_URL = "http://localhost:8080";
```

Necesita ser la URL real del servicio desplegado. La forma más simple: leerla de un bloque de configuración al inicio del HTML que se reemplaza en el proceso de deploy, o exponer un endpoint `/config` desde el backend que el frontend consulta al cargar.

---

## Mejoras de calidad

### 5. Tipar el `except` en `procesar_pedido`

```python
# Actual (modelo.py línea ~264):
except:
    unidades = 0

# Correcto:
except (ValueError, TypeError):
    unidades = 0
```

Sin esto, cualquier error inesperado en esa línea se traga silenciosamente y el usuario recibe un 0 sin saber por qué.

---

### 6. Externalizar la fecha de inicio del histórico

```python
# Actual en modelo.py — hardcodeado en dos queries:
AND le.fecha_inicio >= '2025-01-01'

# Cambiar a:
FECHA_HISTORICO_DESDE = os.getenv("FECHA_HISTORICO_DESDE", "2025-01-01")
```

---

### 7. Invertir el orden del upsert en el scraper

El flujo actual es DELETE → INSERT. Si el proceso falla entre los dos pasos, los datos quedan eliminados y no reinsertados.

Cambiar a INSERT → DELETE (eliminar duplicados más viejos por `insertado_en` después de confirmar que el insert fue exitoso). Así ante cualquier falla siempre hay datos disponibles, aunque haya duplicados temporales.

---

## Backlog (no urgente)

| # | Qué | Por qué importa |
|---|-----|-----------------|
| 8 | Agregar tests a la lógica de estimación | Sin cobertura, cualquier cambio en `modelo.py` puede romper el cálculo sin que nadie se entere hasta que un usuario lo detecte. |
| 9 | Mover `debug_sku.py` a `.gitignore` o eliminarlo | Archivos de debug no deberían estar en el repo de producción. |
| 10 | Evaluar ventana temporal móvil para el modelo | Hoy el ratio se calcula sobre todo el histórico desde enero 2025. Podría tener sentido usar los últimos N meses para que el modelo capture cambios estacionales. |
| 11 | Paginación defensiva en queries BQ | Si el dataset crece mucho, las queries sin `LIMIT` pueden agotar memoria. |
