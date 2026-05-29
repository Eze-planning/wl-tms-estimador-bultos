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

# SKUs con ratio fijo conocido para órdenes Paris (no usar histórico)
RATIOS_FIJOS_PARIS = {
    "WL132107201000511": 50,  # 586712002 en Paris
}


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


def calcular_bultos_linea(df_linea, product_dim, ratios, cliente_norm, linea,
                          ratios_fijos: dict = None) -> tuple:
    total_unidades = df_linea["unidades"].sum()
    ratios_fijos = ratios_fijos or {}
    ratio_pond = 0
    niveles = set()

    for _, row in df_linea.iterrows():
        sku  = str(row["sku"]).strip()
        peso = row["unidades"] / total_unidades if total_unidades > 0 else 0

        if sku in ratios_fijos:
            ratio = ratios_fijos[sku]
            niveles.add("Ratio Fijo")
        elif linea in LINEAS_POR_SUBCLASE:
            dim      = product_dim[product_dim["sku"].astype(str).str.strip() == sku]
            subclase = dim["subclase"].values[0] if len(dim) > 0 else None
            clase    = dim["clase"].values[0]    if len(dim) > 0 else None
            ratio    = obtener_ratio_subclase(cliente_norm, subclase, clase, ratios)
            niveles.add("Ponderado por Subclase")
        else:
            ratio = obtener_ratio_linea(cliente_norm, linea, ratios)
            niveles.add("Línea Completa")

        ratio_pond += peso * ratio

    nivel = " + ".join(sorted(niveles)) if niveles else "Global"
    bultos = total_unidades / ratio_pond if ratio_pond > 0 else 0
    print(f"  [{linea}] método={nivel} ratio={ratio_pond:.1f} unidades={total_unidades} bultos={bultos:.1f}")
    return ratio_pond, bultos, nivel


def procesar_pedido(df_pedido, product_dim, ratios, cliente_raw,
                    col_sku, col_und, col_desc="", col_talla="",
                    ratios_fijos: dict = None) -> tuple:
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
            grupo, product_dim, ratios, cliente_norm, linea,
            ratios_fijos=ratios_fijos
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


def _resolver_sku_wl(df: pd.DataFrame, filepath: str) -> pd.DataFrame:
    """Une la OC con la Mini Maestra (sheet 1) para obtener SKU WL confiable."""
    mini = pd.read_excel(filepath, sheet_name=1, dtype=str)
    mini.columns = [c.strip() for c in mini.columns]
    mapping = dict(zip(
        mini["SKU PARIS"].str.strip(),
        mini["SKU HIJO WL"].str.strip()
    ))
    df = df.copy()
    df["SKU WL"] = df["SKU Paris"].astype(str).str.strip().map(mapping)
    return df


