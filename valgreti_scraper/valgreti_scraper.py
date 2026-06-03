"""
valgreti_scraper.py - Valgreti -> BigQuery
Uso:
  python valgreti_scraper.py --mode historico
  python valgreti_scraper.py --mode incremental
"""

import argparse, os, time, logging
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

BASE_URL       = "http://valgretiapp2.brazilsouth.cloudapp.azure.com:4190/EDARKSTORE/EnfasysWMS_Admin_PROD"
LOGIN_URL      = f"{BASE_URL}/VIEW/Security/login.aspx"
LOG_EMB_URL    = f"{BASE_URL}/VIEW/Salida/HistorialVAS.aspx"
DOC_SAL_URL    = f"{BASE_URL}/VIEW/Salida/DocumentoSalida.aspx"
LOG_REC_URL    = f"{BASE_URL}/VIEW/Entrada/LogCrearCaja.aspx"
STOCK_ITEM_URL = f"{BASE_URL}/VIEW/Stock/ConsultaStockItem.aspx"

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "valgreti_scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def get_credentials():
    user = os.getenv("VALGRETI_USER")
    pwd  = os.getenv("VALGRETI_PASS")
    if not user or not pwd:
        raise ValueError("Faltan VALGRETI_USER y/o VALGRETI_PASS en .env")
    return user, pwd


def get_bq_client():
    project, dataset, key_path = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET"), os.getenv("BQ_KEY_PATH")
    if not all([project, dataset, key_path]):
        raise ValueError("Faltan BQ_PROJECT, BQ_DATASET o BQ_KEY_PATH en .env")
    creds  = service_account.Credentials.from_service_account_file(key_path, scopes=["https://www.googleapis.com/auth/bigquery"])
    client = bigquery.Client(project=project, credentials=creds)
    log.info(f"Conectado a BigQuery: {project}.{dataset}")
    return client


