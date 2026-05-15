"""
app.py
=======
Backend FastAPI para el estimador de bultos.
Soporta tiendas propias y Paris XDB.
"""

import os
import io
import tempfile
import pandas as pd
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from modelo import estimar_bultos
from tarifario_99min import calcular_costo_99min
from despachos import obtener_despachos
from tarifario_shipper import calcular_costo_shipper
from programacion import (
    obtener_semana, guardar_override, eliminar_override, cargar_schedule_base,
    agregar_extra, eliminar_extra
)

app = FastAPI(title="Estimador de Bultos Wild Lama", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/estimar")
async def estimar(
    file: UploadFile = File(...),
    tipo: str = Form(default="tienda_propia")
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser Excel (.xlsx o .xls)")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        resultado = estimar_bultos(tmp_path, tipo)
        if tipo == "tienda_propia":
            orden = resultado["resumen_orden"]
            n     = orden["total_bultos"]
            pdv   = orden["punto_de_venta"]
            resultado["costo_99min"]   = calcular_costo_99min(n, pdv)
            resultado["costo_shipper"] = calcular_costo_shipper(n, pdv)
        return JSONResponse(content=resultado)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.post("/estimar/excel")
async def estimar_excel(
    file: UploadFile = File(...),
    tipo: str = Form(default="tienda_propia")
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser Excel (.xlsx o .xls)")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        resultado = estimar_bultos(tmp_path, tipo)
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            if tipo == "paris_xdb":
                pd.DataFrame(resultado["resumen_tiendas"]).to_excel(writer, sheet_name="Resumen por Tienda", index=False)
            pd.DataFrame(resultado["resumen_linea"]).to_excel(writer, sheet_name="Resumen por Línea", index=False)
            pd.DataFrame(resultado["detalle"]).to_excel(writer, sheet_name="Detalle por SKU", index=False)

        output.seek(0)
        nombre = file.filename.replace(".xlsx", "_estimado.xlsx")
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={nombre}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.get("/despachos")
async def despachos(
    desde: str = Query(default=None),
    hasta: str = Query(default=None),
):
    from datetime import date, timedelta
    if not desde:
        desde = (date.today() - timedelta(days=30)).isoformat()
    if not hasta:
        hasta = date.today().isoformat()
    try:
        data = obtener_despachos(desde, hasta)
        return JSONResponse(content={"despachos": data, "desde": desde, "hasta": hasta})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion")
async def get_programacion():
    try:
        return JSONResponse(content={"schedule": cargar_schedule_base()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion/semana")
async def get_programacion_semana(lunes: str = Query(...)):
    try:
        return JSONResponse(content={"schedule": obtener_semana(lunes), "lunes": lunes})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/programacion/override")
async def post_programacion_override(body: dict):
    try:
        guardar_override(body["lunes"], body["tienda"], body["cambios"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/programacion/override")
async def delete_programacion_override(
    lunes: str = Query(...),
    tienda: str = Query(...)
):
    try:
        eliminar_override(lunes, tienda)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/programacion/extra")
async def post_programacion_extra(body: dict):
    try:
        agregar_extra(body["lunes"], body["entrada"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/programacion/extra")
async def delete_programacion_extra(
    lunes: str = Query(...),
    id: str = Query(...)
):
    try:
        eliminar_extra(lunes, id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion/export")
async def export_programacion(lunes: str = Query(...)):
    try:
        data = obtener_semana(lunes)
        cols = [
            "tienda", "dia_carga", "dia_salida", "hora_salida",
            "courier_preferencia",
            "dia_entrega_99min", "hora_entrega_99min",
            "dia_entrega_shipper", "hora_entrega_shipper",
            "bultos_estimados", "bultos_reales", "override", "extra",
        ]
        df = pd.DataFrame(data).reindex(columns=cols)
        df.columns = [
            "Tienda", "Día Carga", "Día Salida", "Hora Salida",
            "Courier Preferencia",
            "Entrega 99Min (día)", "Entrega 99Min (hora)",
            "Entrega Shipper (día)", "Entrega Shipper (hora)",
            "Bultos Estimados", "Bultos Reales", "Override", "Extra",
        ]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Programación", index=False)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=programacion_{lunes}.xlsx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)