def estimar_paris_xdb(filepath: str) -> dict:
    client      = get_bq_client()
    ratios      = cargar_ratios(client, "paris")
    product_dim = cargar_product_dim(client)

    df = pd.read_excel(filepath, sheet_name=0, dtype={"SKU Paris": str})
    df = _resolver_sku_wl(df, filepath)
    df = df.where(pd.notnull(df), None)

    resumen_tiendas = []
    detalle_total   = []

    for tienda, grupo in df.groupby("Local Destino"):
        detalle, resumen_linea, _ = procesar_pedido(
            grupo, product_dim, ratios, "Paris",
            col_sku="SKU WL", col_und="Solicitado",
            col_desc="Descripción", col_talla="Talla",
            ratios_fijos=RATIOS_FIJOS_PARIS
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

    for r in detalle_total:
        r["Tienda"]           = r.pop("tienda_destino")
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

    return {"detalle": detalle_total, "resumen_tiendas": resumen_tiendas,
            "resumen_linea": resumen_linea_total, "resumen_orden": resumen_orden}


def estimar_paris_stock(filepath: str) -> dict:
    df = pd.read_excel(filepath, sheet_name=0, dtype=str)
    df = df.where(pd.notnull(df), None)

    # Convertir Solicitado a numérico
    df["Solicitado"] = pd.to_numeric(df["Solicitado"], errors="coerce").fillna(0).astype(int)

    client      = get_bq_client()
    ratios      = cargar_ratios(client, "paris")
    product_dim = cargar_product_dim(client)

    # Usar SKU WL si está en el archivo, si no usar Cód. Prod. Prov.
    sku_col = next(
        (c for c in df.columns if "WILD" in c.upper() or "WL" in c.upper()),
        next((c for c in df.columns if "Prod. Prov" in c or "PROV" in c.upper()), None)
    )

    desc_col = next((c for c in df.columns if "escripci" in c), "")
    talla_col = "Talla" if "Talla" in df.columns else ""

    detalle, resumen_linea, _ = procesar_pedido(
        df, product_dim, ratios, "Paris",
        col_sku=sku_col, col_und="Solicitado",
        col_desc=desc_col, col_talla=talla_col,
        ratios_fijos=RATIOS_FIJOS_PARIS
    )

    df_det = pd.DataFrame(detalle)
    n_orden_col = next((c for c in df.columns if "rden" in c and c.upper().startswith("N")), None)

    resumen_orden = {
        "tipo":           "paris_stock",
        "n_orden":        str(df[n_orden_col].iloc[0]) if n_orden_col else "",
        "total_skus":     df_det["sku"].nunique(),
        "total_unidades": int(df_det["unidades"].sum()),
        "total_bultos":   round(sum(r["Bultos_estimados"] for r in resumen_linea)),
        "lineas":         resumen_linea,
    }

    for r in detalle:
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


def estimar_paris(filepath: str) -> dict:
    df_header = pd.read_excel(filepath, sheet_name=0, nrows=1)
    tipo_orden = ""
    if "Tipo de Orden" in df_header.columns:
        tipo_orden = str(df_header["Tipo de Orden"].iloc[0]).strip()
    if tipo_orden == "Stock":
        return estimar_paris_stock(filepath)
    return estimar_paris_xdb(filepath)


def estimar_multi_tienda(filepath: str) -> dict:
    client      = get_bq_client()
    ratios      = cargar_ratios(client, "tienda_propia")
    product_dim = cargar_product_dim(client)

    df = pd.read_excel(filepath, dtype={"Código producto": str})
    df = df.where(pd.notnull(df), None)

    tiendas_result = []
    detalle_total  = []

    for tienda_raw, grupo in df.groupby("Punto de venta"):
        tienda = str(tienda_raw).strip()
        detalle, resumen_linea, _ = procesar_pedido(
            grupo, product_dim, ratios, tienda,
            col_sku="Código producto", col_und="Pedidos",
            col_desc="Descripción", col_talla="Talla"
        )
        df_det = pd.DataFrame(detalle)
        bultos_tienda = sum(r["Bultos_estimados"] for r in resumen_linea)

        tiendas_result.append({
            "tienda":           tienda,
            "total_skus":       df_det["sku"].nunique() if len(df_det) > 0 else 0,
            "total_unidades":   int(df_det["unidades"].sum()) if len(df_det) > 0 else 0,
            "total_bultos":     round(bultos_tienda),
            "lineas":           resumen_linea,
        })
        for r in detalle:
            r["tienda"] = tienda
        detalle_total.extend(detalle)

    df_all = pd.DataFrame(detalle_total) if detalle_total else pd.DataFrame()

    resumen_linea_global = (
        df_all.groupby("linea")
        .agg(SKUs=("sku","nunique"), Unidades_totales=("unidades","sum"),
             Bultos_estimados=("bultos_estimados","sum"))
        .reset_index()
        .assign(Bultos_estimados=lambda x: x["Bultos_estimados"].round(1))
        .rename(columns={"linea": "Línea"})
        .to_dict(orient="records")
    ) if len(df_all) > 0 else []

    resumen_orden = {
        "tipo":             "multi_tienda",
        "n_tiendas":        len(tiendas_result),
        "total_skus":       int(df_all["sku"].nunique()) if len(df_all) > 0 else 0,
        "total_unidades":   int(df_all["unidades"].sum()) if len(df_all) > 0 else 0,
        "total_bultos":     round(sum(t["total_bultos"] for t in tiendas_result)),
    }

    return {
        "tiendas_detalle": tiendas_result,
        "resumen_linea":   resumen_linea_global,
        "resumen_orden":   resumen_orden,
    }


def estimar_bultos(filepath: str, tipo: str = "tienda_propia") -> dict:
    if tipo in ("paris_xdb", "paris"):
        return estimar_paris(filepath)
    if tipo == "multi_tienda":
        return estimar_multi_tienda(filepath)
    return estimar_tienda_propia(filepath)


if __name__ == "__main__":
    import json, sys
    tipo    = sys.argv[1] if len(sys.argv) > 1 else "tienda_propia"
    archivo = sys.argv[2] if len(sys.argv) > 2 else "test.xlsx"
    r = estimar_bultos(archivo, tipo)
    print(json.dumps(r["resumen_orden"], indent=2, default=str))