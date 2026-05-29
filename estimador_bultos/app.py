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
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

# Secreto compartido para llamadas internas desde Cloud Scheduler.
# Debe setearse como variable de entorno CRON_SECRET en Cloud Run.
_CRON_SECRET = os.getenv("CRON_SECRET", "")

from modelo import estimar_bultos, estimar_multi_tienda
from collections import defaultdict
from tarifario_99min import calcular_costo_99min
from tarifario_shipper import (
    calcular_costo_shipper, resolver_destino as shipper_destino,
    RUTAS, TARIFAS as SHIP_TARIFAS, PIONETA_COSTO,
)
from despachos import obtener_despachos
from programacion import (
    obtener_semana, guardar_override, eliminar_override, cargar_schedule_base,
    agregar_extra, eliminar_extra, resolver_tienda, obtener_ordenes, guardar_orden
)
from auth import (
    authenticate_user, create_token, get_current_user, require_edit, require_admin,
    get_all_users, create_user, update_user, delete_user, ROLES,
)
try:
    from bultos_reales import (
        consultar_bultos_reales, invalidar_cache, MAPEO_CLIENTES,
        reconstruir_base_embalaje, estado_tablas, guardar_mapeo_cliente,
    )
    _BQ_DISPONIBLE = True
except Exception:
    _BQ_DISPONIBLE = False

app = FastAPI(title="Estimador de Bultos Wild Lama", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _costo_directo_shipper(tienda: str, tipo: str = "XL") -> int | None:
    try:
        destino = shipper_destino(tienda)
        if not destino or destino not in SHIP_TARIFAS:
            return None
        t    = SHIP_TARIFAS[destino]
        base = t.get(tipo if tipo in ("L", "XL") else "XL")
        if base is None:
            return None
        return round(base + (PIONETA_COSTO if t.get("pioneta") else 0))
    except Exception:
        return None


def _enriquecer_ocs(schedule: list) -> None:
    """Calcula bultos, hora_entrega_shipper (más temprana) desde ordenes_compra."""
    for e in schedule:
        ocs = e.get("ordenes_compra") or []
        if not ocs:
            continue
        est  = sum((oc.get("bultos_estimados") or 0) for oc in ocs)
        real = sum((oc.get("bultos_reales")    or 0) for oc in ocs)
        if est  > 0: e["bultos_estimados"] = est
        if real > 0: e["bultos_reales"]    = real
        citas = sorted(oc["hora_cita"] for oc in ocs if oc.get("hora_cita"))
        if citas:
            e["hora_entrega_shipper"] = citas[0]


def _enriquecer_costos(schedule: list) -> None:
    """
    Agrega costo_estimado, ruta_nombre, n_sharing y rutas_disponibles a cada entry in-place.
    Shipper: costo por camión (L/XL default), con detección automática de rutas compartidas por día.
    Si entry.ruta_override está seteado, se usa esa ruta en lugar de la auto-detectada.
    99min:   costo por bultos (peso volumétrico).
    """
    shipper_por_dia: dict[str, list] = defaultdict(list)
    for e in schedule:
        courier = e.get("courier_preferencia", "")
        if courier and "99" not in courier:
            dia = e.get("dia_salida") or ""
            if dia:
                shipper_por_dia[dia].append(e)

    day_route_sharing: dict[tuple, list] = {}
    for dia, stores in shipper_por_dia.items():
        destinos = {e["tienda"]: shipper_destino(e["tienda"]) for e in stores}
        destinos = {k: v for k, v in destinos.items() if v}
        for ruta in RUTAS:
            sharing = [t for t, d in destinos.items() if d in ruta["destinos"]]
            if len(sharing) >= 2:
                day_route_sharing[(dia, ruta["nombre"])] = sharing

    route_cache: dict[str, dict] = {}
    for (dia, rname), sharing in day_route_sharing.items():
        n    = len(sharing)
        ruta = next(r for r in RUTAS if r["nombre"] == rname)
        for tienda in sharing:
            prev = route_cache.get(tienda)
            if not prev or prev["n"] < n:
                route_cache[tienda] = {
                    "nombre": rname,
                    "n":      n,
                    "L":      round(ruta["L"] / n),
                    "XL":     round(ruta["XL"] / n),
                }

    for e in schedule:
        courier = e.get("courier_preferencia", "")
        tienda  = e.get("tienda", "")
        tipo    = e.get("tipo_camion") or "XL"

        if "99" in courier:
            bultos = int(e.get("bultos_reales") or e.get("bultos_estimados") or 0)
            if bultos > 0:
                r = calcular_costo_99min(bultos, tienda)
                e["costo_estimado"] = r.get("costo_total") if r and not r.get("advertencia") else None
            else:
                e["costo_estimado"] = None
            e["ruta_nombre"]       = None
            e["n_sharing"]         = None
            e["rutas_disponibles"] = []

        elif courier:   # Shipper
            e["rutas_disponibles"] = [r["nombre"] for r in RUTAS]

            ruta_override = e.get("ruta_override") or ""
            if ruta_override == "directo":
                e["costo_estimado"] = _costo_directo_shipper(tienda, tipo)
                e["ruta_nombre"]    = "Directo"
                e["n_sharing"]      = None
            elif ruta_override:
                ruta_obj = next((r for r in RUTAS if r["nombre"] == ruta_override), None)
                if ruta_obj:
                    dia      = e.get("dia_salida") or ""
                    sharing  = day_route_sharing.get((dia, ruta_override), [tienda])
                    n        = max(len(sharing), 1)
                    t_key    = tipo if tipo in ("L", "XL") else "XL"
                    e["costo_estimado"] = round(ruta_obj[t_key] / n)
                    e["ruta_nombre"]    = ruta_override
                    e["n_sharing"]      = n
                else:
                    e["costo_estimado"] = _costo_directo_shipper(tienda, tipo)
                    e["ruta_nombre"]    = None
                    e["n_sharing"]      = None
            else:
                ri = route_cache.get(tienda)
                if ri:
                    e["costo_estimado"] = ri.get(tipo if tipo in ("L", "XL") else "XL")
                    e["ruta_nombre"]    = ri["nombre"]
                    e["n_sharing"]      = ri["n"]
                else:
                    e["costo_estimado"] = _costo_directo_shipper(tienda, tipo)
                    e["ruta_nombre"]    = None
                    e["n_sharing"]      = None

        else:
            e["costo_estimado"]    = None
            e["ruta_nombre"]       = None
            e["n_sharing"]         = None
            e["rutas_disponibles"] = []

        if e.get("costo_manual") is not None:
            e["costo_estimado"]  = e["costo_manual"]
            e["costo_es_manual"] = True
        else:
            e["costo_es_manual"] = False


_GRANDES_TIENDAS = {"Paris", "Ripley", "Falabella"}


def _dia_iso(lunes_iso: str, dia_salida: str) -> str | None:
    """Convierte dia_salida ('Lunes', 'Martes'…) a fecha ISO relativa a lunes_iso."""
    import unicodedata
    _OFF = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4}
    norm = "".join(c for c in unicodedata.normalize("NFD", (dia_salida or "").lower())
                   if unicodedata.category(c) != "Mn")
    off = _OFF.get(norm)
    if off is None:
        return None
    from datetime import date, timedelta
    return (date.fromisoformat(lunes_iso) + timedelta(days=off)).isoformat()


