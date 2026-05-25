"""
bultos_reales.py
================
Consulta bultos reales por tienda/semana desde BigQuery.
Estrategia: intenta base_embalaje primero; si no tiene datos para la semana
solicitada, cae al join directo documento_salida + log_embalaje (siempre actualizado).
"""

import os
import json
import time
from datetime import date, timedelta
from pathlib import Path
from google.cloud import bigquery
from modelo import get_bq_client

BQ_PROJECT  = os.getenv("BQ_PROJECT", "prj-wlcl-p-data-share")
_MAPEO_PATH = Path(__file__).parent / "mapeo_clientes.json"


def _load_mapeo() -> dict:
    if _MAPEO_PATH.exists():
        with open(_MAPEO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


MAPEO_CLIENTES: dict[str, str] = _load_mapeo()


def guardar_mapeo_cliente(nom_cliente: str, tienda: str) -> None:
    """Persiste un nuevo par nom_cliente → tienda y recarga el mapeo en memoria."""
    MAPEO_CLIENTES[nom_cliente] = tienda
    with open(_MAPEO_PATH, "w", encoding="utf-8") as f:
        json.dump(MAPEO_CLIENTES, f, ensure_ascii=False, indent=2)
    invalidar_cache()

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 minutos


def _rango_semana(lunes_iso: str) -> tuple[str, str]:
    lunes   = date.fromisoformat(lunes_iso)
    viernes = (lunes + timedelta(days=6)).isoformat()
    return lunes_iso, viernes


def _procesar_filas(rows) -> dict:
    """Convierte filas BQ → {tienda: {total, ocs, por_fecha}, _sin_mapeo: [...]}"""
    resultado: dict = {}
    sin_mapeo: set  = set()
    for row in rows:
        nom    = (row.nom_cliente or "").strip().replace("\xa0", " ")
        tienda = MAPEO_CLIENTES.get(nom)
        if tienda is None:
            sin_mapeo.add(nom)
            tienda = nom
        oc     = str(row.oc or "").strip()
        bultos = int(row.bultos or 0)
        fecha  = str(getattr(row, "fecha_compromiso", None) or "")[:10]
        if tienda not in resultado:
            resultado[tienda] = {"total": 0, "ocs": {}, "por_fecha": {}}
        resultado[tienda]["total"] += bultos
        if oc:
            resultado[tienda]["ocs"][oc] = resultado[tienda]["ocs"].get(oc, 0) + bultos
        if fecha:
            pf = resultado[tienda]["por_fecha"]
            if fecha not in pf:
                pf[fecha] = {"total": 0, "ocs": {}}
            pf[fecha]["total"] += bultos
            if oc:
                pf[fecha]["ocs"][oc] = pf[fecha]["ocs"].get(oc, 0) + bultos
    resultado["_sin_mapeo"] = sorted(sin_mapeo)
    return resultado


def _query_base_embalaje(client, lunes_iso: str, viernes_iso: str) -> list:
    query = f"""
    SELECT
        nom_cliente,
        REGEXP_REPLACE(CAST(nroordencliente AS STRING), r'-[SP]$', '') AS oc,
        SUBSTR(CAST(fechacompromiso AS STRING), 1, 10) AS fecha_compromiso,
        COUNT(DISTINCT caja_origen) AS bultos
    FROM `{BQ_PROJECT}.sandbox.base_embalaje`
    WHERE caja_origen  IS NOT NULL
      AND nom_cliente  IS NOT NULL
      AND SUBSTR(CAST(fechacompromiso AS STRING), 1, 10) BETWEEN @lunes AND @viernes
    GROUP BY nom_cliente, oc, fecha_compromiso
    ORDER BY nom_cliente, fecha_compromiso, oc
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("lunes",   "STRING", lunes_iso),
        bigquery.ScalarQueryParameter("viernes", "STRING", viernes_iso),
    ])
    return list(client.query(query, job_config=cfg).result())


def _query_fuente_directa(client, lunes_iso: str, viernes_iso: str) -> list:
    """
    Join directo documento_salida + log_embalaje.
    Siempre refleja el estado más reciente de las tablas fuente.
    """
    query = f"""
    SELECT
        ds.nom_cliente,
        REGEXP_REPLACE(CAST(ds.nroordencliente AS STRING), r'-[SP]$', '') AS oc,
        SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10) AS fecha_compromiso,
        COUNT(DISTINCT le.caja_origen) AS bultos
    FROM `{BQ_PROJECT}.sandbox.documento_salida` ds
    LEFT JOIN `{BQ_PROJECT}.sandbox.log_embalaje` le
        ON le.nro_orden_salida = ds.orden_salida
       AND le.caja_origen IS NOT NULL
    WHERE ds.nom_cliente   IS NOT NULL
      AND ds.fechacompromiso IS NOT NULL
      AND SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10) BETWEEN @lunes AND @viernes
    GROUP BY ds.nom_cliente, oc, fecha_compromiso
    ORDER BY ds.nom_cliente, fecha_compromiso
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("lunes",   "STRING", lunes_iso),
        bigquery.ScalarQueryParameter("viernes", "STRING", viernes_iso),
    ])
    return list(client.query(query, job_config=cfg).result())


