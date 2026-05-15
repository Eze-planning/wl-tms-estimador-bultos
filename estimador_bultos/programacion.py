"""
programacion.py
===============
Programación semanal de despachos: schedule base desde Excel + overrides por semana.
"""
import os
import json
import unicodedata
import pandas as pd
from pathlib import Path

SCHEDULE_PATH = os.getenv(
    "SCHEDULE_PATH",
    r"G:\Unidades compartidas\2.- Wild Lama\Logistics & Planning\Warehouse Manager & Logistics (Ezequiel)\Warehouse\17. Claude\TMS\Programación\BBDD Programación.xlsx"
)
OVERRIDES_PATH = Path(__file__).parent / "overrides_programacion.json"


def _norm(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _find_col(cols, keywords):
    for kw in keywords:
        kw_n = _norm(kw)
        for c in cols:
            if kw_n in _norm(str(c)):
                return c
    return None


def _fmt_hora(v) -> str:
    if v is None:
        return ""
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return ""
    except Exception:
        pass
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    s = str(v).strip().replace("::", ":")
    parts = s.split(":")
    if len(parts) >= 2:
        return f"{parts[0].zfill(2)}:{parts[1][:2].zfill(2)}"
    return s


def cargar_schedule_base() -> list:
    df = pd.read_excel(SCHEDULE_PATH, sheet_name=0)
    df = df.where(pd.notnull(df), None)
    cols = list(df.columns)

    c_tienda  = _find_col(cols, ["tienda"])
    c_carga   = _find_col(cols, ["carga"])
    c_sal_dia = _find_col(cols, ["dia de salida", "salida"])
    c_sal_hr  = _find_col(cols, ["hora de salida", "hora sal"])
    c_99_dia  = _find_col(cols, ["entrega 99"])
    c_99_hr   = _find_col(cols, ["hora de entrega 99", "hora entrega 99"])
    c_99_lt   = _find_col(cols, ["lt 99"])
    c_sh_dia  = _find_col(cols, ["entrega shipper"])
    c_sh_hr   = _find_col(cols, ["hora de entrega shipper", "hora entrega ship"])
    c_sh_lt   = _find_col(cols, ["lt shipper"])

    schedule = []
    for _, row in df.iterrows():
        tienda = str(row.get(c_tienda) or "").strip()
        if not tienda:
            continue
        schedule.append({
            "tienda":               tienda,
            "dia_carga":            str(row.get(c_carga) or "").strip(),
            "dia_salida":           str(row.get(c_sal_dia) or "").strip(),
            "hora_salida":          _fmt_hora(row.get(c_sal_hr)),
            "dia_entrega_99min":    str(row.get(c_99_dia) or "").strip(),
            "hora_entrega_99min":   _fmt_hora(row.get(c_99_hr)),
            "lt_99min":             int(row.get(c_99_lt) or 0),
            "dia_entrega_shipper":  str(row.get(c_sh_dia) or "").strip(),
            "hora_entrega_shipper": _fmt_hora(row.get(c_sh_hr)),
            "lt_shipper":           int(row.get(c_sh_lt) or 0),
        })
    return schedule


def _load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_overrides(overrides: dict):
    with open(OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)


def obtener_semana(lunes_iso: str) -> list:
    """Devuelve la programación efectiva para la semana (base + overrides)."""
    base = cargar_schedule_base()
    week_ov = _load_overrides().get(lunes_iso, {})
    result = []
    for entry in base:
        e = dict(entry)
        if e["tienda"] in week_ov:
            e.update(week_ov[e["tienda"]])
            e["override"] = True
        else:
            e["override"] = False
        result.append(e)
    return result


def guardar_override(lunes_iso: str, tienda: str, cambios: dict):
    overrides = _load_overrides()
    if lunes_iso not in overrides:
        overrides[lunes_iso] = {}
    overrides[lunes_iso][tienda] = cambios
    _save_overrides(overrides)


def eliminar_override(lunes_iso: str, tienda: str):
    overrides = _load_overrides()
    if lunes_iso in overrides and tienda in overrides[lunes_iso]:
        del overrides[lunes_iso][tienda]
        if not overrides[lunes_iso]:
            del overrides[lunes_iso]
        _save_overrides(overrides)