def _enriquecer_bultos_reales(schedule: list, lunes_iso: str) -> list[str]:
    """
    Inyecta bultos_reales desde base_embalaje BQ.
    - GT (Paris/Ripley/Falabella): actualiza bultos_reales por OC dentro de ordenes_compra.
    - Resto: actualiza bultos_reales de la entry.
    Retorna lista de nom_cliente sin mapeo (para diagnóstico).
    No lanza excepción: si BQ falla, el schedule queda intacto.
    """
    if not _BQ_DISPONIBLE:
        return []
    try:
        datos = consultar_bultos_reales(lunes_iso)
    except Exception:
        return []

    sin_mapeo = datos.get("_sin_mapeo") or []

    # Contar entradas por tienda para decidir si usar match por fecha
    entradas_por_tienda: dict[str, int] = {}
    for e in schedule:
        t = e.get("tienda", "")
        entradas_por_tienda[t] = entradas_por_tienda.get(t, 0) + 1

    for e in schedule:
        tienda = e.get("tienda", "")
        info   = datos.get(tienda)
        if not info:
            continue

        if tienda in _GRANDES_TIENDAS:
            ocs = e.get("ordenes_compra") or []
            for oc in ocs:
                oc_key = str(oc.get("oc") or "").strip()
                bq_val = info["ocs"].get(oc_key)
                if bq_val is not None:
                    oc["bultos_reales"] = bq_val
        else:
            if entradas_por_tienda.get(tienda, 0) > 1:
                # Múltiples casillas: match por fechacompromiso == dia_salida
                fecha = _dia_iso(lunes_iso, e.get("dia_salida", ""))
                if fecha:
                    info_fecha = info.get("por_fecha", {}).get(fecha)
                    if info_fecha and info_fecha.get("total"):
                        e["bultos_reales"] = info_fecha["total"]
            else:
                total = info.get("total")
                if total:
                    e["bultos_reales"] = total

    return sin_mapeo


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/auth/login")
async def login(body: dict):
    user = authenticate_user(body.get("username", ""), body.get("password", ""))
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = create_token(user)
    perms = ROLES.get(user["role"], {})
    return {
        "token":  token,
        "role":   user["role"],
        "nombre": user.get("nombre", user["username"]),
        "tabs":   perms.get("tabs", []),
        "edit":   perms.get("edit", False),
        "costos": perms.get("costos", False),
    }