def consultar_bultos_reales(lunes_iso: str) -> dict:
    """
    Retorna {tienda: {total, ocs: {oc: n}}, _sin_mapeo: [...], _fuente: str}.
    Intenta base_embalaje primero; si está vacía para esa semana, usa el join directo.
    """
    now = time.time()
    if lunes_iso in _CACHE:
        ts, cached = _CACHE[lunes_iso]
        if now - ts < _CACHE_TTL:
            return cached

    lunes_iso, viernes_iso = _rango_semana(lunes_iso)
    client = get_bq_client()

    # Intentar base_embalaje
    filas  = _query_base_embalaje(client, lunes_iso, viernes_iso)
    fuente = "base_embalaje"

    # Fallback a tablas fuente si base_embalaje no tiene datos para la semana
    if not filas:
        filas  = _query_fuente_directa(client, lunes_iso, viernes_iso)
        fuente = "documento_salida+log_embalaje"

    resultado          = _procesar_filas(filas)
    resultado["_fuente"] = fuente

    _CACHE[lunes_iso] = (now, resultado)
    return resultado


def reconstruir_base_embalaje() -> dict:
    """
    Reconstruye base_embalaje completa desde documento_salida + log_embalaje.
    Usa WRITE_TRUNCATE (reemplaza toda la tabla). Puede tardar 1-2 min.
    Requiere que la cuenta de servicio tenga BigQuery Data Editor en sandbox.
    """
    client = get_bq_client()
    query  = f"""
    SELECT
        ds.nom_cliente,
        ds.fechacompromiso,
        le.caja_origen,
        le.item,
        le.q_revisada,
        ds.nroordencliente,
        ds.nro_referencia
    FROM `{BQ_PROJECT}.sandbox.documento_salida` ds
    JOIN `{BQ_PROJECT}.sandbox.log_embalaje` le
        ON le.nro_orden_salida = ds.orden_salida
    WHERE le.caja_origen      IS NOT NULL
      AND ds.fechacompromiso  IS NOT NULL
      AND ds.nom_cliente      IS NOT NULL
    """
    dest = bigquery.TableReference.from_string(f"{BQ_PROJECT}.sandbox.base_embalaje")
    cfg  = bigquery.QueryJobConfig(
        destination                = dest,
        write_disposition          = bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_large_results        = True,
        use_legacy_sql             = False,
    )
    job = client.query(query, job_config=cfg)
    job.result()  # espera a que termine
    return {"filas_escritas": job.num_dml_affected_rows, "job_id": job.job_id}


def estado_tablas() -> dict:
    """Retorna fecha_min, fecha_max y total_registros de las tablas fuente."""
    client = get_bq_client()
    resultado = {}

    # Tablas con columna fechacompromiso propia
    tablas_directas = {
        "base_embalaje":   f"`{BQ_PROJECT}.sandbox.base_embalaje`",
        "documento_salida": f"`{BQ_PROJECT}.sandbox.documento_salida`",
    }
    for nombre, tabla in tablas_directas.items():
        try:
            q = f"""
            SELECT
                MIN(SUBSTR(CAST(fechacompromiso AS STRING), 1, 10)) AS fecha_min,
                MAX(SUBSTR(CAST(fechacompromiso AS STRING), 1, 10)) AS fecha_max,
                COUNT(*) AS total
            FROM {tabla}
            WHERE fechacompromiso IS NOT NULL
            """
            row = list(client.query(q).result())[0]
            resultado[nombre] = {
                "fecha_min": row.fecha_min,
                "fecha_max": row.fecha_max,
                "total":     row.total,
            }
        except Exception as e:
            resultado[nombre] = {"error": str(e)}

    # log_embalaje: fecha via JOIN con documento_salida (no tiene fechacompromiso propia)
    try:
        q = f"""
        SELECT
            MIN(SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10)) AS fecha_min,
            MAX(SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10)) AS fecha_max,
            COUNT(*) AS total
        FROM `{BQ_PROJECT}.sandbox.log_embalaje` le
        JOIN `{BQ_PROJECT}.sandbox.documento_salida` ds
            ON ds.orden_salida = le.nro_orden_salida
        WHERE le.caja_origen IS NOT NULL
          AND ds.fechacompromiso IS NOT NULL
        """
        row = list(client.query(q).result())[0]
        resultado["log_embalaje"] = {
            "fecha_min": row.fecha_min,
            "fecha_max": row.fecha_max,
            "total":     row.total,
        }
    except Exception as e:
        resultado["log_embalaje"] = {"error": str(e)}

    return resultado


def invalidar_cache(lunes_iso: str | None = None) -> None:
    if lunes_iso:
        _CACHE.pop(lunes_iso, None)
    else:
        _CACHE.clear()
