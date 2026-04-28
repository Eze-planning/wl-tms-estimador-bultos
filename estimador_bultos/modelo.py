"""
modelo.py v3.3 - Modelo hibrido con subclase
==============================================
Logica diferenciada por linea:
  - Vestuario (Hombre/Kids): ratio ponderado por subclase
  - Otras lineas (Accesorios, Travel, Vestuario Mujer, etc.): ratio por linea completa

Fallback para vestuario: Cliente+Subclase -> Cliente+Clase -> Subclase -> Clase -> Global
"""

import os
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv
from pathlib import Path
from rapidfuzz import process, fuzz

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# Líneas que usan ratio ponderado por subclase
LINEAS_POR_SUBCLASE = {"Vestuario Hombre", "Vestuario Kids"}


def get_bq_client():
    project  = os.getenv("BQ_PROJECT")
    key_path = os.getenv("BQ_KEY_PATH")
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=project, credentials=creds)


def cargar_ratios(client, tipo_cliente: str = "tienda_propia") -> dict:
    project = os.getenv("BQ_PROJECT")

    if tipo_cliente == "paris":
        filtro_cliente = "ds.nom_cliente = 'Paris'"
    else:
        filtro_cliente = "ds.cod_cliente NOT IN ('PAR','FAL','RIP','EDS','DIM','MELI','snaqui','SNAQUI','WL')"

    # Ratio por SUBCLASE (para líneas de vestuario hombre/kids)
    query_subclase = f"""
    WITH cajas AS (
        SELECT
            le.caja_origen,
            le.nro_orden_salida,
            ds.nom_cliente,
            pd.product_subclass_name AS subclase,
            pd.product_class_name    AS clase,
            pd.product_group_name    AS linea,
            SUM(le.q_revisada)       AS unidades_en_caja
        FROM `{project}.sandbox.log_embalaje` le
        JOIN `{project}.sandbox.documento_salida` ds
            ON le.nro_orden_salida = ds.orden_salida
        INNER JOIN `{project}.dims.product_dim` pd
            ON le.item = pd.product_sku_num
        WHERE {filtro_cliente}
        AND ds.estado = 'Despachada'
        AND le.fecha_inicio >= '2025-01-01'
        AND le.caja_origen IS NOT NULL
        AND le.item IS NOT NULL
        AND pd.product_class_name != 'Bandana'
        AND pd.product_group_name IN ('Vestuario Hombre', 'Vestuario Kids')
        GROUP BY le.caja_origen, le.nro_orden_salida,
                 ds.nom_cliente, pd.product_subclass_name,
                 pd.product_class_name, pd.product_group_name
        HAVING SUM(le.q_revisada) >= 5
    )
    SELECT nom_cliente, subclase, clase, linea,
           APPROX_QUANTILES(unidades_en_caja, 2)[OFFSET(1)] AS ratio,
           COUNT(*) AS n_obs
    FROM cajas
    WHERE unidades_en_caja > 0
    GROUP BY nom_cliente, subclase, clase, linea
    """

    # Ratio por LINEA COMPLETA (para otras líneas)
    query_linea = f"""
    WITH cajas AS (
        SELECT
            le.caja_origen,
            le.nro_orden_salida,
            ds.nom_cliente,
            pd.product_group_name AS linea,
            SUM(le.q_revisada)    AS unidades_en_caja
        FROM `{project}.sandbox.log_embalaje` le
        JOIN `{project}.sandbox.documento_salida` ds
            ON le.nro_orden_salida = ds.orden_salida
        INNER JOIN `{project}.dims.product_dim` pd
            ON le.item = pd.product_sku_num
        WHERE {filtro_cliente}
        AND ds.estado = 'Despachada'
        AND le.fecha_inicio >= '2025-01-01'
        AND le.caja_origen IS NOT NULL
        AND le.item IS NOT NULL
        AND pd.product_class_name != 'Bandana'
        AND pd.product_group_name NOT IN ('Vestuario Hombre', 'Vestuario Kids')
        GROUP BY le.caja_origen, le.nro_orden_salida,
                 ds.nom_cliente, pd.product_group_name
        HAVING SUM(le.q_revisada) >= 5
    )
    SELECT nom_cliente, linea,
           APPROX_QUANTILES(unidades_en_caja, 2)[OFFSET(1)] AS ratio,
           COUNT(*) AS n_obs
    FROM cajas
    WHERE unidades_en_caja > 0
    GROUP BY nom_cliente, linea
    """

    df_sub  = client.query(query_subclase).to_dataframe()
    df_lin  = client.query(query_linea).to_dataframe()

    # Normalizar \xa0 en nombres
    df_sub["nom_cliente"] = df_sub["nom_cliente"].str.replace("\xa0", " ")
    df_lin["nom_cliente"] = df_lin["nom_cliente"].str.replace("\xa0", " ")

    print(f"Ratios por subclase: {len(df_sub)} combinaciones")
    print(f"Ratios por linea:    {len(df_lin)} combinaciones")

    ratios = {}

    # Subclase
    ratios["cliente_subclase"] = df_sub.copy()
    ratios["subclase"] = (
        df_sub[df_sub["subclase"].notna()]
        .groupby("subclase")["ratio"].median()
        .reset_index()
    )
    ratios["clase"] = (
        df_sub[df_sub["clase"].notna()]
        .groupby("clase")["ratio"].median()
        .reset_index()
    )

    # Linea
    ratios["cliente_linea"] = df_lin.copy()
    ratios["linea"] = (
        df_lin.groupby("linea")["ratio"].median()
        .reset_index()
    )

    ratios["global"] = pd.concat([df_sub["ratio"], df_lin["ratio"]]).median()
    ratios["clientes_lista"] = (
        pd.concat([df_sub["nom_cliente"], df_lin["nom_cliente"]])
        .dropna().str.replace("\xa0", " ").unique().tolist()
    )

    print(f"Ratio global: {ratios['global']:.1f} und/caja")
    return ratios