@app.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    perms = ROLES.get(user.get("role"), {})
    return {
        "id":     user.get("sub"),
        "usr":    user.get("usr"),
        "role":   user.get("role"),
        "nombre": user.get("nombre"),
        "tabs":   perms.get("tabs", []),
        "edit":   perms.get("edit", False),
        "costos": perms.get("costos", False),
    }


# ── Usuarios (solo admin) ─────────────────────────────────────────────────────

@app.get("/users")
async def list_users(_: dict = Depends(require_admin)):
    return {"users": get_all_users()}


@app.post("/users")
async def add_user(body: dict, _: dict = Depends(require_admin)):
    try:
        user = create_user(
            body["username"], body["password"],
            body["role"],     body.get("nombre", body["username"])
        )
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/users/{user_id}")
async def edit_user(user_id: str, body: dict, _: dict = Depends(require_admin)):
    try:
        return update_user(user_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/users/{user_id}")
async def remove_user(user_id: str, admin: dict = Depends(require_admin)):
    try:
        delete_user(user_id, admin.get("sub", ""))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Estimador ────────────────────────────────────────────────────────────────

@app.post("/estimar")
async def estimar(
    file: UploadFile = File(...),
    tipo: str = Form(default="tienda_propia"),
    _: dict = Depends(get_current_user),
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


@app.post("/estimar/multi-archivos")
async def estimar_multi_archivos(
    files: list[UploadFile] = File(...),
    _: dict = Depends(get_current_user),
):
    if not files:
        raise HTTPException(status_code=400, detail="No se recibieron archivos")
    dfs = []
    for f in files:
        if not f.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail=f"'{f.filename}' debe ser .xlsx o .xls")
        content = await f.read()
        try:
            df = pd.read_excel(io.BytesIO(content), dtype={"Código producto": str})
            df = df.where(pd.notnull(df), None)
            dfs.append(df)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error leyendo '{f.filename}': {e}")
    try:
        combined = pd.concat(dfs, ignore_index=True)
        resultado = estimar_multi_tienda(df=combined)
        return JSONResponse(content=resultado)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/estimar/excel")
async def estimar_excel(
    file: UploadFile = File(...),
    tipo: str = Form(default="tienda_propia"),
    _: dict = Depends(get_current_user),
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


# ── Despachos ────────────────────────────────────────────────────────────────

@app.get("/despachos")
async def despachos(
    desde: str = Query(default=None),
    hasta: str = Query(default=None),
    _: dict = Depends(get_current_user),
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


# ── Programación ─────────────────────────────────────────────────────────────

@app.get("/programacion/resolver_tienda")
async def get_resolver_tienda(
    nombre: str = Query(...),
    _: dict = Depends(get_current_user),
):
    try:
        return {"tienda": resolver_tienda(nombre)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion")
async def get_programacion(_: dict = Depends(get_current_user)):
    try:
        return JSONResponse(content={"schedule": cargar_schedule_base()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion/semana")
async def get_programacion_semana(
    lunes: str = Query(...),
    _: dict = Depends(get_current_user),
):
    try:
        schedule    = obtener_semana(lunes)
        sin_mapeo   = _enriquecer_bultos_reales(schedule, lunes)
        _enriquecer_ocs(schedule)
        _enriquecer_costos(schedule)
        return JSONResponse(content={
            "schedule":  schedule,
            "lunes":     lunes,
            "ordenes":   obtener_ordenes(lunes),
            "sin_mapeo": sin_mapeo,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/programacion/orden")
async def post_programacion_orden(body: dict, _: dict = Depends(require_edit)):
    try:
        guardar_orden(body["lunes"], body["dia_vista"], body["tiendas"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/programacion/override")
async def post_programacion_override(body: dict, _: dict = Depends(require_edit)):
    try:
        guardar_override(body["lunes"], body["tienda"], body["cambios"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/programacion/override")
async def delete_programacion_override(
    lunes: str = Query(...),
    tienda: str = Query(...),
    _: dict = Depends(require_edit),
):
    try:
        eliminar_override(lunes, tienda)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/programacion/extra")
async def post_programacion_extra(body: dict, _: dict = Depends(require_edit)):
    try:
        agregar_extra(body["lunes"], body["entrada"])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/programacion/extra")
async def delete_programacion_extra(
    lunes: str = Query(...),
    id: str = Query(...),
    _: dict = Depends(require_edit),
):
    try:
        eliminar_extra(lunes, id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bultos-reales/clientes")
async def get_bultos_clientes(
    lunes: str = Query(...),
    _: dict = Depends(require_admin),
):
    """Muestra clientes BQ para la semana, fuente usada y estado de las tablas."""
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    try:
        invalidar_cache(lunes)  # fuerza re-query para mostrar datos frescos
        datos     = consultar_bultos_reales(lunes)
        sin_mapeo = datos.get("_sin_mapeo", [])
        fuente    = datos.get("_fuente", "?")
        tiendas   = {k: {"total": v["total"], "ocs": len(v["ocs"])}
                     for k, v in datos.items() if not k.startswith("_")}
        tablas    = estado_tablas()
        tiendas_schedule = sorted({e["tienda"] for e in cargar_schedule_base() if e.get("tienda")})
        return {
            "tiendas":          tiendas,
            "sin_mapeo":        sin_mapeo,
            "mapeo_actual":     MAPEO_CLIENTES,
            "fuente":           fuente,
            "tablas":           tablas,
            "tiendas_schedule": tiendas_schedule,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/mapeo-clientes")
async def guardar_mapeo(body: dict, _: dict = Depends(require_admin)):
    nom = (body.get("nom_cliente") or "").strip()
    tienda = (body.get("tienda") or "").strip()
    if not nom or not tienda:
        raise HTTPException(status_code=400, detail="nom_cliente y tienda son requeridos")
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    guardar_mapeo_cliente(nom, tienda)
    return {"ok": True, "nom_cliente": nom, "tienda": tienda}


@app.post("/bultos-reales/cache/invalidar")
async def invalidar_cache_bultos(
    lunes: str | None = Query(None),
    _: dict = Depends(require_admin),
):
    """Limpia la cache de bultos reales para forzar re-query a BQ."""
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    invalidar_cache(lunes)
    return {"ok": True, "lunes": lunes or "todos"}


@app.get("/admin/tablas-estado")
async def get_tablas_estado(_: dict = Depends(require_admin)):
    """Estado (fecha_min, fecha_max, total) de base_embalaje y documento_salida."""
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    try:
        return estado_tablas()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/rebuild-base-embalaje")
async def post_rebuild_base_embalaje(_: dict = Depends(require_admin)):
    """
    Reconstruye base_embalaje completa desde documento_salida + log_embalaje.
    Puede tardar 1-2 minutos. Requiere BigQuery Data Editor en sandbox.
    """
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    try:
        resultado = reconstruir_base_embalaje()
        invalidar_cache()
        return {"ok": True, **resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cron/rebuild-base-embalaje")
async def cron_rebuild_base_embalaje(x_cron_secret: str = Header(default="")):
    """
    Endpoint para Cloud Scheduler. Protegido por header X-Cron-Secret.
    Configurar en Cloud Run: CRON_SECRET=<valor aleatorio>.
    Configurar en Cloud Scheduler: header X-Cron-Secret: <mismo valor>.

    Schedule sugerido: 3 veces al día (mismo horario que documento_salida
    y log_embalaje): 07:30, 12:30, 18:00 hora Chile (UTC-3 / UTC-4 según DST).
    """
    if not _CRON_SECRET or x_cron_secret != _CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not _BQ_DISPONIBLE:
        raise HTTPException(status_code=503, detail="BQ no disponible")
    try:
        resultado = reconstruir_base_embalaje()
        invalidar_cache()
        return {"ok": True, "trigger": "cron", **resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/programacion/export")
async def export_programacion(
    lunes: str = Query(...),
    _: dict = Depends(get_current_user),
):
    try:
        data = obtener_semana(lunes)
        _enriquecer_bultos_reales(data, lunes)
        _enriquecer_ocs(data)
        _enriquecer_costos(data)
        # Aplanar ordenes_compra a string para el Excel
        for row in data:
            ocs = row.get("ordenes_compra") or []
            row["ocs_resumen"] = " | ".join(
                f"{oc.get('oc','')} Est:{oc.get('bultos_estimados','')} Real:{oc.get('bultos_reales','')}"
                for oc in ocs
            ) if ocs else ""

        cols = [
            "tienda", "dia_carga", "dia_salida", "hora_salida",
            "courier_preferencia", "tipo_camion",
            "dia_entrega_99min", "hora_entrega_99min",
            "dia_entrega_shipper", "hora_entrega_shipper",
            "bultos_estimados", "bultos_reales", "ocs_resumen",
            "costo_estimado", "ruta_nombre", "n_sharing", "override", "extra",
        ]
        df = pd.DataFrame(data).reindex(columns=cols)
        df.columns = [
            "Tienda", "Día Carga", "Día Salida", "Hora Salida",
            "Courier Preferencia", "Tipo Camión",
            "Entrega 99Min (día)", "Entrega 99Min (hora)",
            "Entrega Shipper (día)", "Entrega Shipper (hora)",
            "Bultos Estimados", "Bultos Reales", "Órdenes de Compra",
            "Costo Estimado ($)", "Ruta Compartida", "N° Tiendas Ruta", "Override", "Extra",
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
