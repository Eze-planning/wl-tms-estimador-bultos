import os
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
project  = os.getenv("BQ_PROJECT")
key_path = os.getenv("BQ_KEY_PATH")
creds = service_account.Credentials.from_service_account_file(
    key_path, scopes=["https://www.googleapis.com/auth/bigquery"]
)
client = bigquery.Client(project=project, credentials=creds)

# Ver SKUs en product_dim
df_dim = client.query(f"""
    SELECT CAST(product_sku_num AS STRING) AS sku, product_class_name, product_group_name
    FROM `{project}.dims.product_dim`
    LIMIT 5
""").to_dataframe()
print("product_dim SKUs:")
print(df_dim)
print("Tipo:", df_dim["sku"].dtype)
print("repr:", repr(df_dim["sku"].iloc[0]))

# Ver SKUs en el pedido
df_ped = pd.read_excel("Repo Parque Arauco 2026-04-15.xlsx", dtype={"Código producto": str})
print("\nPedido SKUs:")
print(df_ped["Código producto"].head(5).tolist())
print("repr:", repr(df_ped["Código producto"].iloc[0]))

# Intentar el merge
match = df_dim[df_dim["sku"].astype(str).str.strip() == str(df_ped["Código producto"].iloc[0]).strip()]
print("\nMatch para primer SKU:", len(match), "filas")
print(match)
match2 = df_dim[df_dim["sku"] == "20696"]
print("Busqueda directa '20696':", len(match2))
match3 = df_dim[df_dim["sku"].str.contains("20696", na=False)]
print("Busqueda contains '20696':", len(match3))
# Buscar específicamente el SKU 20696
df_especifico = client.query(f"""
    SELECT CAST(product_sku_num AS STRING) AS sku, product_class_name, product_group_name
    FROM `{project}.dims.product_dim`
    WHERE CAST(product_sku_num AS STRING) = '20696'
""").to_dataframe()
print("\nBúsqueda directa en BQ para '20696':")
print(df_especifico)

# Ver cuántos SKUs hay en total
df_count = client.query(f"SELECT COUNT(*) as total FROM `{project}.dims.product_dim`").to_dataframe()
print("\nTotal SKUs en product_dim:", df_count["total"].values[0])
# Cargar toda la tabla y probar el merge
df_dim_full = client.query(f"""
    SELECT CAST(product_sku_num AS STRING) AS sku, product_class_name, product_group_name
    FROM `{project}.dims.product_dim`
""").to_dataframe()
print("\nTotal cargado:", len(df_dim_full))
match_full = df_dim_full[df_dim_full["sku"].astype(str).str.strip() == "20696"]
print("Match en tabla completa:", len(match_full))
print(match_full)