def cargar_product_dim(client) -> pd.DataFrame:
    project = os.getenv("BQ_PROJECT")
    query = f"""
    SELECT
        CAST(product_sku_num AS STRING) AS sku,
        product_subclass_name           AS subclase,
        product_class_name              AS clase,
        product_group_name              AS linea
    FROM `{project}.dims.product_dim`
    """
    df = client.query(query).to_dataframe()
    print(f"product_dim cargado: {len(df)} SKUs")
    return df


def normalizar_cliente(cliente_raw: str, clientes_bq: list) -> str:
    cliente = cliente_raw.replace("Mall ", "").replace("\xa0", " ").strip()
    if cliente in clientes_bq:
        return cliente
    result = process.extractOne(cliente, clientes_bq, scorer=fuzz.WRatio, score_cutoff=80)
    if result:
        return result[0]
    return cliente


def obtener_ratio_subclase(cliente_norm, subclase, clase, ratios) -> float:
    cs = ratios["cliente_subclase"]

    # Nivel 1: cliente + subclase
    match = cs[(cs["nom_cliente"] == cliente_norm) & (cs["subclase"] == subclase)]
    if len(match) > 0:
        return match["ratio"].median()

    # Nivel 2: cliente + clase
    match = cs[(cs["nom_cliente"] == cliente_norm) & (cs["clase"] == clase)]
    if len(match) > 0:
        return match["ratio"].median()

    # Nivel 3: solo subclase
    match = ratios["subclase"][ratios["subclase"]["subclase"] == subclase]
    if len(match) > 0:
        return match["ratio"].values[0]

    # Nivel 4: solo clase
    match = ratios["clase"][ratios["clase"]["clase"] == clase]
    if len(match) > 0:
        return match["ratio"].values[0]

    return ratios["global"]


def obtener_ratio_linea(cliente_norm, linea, ratios) -> float:
    cl = ratios["cliente_linea"]
    match = cl[(cl["nom_cliente"] == cliente_norm) & (cl["linea"] == linea)]
    if len(match) > 0:
        return match["ratio"].median()
    match = ratios["linea"][ratios["linea"]["linea"] == linea]
    if len(match) > 0:
        return match["ratio"].values[0]
    return ratios["global"]