def login(page, user, pwd):
    log.info("Iniciando sesion en Valgreti...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1000)
    page.locator("input[type='text'], input:not([type])").first.fill(user)
    page.locator("input[type='password']").fill(pwd)
    page.get_by_role("button", name="Aceptar").click()
    page.wait_for_url("**Menu.aspx**", timeout=30000)
    log.info("Login exitoso.")


def set_date_js(page, field_id, date_str):
    page.evaluate(f"""
        var el = document.getElementById('{field_id}');
        if (el) {{
            el.removeAttribute('disabled');
            el.value = '{date_str}';
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
    """)


def download_log_embalaje(page, fecha_desde, fecha_hasta):
    log.info(f"[log_embalaje] Descargando {fecha_desde} -> {fecha_hasta}")
    page.goto(LOG_EMB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    set_date_js(page, "bodyContent_txtFechaDesde", fecha_desde)
    set_date_js(page, "bodyContent_txtFechaHasta", fecha_hasta)
    page.wait_for_timeout(500)

    page.get_by_role("button", name="Buscar").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)

    if page.locator("text=No existen datos para mostrar").count() > 0:
        log.info("[log_embalaje] Sin datos. Saltando.")
        return None

    dest = DOWNLOAD_DIR / f"log_embalaje_{fecha_desde.replace('/','-')}_{fecha_hasta.replace('/','-')}.xlsx"
    with page.expect_download(timeout=60000) as dl:
        page.get_by_role("button", name="Excel").click()
    dl.value.save_as(dest)
    log.info(f"[log_embalaje] Guardado: {dest}")
    return dest


def download_documento_salida(page, fecha_desde, fecha_hasta):
    log.info(f"[documento_salida] Descargando {fecha_desde} -> {fecha_hasta}")
    page.goto(DOC_SAL_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    try:
        page.get_by_text("1: Buscar").click()
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Seleccionar Tipo Fecha = Fecha Compromiso
    tipo_fecha = page.locator("select[id*='TipoFecha'], select[id*='tipoFecha']").first
    try:
        tipo_fecha.select_option(label="Fecha Compromiso")
    except Exception:
        # intentar por indice si el label falla
        tipo_fecha.select_option(index=1)
    page.wait_for_timeout(1000)

    set_date_js(page, "bodyContent_txtFechaDesde", fecha_desde)
    set_date_js(page, "bodyContent_txtFechaHasta", fecha_hasta)
    page.wait_for_timeout(500)

    page.get_by_role("button", name="Buscar").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)

    if page.locator("text=No existen datos para mostrar").count() > 0:
        log.info("[documento_salida] Sin datos. Saltando.")
        return None

    dest = DOWNLOAD_DIR / f"documento_salida_{fecha_desde.replace('/','-')}_{fecha_hasta.replace('/','-')}.xlsx"
    with page.expect_download(timeout=60000) as dl:
        page.get_by_role("button", name="Excel").click()
    dl.value.save_as(dest)
    log.info(f"[documento_salida] Guardado: {dest}")
    return dest


def normalize_columns(df):
    df.columns = (df.columns.str.strip().str.lower()
        .str.replace(" ","_").str.replace("á","a").str.replace("é","e")
        .str.replace("í","i").str.replace("ó","o").str.replace("ú","u")
        .str.replace("ñ","n").str.replace("#","q").str.replace(".",""))
    return df


SCHEMA_LOG_EMBALAJE = [
    bigquery.SchemaField("id","INTEGER"), bigquery.SchemaField("empresa","INTEGER"),
    bigquery.SchemaField("deposito","STRING"), bigquery.SchemaField("proceso","INTEGER"),
    bigquery.SchemaField("nombre_proceso","STRING"), bigquery.SchemaField("nro_orden_salida","STRING"),
    bigquery.SchemaField("caja_origen","STRING"), bigquery.SchemaField("caja_destino","STRING"),
    bigquery.SchemaField("item","STRING"), bigquery.SchemaField("descripcion","STRING"),
    bigquery.SchemaField("q_revisada","INTEGER"), bigquery.SchemaField("fecha_inicio","DATE"),
    bigquery.SchemaField("hora_inicio","STRING"), bigquery.SchemaField("fecha_termino","DATE"),
    bigquery.SchemaField("hora_termino","STRING"), bigquery.SchemaField("fecha_creacion","TIMESTAMP"),
    bigquery.SchemaField("usuario","STRING"), bigquery.SchemaField("insertado_en","TIMESTAMP"),
]

SCHEMA_DOCUMENTO_SALIDA = [
    bigquery.SchemaField("orden_salida","STRING"), bigquery.SchemaField("row_no","INTEGER"),
    bigquery.SchemaField("cod_owner","STRING"), bigquery.SchemaField("tipo","STRING"),
    bigquery.SchemaField("estado","STRING"), bigquery.SchemaField("nom_cliente","STRING"),
    bigquery.SchemaField("cod_cliente","STRING"), bigquery.SchemaField("nro_orden_cliente","STRING"),
    bigquery.SchemaField("nro_referencia","STRING"), bigquery.SchemaField("transporte","STRING"),
    bigquery.SchemaField("lineas","INTEGER"), bigquery.SchemaField("q_solicitadas","INTEGER"),
    bigquery.SchemaField("q_un_solicitadas","INTEGER"), bigquery.SchemaField("q_cajas_pickeadas","INTEGER"),
    bigquery.SchemaField("q_un_pickeadas","INTEGER"), bigquery.SchemaField("q_cajas_separadas","INTEGER"),
    bigquery.SchemaField("q_un_separadas","INTEGER"), bigquery.SchemaField("q_cajas_embaladas","INTEGER"),
    bigquery.SchemaField("q_un_embaladas","INTEGER"), bigquery.SchemaField("insertado_en","TIMESTAMP"),
    bigquery.SchemaField("actualizado_en","TIMESTAMP"),
]


SCHEMA_LOG_RECEPCION = [
    bigquery.SchemaField("id",                "INTEGER"),
    bigquery.SchemaField("empresa",           "INTEGER"),
    bigquery.SchemaField("deposito",          "STRING"),
    bigquery.SchemaField("tipo_recepcion",    "STRING"),
    bigquery.SchemaField("nro_orden_entrada", "STRING"),
    bigquery.SchemaField("orden_cliente",     "STRING"),
    bigquery.SchemaField("doc_referencia",    "STRING"),
    bigquery.SchemaField("tipo_referencia",   "STRING"),
    bigquery.SchemaField("ubicacion_origen",  "STRING"),
    bigquery.SchemaField("pallet",            "STRING"),
    bigquery.SchemaField("caja",              "STRING"),
    bigquery.SchemaField("cod_item",          "STRING"),
    bigquery.SchemaField("nom_item",          "STRING"),
    bigquery.SchemaField("cantidad",          "FLOAT"),
    bigquery.SchemaField("ut",                "STRING"),
    bigquery.SchemaField("unidades",          "FLOAT"),
    bigquery.SchemaField("numero_lote",       "STRING"),
    bigquery.SchemaField("fecha_fabricacion", "STRING"),
    bigquery.SchemaField("fecha_expiracion",  "STRING"),
    bigquery.SchemaField("fecha_recepcion",   "DATE"),
    bigquery.SchemaField("hora_recepcion",    "STRING"),
    bigquery.SchemaField("motivo_devolucion", "STRING"),
    bigquery.SchemaField("usuario",           "STRING"),
    bigquery.SchemaField("observacion",       "STRING"),
    bigquery.SchemaField("insertado_en",      "TIMESTAMP"),
]


def download_log_recepcion(page, fecha_desde, fecha_hasta):
    log.info(f"[log_recepcion] Descargando {fecha_desde} -> {fecha_hasta}")
    page.goto(LOG_REC_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    set_date_js(page, "bodyContent_txtFechaInicio", fecha_desde)
    set_date_js(page, "bodyContent_txtFechaFin", fecha_hasta)
    page.wait_for_timeout(500)

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    page.get_by_role("button", name="Buscar").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(15000)

    if page.locator("text=No existen datos para mostrar").count() > 0:
        log.info("[log_recepcion] Sin datos. Saltando.")
        return None

    dest = DOWNLOAD_DIR / f"log_recepcion_{fecha_desde.replace('/','-')}_{fecha_hasta.replace('/','-')}.xlsx"
    page.wait_for_timeout(2000)
    with page.expect_download(timeout=300000) as dl:
        page.locator("#bodyContent_btnExportar").click(timeout=300000)
    dl.value.save_as(dest)
    log.info(f"[log_recepcion] Guardado: {dest}")
    return dest


def load_log_recepcion(client, filepath):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    table_id = f"{p}.{d}.log_recepcion"

    try:
        df = normalize_columns(pd.read_excel(filepath, dtype=str))
    except Exception:
        df = normalize_columns(pd.read_html(filepath, header=0)[0].astype(str))

    df = df.drop(columns=["q", "rowno"], errors="ignore")
    df = df.rename(columns={
        "tiporecepcion":   "tipo_recepcion",
    "nroordentrada":   "nro_orden_entrada",
        "ordencliente":    "orden_cliente",
        "docreferencia":   "doc_referencia",
        "tiporeferencia":  "tipo_referencia",
        "ubicacionorigen": "ubicacion_origen",
        "coditem":         "cod_item",
        "nomitem":         "nom_item",
        "numerolote":      "numero_lote",
        "fechafabricacion":"fecha_fabricacion",
        "fechaexpiracion": "fecha_expiracion",
        "fecharecepcion":  "fecha_recepcion",
        "horarecepcion":   "hora_recepcion",
        "motivodevolucion":"motivo_devolucion",
    })

    df["insertado_en"] = pd.Timestamp.now(tz="UTC")

    for col in ["id", "empresa"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["cantidad", "unidades"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "fecha_recepcion" in df.columns:
        df["fecha_recepcion"] = pd.to_datetime(df["fecha_recepcion"], errors="coerce", dayfirst=True).dt.date

    job_config = bigquery.LoadJobConfig(autodetect=True, write_disposition="WRITE_APPEND")
    try:
        ids = df["id"].dropna().astype(int).tolist()
        if ids:
            client.query(f"DELETE FROM `{table_id}` WHERE id IN ({','.join(str(i) for i in ids)})").result()
    except Exception:
        pass  # tabla no existe aún, el insert la crea
    client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
    log.info(f"Log Recepcion: {len(df)} filas cargadas.")


def ensure_table(client, table_id, schema):
    try:
        client.get_table(table_id)
        log.info(f"Tabla {table_id} ya existe.")
    except Exception:
        client.create_table(bigquery.Table(table_id, schema=schema))
        log.info(f"Tabla {table_id} creada.")


def init_bq(client):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    ensure_table(client, f"{p}.{d}.log_embalaje", SCHEMA_LOG_EMBALAJE)
    ensure_table(client, f"{p}.{d}.documento_salida", SCHEMA_DOCUMENTO_SALIDA)
    # log_recepcion se crea automáticamente con autodetect en el primer insert


def load_log_embalaje(client, filepath):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    table_id = f"{p}.{d}.log_embalaje"
    df = normalize_columns(pd.read_excel(filepath, dtype=str))
    df = df.drop(columns=["q"], errors="ignore")
    df = df.rename(columns={"nombreproceso":"nombre_proceso","nroordensalida":"nro_orden_salida",
        "cajaorigen":"caja_origen","cajadestino":"caja_destino","qrevisada":"q_revisada",
        "fechainicio":"fecha_inicio","horainicio":"hora_inicio","fechatermino":"fecha_termino",
        "horatermino":"hora_termino","fechacreacion":"fecha_creacion"})
    df["insertado_en"] = pd.Timestamp.now(tz="UTC")
    if "fecha_creacion" in df.columns:
        fc = pd.to_datetime(df["fecha_creacion"], errors="coerce", dayfirst=True)
        df["fecha_creacion"] = fc.dt.tz_localize("UTC") if fc.dt.tz is None else fc.dt.tz_convert("UTC")
    for col in ["id","empresa","proceso","q_revisada"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["fecha_inicio","fecha_termino"]:
        if col in df.columns: df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    ids = df["id"].dropna().astype(int).tolist()
    if ids:
        client.query(f"DELETE FROM `{table_id}` WHERE id IN ({','.join(str(i) for i in ids)})").result()
    client.load_table_from_dataframe(df, table_id).result()
    log.info(f"Log Embalaje: {len(df)} filas cargadas.")


def load_documento_salida(client, filepath):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    table_id = f"{p}.{d}.documento_salida"
    try:
        df = normalize_columns(pd.read_excel(filepath, dtype=str))
    except Exception:
        df = normalize_columns(pd.read_html(filepath, header=0)[0].astype(str))
    df = df.rename(columns={"ordensalida":"orden_salida","rowno":"row_no","codowner":"cod_owner",
        "nomcliente":"nom_cliente","codcliente":"cod_cliente","nrordencliente":"nro_orden_cliente",
        "nroreferencia":"nro_referencia","qsolicitadas":"q_solicitadas","qunsolicitadas":"q_un_solicitadas",
        "qcajaspickeadas":"q_cajas_pickeadas","qunpickeadas":"q_un_pickeadas",
        "qcajasseparadas":"q_cajas_separadas","qunseparadas":"q_un_separadas",
        "qcajasembaladas":"q_cajas_embaladas","qunembaladas":"q_un_embaladas"})
    now = pd.Timestamp.now(tz="UTC").isoformat()
    df["insertado_en"] = now; df["actualizado_en"] = now
    for col in ["row_no","lineas","q_solicitadas","q_un_solicitadas","q_cajas_pickeadas",
                "q_un_pickeadas","q_cajas_separadas","q_un_separadas","q_cajas_embaladas","q_un_embaladas"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
    ordenes = df["orden_salida"].dropna().tolist()
    if ordenes:
        client.query(f"DELETE FROM `{table_id}` WHERE orden_salida IN ({','.join(repr(o) for o in ordenes)})").result()
    job_config = bigquery.LoadJobConfig(autodetect=True, write_disposition="WRITE_APPEND")
    client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
    log.info(f"Documento Salida: {len(df)} filas cargadas.")


def get_date_ranges(start, end, chunk_days=30):
    ranges, current = [], start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days-1), end)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


def get_last_date_bq(client, table, date_col):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    result = list(client.query(f"SELECT MAX({date_col}) as max_date FROM `{p}.{d}.{table}`").result())
    val = result[0].max_date if result else None
    inicio = date(2025, 1, 1) if table == "log_recepcion" else date(2020, 1, 1)
    if val is None:
        return inicio
    if isinstance(val, date):
        return val if not isinstance(val, datetime) else val.date()
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).date()
    except Exception:
        return inicio


def run_historico(page, client, start_date, end_date):
    log.info(f"=== MODO HISTORICO: {start_date} -> {end_date} ===")
    for desde, hasta in get_date_ranges(start_date, end_date):
        fd, fh = desde.strftime("%d/%m/%Y"), hasta.strftime("%d/%m/%Y")
        path = download_log_embalaje(page, fd, fh)
        if path: load_log_embalaje(client, path)
        time.sleep(2)
        path = download_documento_salida(page, fd, fh)
        if path: load_documento_salida(client, path)
        time.sleep(2)
        path = download_log_recepcion(page, fd, fh)
        if path: load_log_recepcion(client, path)
        time.sleep(2)
    log.info("=== HISTORICO COMPLETADO ===")


def run_incremental(page, client):
    log.info("=== MODO INCREMENTAL ===")
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    # Siempre reprocesa al menos desde ayer para cubrir posibles huecos del día anterior
    desde_emb = min(get_last_date_bq(client, "log_embalaje", "fecha_inicio") + timedelta(days=1), ayer)
    desde_doc = min(get_last_date_bq(client, "documento_salida", "actualizado_en") + timedelta(days=1), ayer)
    desde_rec = min(get_last_date_bq(client, "log_recepcion", "fecha_recepcion") + timedelta(days=1), ayer)

    if desde_emb <= hoy:
        path = download_log_embalaje(page, desde_emb.strftime("%d/%m/%Y"), hoy.strftime("%d/%m/%Y"))
        if path: load_log_embalaje(client, path)
    else:
        log.info("Log Embalaje ya esta al dia.")
    time.sleep(2)

    if desde_doc <= hoy:
        path = download_documento_salida(page, desde_doc.strftime("%d/%m/%Y"), hoy.strftime("%d/%m/%Y"))
        if path: load_documento_salida(client, path)
    else:
        log.info("Documento Salida ya esta al dia.")
    time.sleep(2)

    if desde_rec <= hoy:
        path = download_log_recepcion(page, desde_rec.strftime("%d/%m/%Y"), hoy.strftime("%d/%m/%Y"))
        if path: load_log_recepcion(client, path)
    else:
        log.info("Log Recepcion ya esta al dia.")

    log.info("=== INCREMENTAL COMPLETADO ===")


def download_stock_actual(page):
    log.info("[stock_actual] Descargando stock por item...")
    page.goto(STOCK_ITEM_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    page.locator("#bodyContent_btnBuscar").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(5000)
    dest = DOWNLOAD_DIR / "stock_actual.xlsx"
    with page.expect_download(timeout=120000) as dl:
        page.locator("#bodyContent_btnExportar").click()
    dl.value.save_as(dest)
    log.info(f"[stock_actual] Guardado: {dest}")
    return dest


def load_stock_actual(client, filepath):
    p, d = os.getenv("BQ_PROJECT"), os.getenv("BQ_DATASET")
    table_id = f"{p}.{d}.stock_actual"
    df = normalize_columns(pd.read_excel(filepath, dtype=str))
    df = df.where(pd.notnull(df), None)
    df = df.loc[:, df.columns != ""]                          # quitar col sin nombre
    for c in df.columns:
        if any(k in c for k in ["cantidad", "unidad", "stock"]):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in df.columns:                                      # cols vacías → STRING
        if df[c].isna().all():
            df[c] = df[c].astype(str).where(df[c].notna(), None)
    job_config = bigquery.LoadJobConfig(
        autodetect=True,
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
    log.info(f"Stock Actual: {len(df)} filas en {table_id}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["historico","incremental","stock-actual"], default="incremental")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    user, pwd = get_credentials()
    client = get_bq_client()
    init_bq(client)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, downloads_path=str(DOWNLOAD_DIR))
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            login(page, user, pwd)
            if args.mode == "historico":
                run_historico(page, client,
                    datetime.strptime(args.start, "%Y-%m-%d").date(),
                    datetime.strptime(args.end, "%Y-%m-%d").date())
            elif args.mode == "stock-actual":
                path = download_stock_actual(page)
                load_stock_actual(client, path)
            else:
                run_incremental(page, client)
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)
            raise
        finally:
            context.close()
            browser.close()
    log.info("Proceso finalizado.")


if __name__ == "__main__":
    main()
