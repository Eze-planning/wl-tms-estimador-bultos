"""
despachos.py
============
Consulta historial de despachos desde BigQuery y calcula el courier óptimo
usando los tarifarios de 99 Minutos y Shipper Logistic.
"""

import os
from google.cloud import bigquery
from tarifario_99min import calcular_costo_99min
from tarifario_shipper import calcular_tabla_shipper

BQ_PROJECT = os.getenv("BQ_PROJECT", "prj-wlcl-p-data-share")


def _cliente_bq():
    key_path = os.getenv("BQ_KEY_PATH")
    if key_path:
        return bigquery.Client.from_service_account_json(key_path)
    return bigquery.Client(project=BQ_PROJECT)


def normalizar_nom_cliente(nom: str) -> str:
    """
    Convierte el nom_cliente de BQ al formato que esperan los tarifarios.
    Ej: "Repo - Osorno" → "Tienda Osorno"
        "GT - Paris"    → "Paris"
        "Mayorista - X" → "Mayoristas"
    """
    nom = nom.strip()
    nom_low = nom.lower()
    if nom_low.startswith("repo - ") or nom_low.startswith("repo -"):
        parte = nom[nom.index("-") + 1:].strip()
        return "Tienda " + parte
    if nom_low.startswith("gt - ") or nom_low.startswith("gt -"):
        parte = nom[nom.index("-") + 1:].strip()
        return parte.split(" - ")[0].strip()   # "Paris - Muebles" → "Paris"
    if nom_low.startswith("mayorista"):
        return "Mayoristas"
    return nom


def _auto_courier(nom_cliente: str, bultos: int) -> dict:
    """
    Devuelve el courier más barato y sus costos comparativos.
    """
    nom = normalizar_nom_cliente(nom_cliente)
    c99    = calcular_costo_99min(bultos, nom)
    cship  = calcular_tabla_shipper(nom)

    total_99   = c99.get("costo_total")   if c99  and not c99.get("advertencia")  else None
    directo_xl = None
    ruta_xl    = None

    if cship and not cship.get("advertencia") and cship.get("directo"):
        d = cship["directo"]
        directo_xl = d.get("costo_XL")
        rutas = cship.get("rutas") or []
        if rutas:
            ruta_xl = min(r["por_tienda_XL"] for r in rutas if r.get("por_tienda_XL"))

    mejor_ship = min(x for x in [directo_xl, ruta_xl] if x is not None) if any(
        x is not None for x in [directo_xl, ruta_xl]) else None

    if total_99 is not None and mejor_ship is not None:
        sugerido = "99 Min" if total_99 <= mejor_ship else "Shipper"
        costo_sugerido = min(total_99, mejor_ship)
    elif total_99 is not None:
        sugerido, costo_sugerido = "99 Min", total_99
    elif mejor_ship is not None:
        sugerido, costo_sugerido = "Shipper", mejor_ship
    else:
        sugerido, costo_sugerido = None, None

    return {
        "courier_sugerido": sugerido,
        "costo_99min":      round(total_99)    if total_99    else None,
        "costo_shipper_xl": round(mejor_ship)  if mejor_ship  else None,
        "costo_sugerido":   round(costo_sugerido) if costo_sugerido else None,
    }


def obtener_despachos(desde: str, hasta: str) -> list:
    """
    Devuelve lista de despachos entre desde y hasta (formato YYYY-MM-DD).
    Incluye bultos reales (log_embalaje PIKs), costos comparativos y courier sugerido.
    """
    client = _cliente_bq()

    query = f"""
    SELECT
        ds.orden_salida,
        ds.nom_cliente,
        ds.tipo,
        ds.estado,
        ds.transporte,
        ds.horario,
        SAFE_CAST(SUBSTR(CAST(ds.fechadespacho   AS STRING), 1, 10) AS DATE) AS fecha_despacho,
        SAFE_CAST(SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10) AS DATE) AS fecha_compromiso,
        COUNT(DISTINCT le.caja_origen) AS bultos_reales
    FROM `{BQ_PROJECT}.sandbox.documento_salida` ds
    LEFT JOIN `{BQ_PROJECT}.sandbox.log_embalaje` le
        ON le.nro_orden_salida = ds.orden_salida
        AND le.caja_origen IS NOT NULL
    WHERE ds.fechacompromiso IS NOT NULL
    AND SUBSTR(CAST(ds.fechacompromiso AS STRING), 1, 10) BETWEEN '{desde}' AND '{hasta}'
    GROUP BY
        ds.orden_salida, ds.nom_cliente, ds.tipo, ds.estado,
        ds.transporte, ds.horario, ds.fechadespacho, ds.fechacompromiso
    ORDER BY ds.fechacompromiso DESC, ds.nom_cliente
    """

    despachos = []
    for row in client.query(query).result():
        bultos = row.bultos_reales or 0
        costos = _auto_courier(row.nom_cliente or "", bultos)

        despachos.append({
            "orden_salida":     row.orden_salida,
            "nom_cliente":      row.nom_cliente or "",
            "tipo":             row.tipo or "",
            "estado":           row.estado or "",
            "transporte_real":  row.transporte or "",
            "horario":          str(row.horario) if row.horario else "",
            "fecha_despacho":   str(row.fecha_despacho)   if row.fecha_despacho   else "",
            "fecha_compromiso": str(row.fecha_compromiso) if row.fecha_compromiso else "",
            "bultos_reales":    bultos,
            **costos,
        })

    return despachos