def calcular_bultos_linea(df_linea, product_dim, ratios, cliente_norm, linea) -> tuple:
    total_unidades = df_linea["unidades"].sum()

    if linea in LINEAS_POR_SUBCLASE:
        # Ratio ponderado por subclase
        ratio_pond = 0
        for _, row in df_linea.iterrows():
            sku = str(row["sku"]).strip()
            dim = product_dim[product_dim["sku"].astype(str).str.strip() == sku]
            subclase = dim["subclase"].values[0] if len(dim) > 0 else None
            clase    = dim["clase"].values[0]    if len(dim) > 0 else None
            ratio    = obtener_ratio_subclase(cliente_norm, subclase, clase, ratios)
            peso     = row["unidades"] / total_unidades if total_unidades > 0 else 0
            ratio_pond += peso * ratio
        nivel = "Ponderado por Subclase"
    else:
        ratio_pond = obtener_ratio_linea(cliente_norm, linea, ratios)
        nivel = "Línea Completa"

    bultos = total_unidades / ratio_pond if ratio_pond > 0 else 0
    print(f"  [{linea}] método={nivel} ratio={ratio_pond:.1f} unidades={total_unidades} bultos={bultos:.1f}")
    return ratio_pond, bultos, nivel


def procesar_pedido(df_pedido, product_dim, ratios, cliente_raw,
                    col_sku, col_und, col_desc="", col_talla="") -> tuple:
    df_pedido = df_pedido.fillna("")
    cliente_norm = normalizar_cliente(cliente_raw, ratios["clientes_lista"])

    rows = []
    for _, row in df_pedido.iterrows():
        sku      = str(row.get(col_sku, "")).strip()
        unidades = row.get(col_und, 0)
        try:
            unidades = int(float(unidades)) if unidades != "" else 0
        except:
            unidades = 0
        dim      = product_dim[product_dim["sku"].astype(str).str.strip() == sku]
        subclase = dim["subclase"].values[0] if len(dim) > 0 else None
        clase    = dim["clase"].values[0]    if len(dim) > 0 else None
        linea    = dim["linea"].values[0]    if len(dim) > 0 else None
        rows.append({
            "sku":         sku,
            "descripcion": row.get(col_desc, ""),
            "talla":       row.get(col_talla, ""),
            "subclase":    subclase or "",
            "clase":       clase or "",
            "linea":       linea or "",
            "unidades":    unidades,
        })

    df_enrich = pd.DataFrame(rows)
    detalle = []
    resumen_linea = []

    for linea, grupo in df_enrich.groupby("linea"):
        total_und_linea = grupo["unidades"].sum()
        ratio_final, bultos_linea, nivel = calcular_bultos_linea(
            grupo, product_dim, ratios, cliente_norm, linea
        )

        resumen_linea.append({
            "linea":            linea,
            "Línea":            linea,
            "SKUs":             grupo["sku"].nunique(),
            "Unidades_totales": int(total_und_linea),
            "Ratio_und_caja":   round(ratio_final, 1),
            "Bultos_estimados": round(bultos_linea, 1),
            "Nivel_fallback":   nivel,
        })

        for _, row in grupo.iterrows():
            prop = row["unidades"] / total_und_linea if total_und_linea > 0 else 0
            detalle.append({
                "sku":              row["sku"],
                "descripcion":      row["descripcion"],
                "talla":            row["talla"],
                "subclase":         row["subclase"],
                "clase":            row["clase"],
                "linea":            row["linea"],
                "unidades":         row["unidades"],
                "ratio_und_caja":   round(ratio_final, 1),
                "bultos_estimados": round(bultos_linea * prop, 2),
                "nivel_fallback":   nivel,
            })

    return detalle, resumen_linea, cliente_norm


