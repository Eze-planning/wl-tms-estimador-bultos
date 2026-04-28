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
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from modelo import estimar_bultos

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)