def estimar_tienda_propia(filepath: str) -> dict:
    client      = get_bq_client()
    ratios      = cargar_ratios(client, "tienda_propia")
    product_dim = cargar_product_dim(client)

    df      = pd.read_excel(filepath, dtype={"Código producto": str})
    df      = df.where(pd.notnull(df), None)
    cliente = df["Punto de venta"].iloc[0] if len(df) > 0 else ""

    detalle, resumen_linea, _ = procesar_pedido(
        df, product_dim, ratios, cliente,
        col_sku="Código producto", col_und="Pedidos",
        col_desc="Descripción", col_talla="Talla"
    )

    df_det = pd.DataFrame(detalle)
    total_bultos = sum(r["Bultos_estimados"] for r in resumen_linea)

    resumen_orden = {
        "tipo":             "tienda_propia",
        "punto_de_venta":   cliente,
        "fecha_compromiso": str(df["Fecha Compromiso"].iloc[0])[:10] if "Fecha Compromiso" in df.columns else "",
        "total_skus":       df_det["sku"].nunique(),
        "total_unidades":   int(df_det["unidades"].sum()),
        "total_bultos":     round(total_bultos),
        "lineas":           resumen_linea,
    }

    for r in detalle:
        r["Punto de venta"]   = cliente
        r["Fecha Compromiso"] = resumen_orden["fecha_compromiso"]
        r["Línea"]            = r.pop("linea")
        r["Subclase"]         = r.pop("subclase")
        r["Clase"]            = r.pop("clase")
        r["Código producto"]  = r.pop("sku")
        r["Descripción"]      = r.pop("descripcion")
        r["Talla"]            = r.pop("talla")
        r["Unidades pedidas"] = r.pop("unidades")
        r["Ratio und/caja"]   = r.pop("ratio_und_caja")
        r["Bultos estimados"] = r.pop("bultos_estimados")
        r["Nivel fallback"]   = r.pop("nivel_fallback")

    return {"detalle": detalle, "resumen_linea": resumen_linea, "resumen_orden": resumen_orden}


def estimar_paris_xdb(filepath: str) -> dict:
    client      = get_bq_client()
    ratios      = cargar_ratios(client, "paris")
    product_dim = cargar_product_dim(client)

    df = pd.read_excel(filepath, sheet_name="Original", dtype={"SKU WL": str})
    df = df.where(pd.notnull(df), None)

    resumen_tiendas = []
    detalle_total   = []

    for tienda, grupo in df.groupby("Local Destino"):
        detalle, resumen_linea, _ = procesar_pedido(
            grupo, product_dim, ratios, "Paris",
            col_sku="SKU WL", col_und="Solicitado",
            col_desc="Descripción", col_talla="Talla"
        )
        df_det = pd.DataFrame(detalle)
        bultos_tienda = sum(r["Bultos_estimados"] for r in resumen_linea)

        resumen_tiendas.append({
            "Tienda":           tienda,
            "SKUs":             df_det["sku"].nunique(),
            "Unidades":         int(df_det["unidades"].sum()),
            "Bultos_estimados": round(bultos_tienda, 1),
        })
        for r in detalle:
            r["tienda_destino"] = tienda
        detalle_total.extend(detalle)

    df_all = pd.DataFrame(detalle_total)
    resumen_linea_total = (
        df_all.groupby("linea")
        .agg(SKUs=("sku","nunique"), Unidades_totales=("unidades","sum"),
             Bultos_estimados=("bultos_estimados","sum"))
        .reset_index()
        .assign(Bultos_estimados=lambda x: x["Bultos_estimados"].round(1))
        .to_dict(orient="records")
    )

    resumen_orden = {
        "tipo":           "paris_xdb",
        "n_orden":        str(df["N° Orden"].iloc[0]) if "N° Orden" in df.columns else "",
        "total_tiendas":  df["Local Destino"].nunique(),
        "total_skus":     df_all["sku"].nunique(),
        "total_unidades": int(df_all["unidades"].sum()),
        "total_bultos":   round(df_all["bultos_estimados"].sum()),
        "tiendas":        resumen_tiendas,
        "lineas":         resumen_linea_total,
    }

    return {"detalle": detalle_total, "resumen_tiendas": resumen_tiendas,
            "resumen_linea": resumen_linea_total, "resumen_orden": resumen_orden}


def estimar_bultos(filepath: str, tipo: str = "tienda_propia") -> dict:
    if tipo == "paris_xdb":
        return estimar_paris_xdb(filepath)
    return estimar_tienda_propia(filepath)


if __name__ == "__main__":
    import json, sys
    tipo    = sys.argv[1] if len(sys.argv) > 1 else "tienda_propia"
    archivo = sys.argv[2] if len(sys.argv) > 2 else "test.xlsx"
    r = estimar_bultos(archivo, tipo)
    print(json.dumps(r["resumen_orden"], indent=2, default=str))