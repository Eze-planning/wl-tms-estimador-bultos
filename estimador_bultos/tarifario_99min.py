"""
tarifario_99min.py
==================
Cálculo de costos de envío 99 Minutos para reposiciones Wild Lama.

Dimensiones caja: 0.50 (alto) × 0.45 (largo) × 0.35 (ancho) m
Orientación óptima: lado de 45 cm hacia arriba, base 3×2, 3 capas → 18 cajas/pallet, 1.47 m
Pallet: 1.20 × 1.00 m, máximo 1.60 m de altura (base pallet 0.12 m)
Peso volumétrico = volumen total palletizado × 250
Costo = Primera Milla + Costo Fijo + Flete Variable (tramos marginales)
"""

import math
from rapidfuzz import process, fuzz

# ---------------------------------------------------------------------------
# Configuración de palletizado
# ---------------------------------------------------------------------------
CAJA_ALTO   = 0.45   # m — dimensión que va hacia arriba (largo de la caja)
CAJA_BASE_1 = 0.35   # m — a lo largo del pallet (1.20m): 3 caben exactas
CAJA_BASE_2 = 0.50   # m — a lo ancho del pallet (1.00m): 2 caben exactas
PALLET_L    = 1.20   # m
PALLET_W    = 1.00   # m
PALLET_BASE = 0.12   # m
ALTURA_MAX  = 1.60   # m

CAJAS_POR_CAPA   = math.floor(PALLET_L / CAJA_BASE_1) * math.floor(PALLET_W / CAJA_BASE_2)  # 6
CAPAS_POR_PALLET = math.floor((ALTURA_MAX - PALLET_BASE) / CAJA_ALTO)                        # 3
CAJAS_POR_PALLET = CAJAS_POR_CAPA * CAPAS_POR_PALLET                                         # 18

INSTRUCCION_PALLETIZADO = (
    f"Caja con el lado de {int(CAJA_ALTO*100)} cm hacia arriba. "
    f"{math.floor(PALLET_L/CAJA_BASE_1)} cajas de frente × "
    f"{math.floor(PALLET_W/CAJA_BASE_2)} cajas de fondo, "
    f"{CAPAS_POR_PALLET} capas de alto. "
    f"{CAJAS_POR_PALLET} cajas por pallet, {CAPAS_POR_PALLET * CAJA_ALTO + PALLET_BASE:.2f} m de altura."
)

# ---------------------------------------------------------------------------
# Primera milla desde Santiago (rangos de peso volumétrico en kg)
# ---------------------------------------------------------------------------
PRIMERA_MILLA = [
    (100,  38500),
    (200,  44000),
    (1000, 49500),
    (2000, 71500),
    (3000, 93500),
]

# ---------------------------------------------------------------------------
# Tarifas por destino
# fijo     = costo fijo tramo (10,15] — base para envíos > 15 kg
# t15_50 … t1000_plus = tarifa marginal por kg en cada tramo
# ---------------------------------------------------------------------------
TARIFAS = {
    "ANTOFAGASTA":    {"fijo": 11284.705882, "t15_50": 591.411765, "t50_100": 472.352941, "t100_200": 443.882353, "t200_500": 399.882353, "t500_1000": 367.529412, "t1000_plus": 359.764706},
    "COQUIMBO":       {"fijo":  9608.885,    "t15_50": 512.655,    "t50_100": 417.40875,  "t100_200": 326.37,     "t200_500": 312.35875,  "t500_1000": 298.3475,   "t1000_plus": 263.34},
    "VIÑA DEL MAR":   {"fijo":  7984.06125,  "t15_50": 495.8525,   "t50_100": 394.99625,  "t100_200": 308.15125,  "t200_500": 296.945,    "t500_1000": 284.35,     "t1000_plus": 252.13375},
    "SANTIAGO":       {"fijo":  6205.155,    "t15_50": 403.41125,  "t50_100": 322.1625,   "t100_200": 252.13375,  "t200_500": 240.9275,   "t500_1000": 235.3175,   "t1000_plus": 225.51375},
    "PICHILEMU":      {"fijo": 12437.68625,  "t15_50": 957.8525,   "t50_100": 764.87125,  "t100_200": 656.02625,  "t200_500": 609.07,     "t500_1000": 571.725,    "t1000_plus": 534.00875},
    "TALCA":          {"fijo":  7056.5,      "t15_50": 302.5,      "t50_100": 271.7,      "t100_200": 261.25,     "t200_500": 240.35,     "t500_1000": 225.72,     "t1000_plus": 215.27},
    "CURICO":         {"fijo":  7056.5,      "t15_50": 302.5,      "t50_100": 271.7,      "t100_200": 261.25,     "t200_500": 240.35,     "t500_1000": 225.72,     "t1000_plus": 215.27},
    "CHILLAN":        {"fijo":  7056.5,      "t15_50": 302.5,      "t50_100": 271.7,      "t100_200": 261.25,     "t200_500": 240.35,     "t500_1000": 225.72,     "t1000_plus": 215.27},
    "CONCEPCION":     {"fijo":  7056.225,    "t15_50": 302.5,      "t50_100": 271.7,      "t100_200": 261.25,     "t200_500": 240.35,     "t500_1000": 225.72,     "t1000_plus": 215.27},
    "LOS ANGELES":    {"fijo":  7526.64,     "t15_50": 324.5,      "t50_100": 498.666667, "t100_200": 440.0,      "t200_500": 308.0,      "t500_1000": 222.933333, "t1000_plus": 222.933333},
    "TEMUCO":         {"fijo":  9405.0,      "t15_50": 570.738667, "t50_100": 570.738667, "t100_200": 455.693333, "t200_500": 355.593333, "t500_1000": 340.648,    "t1000_plus": 324.221333},
    "PUCON":          {"fijo": 10505.0,      "t15_50": 996.875,    "t50_100": 996.875,    "t100_200": 797.5,      "t200_500": 680.625,    "t500_1000": 631.125,    "t1000_plus": 591.25},
    "VALDIVIA":       {"fijo": 12214.125,    "t15_50": 640.75,     "t50_100": 640.75,     "t100_200": 511.5,      "t200_500": 479.875,    "t500_1000": 433.125,    "t1000_plus": 397.375},
    "OSORNO":         {"fijo": 12214.125,    "t15_50": 640.75,     "t50_100": 640.75,     "t100_200": 511.5,      "t200_500": 479.875,    "t500_1000": 433.125,    "t1000_plus": 397.375},
    "PUERTO MONTT":   {"fijo": 12214.2075,   "t15_50": 640.13125,  "t50_100": 511.26625,  "t100_200": 480.43875,  "t200_500": 432.8225,   "t500_1000": 397.80125,  "t1000_plus": 389.4},
    "PUERTO VARAS":   {"fijo": 12214.2075,   "t15_50": 640.13125,  "t50_100": 511.26625,  "t100_200": 480.43875,  "t200_500": 432.8225,   "t500_1000": 397.80125,  "t1000_plus": 389.4},
    "CASTRO":         {"fijo": 13673.0,      "t15_50": 684.2,      "t50_100": 665.5,      "t100_200": 548.9,      "t200_500": 488.4,      "t500_1000": 438.9,      "t1000_plus": 415.8},
    "ANCUD":          {"fijo": 13673.0,      "t15_50": 684.2,      "t50_100": 665.5,      "t100_200": 548.9,      "t200_500": 488.4,      "t500_1000": 438.9,      "t1000_plus": 415.8},
    "COYHAIQUE":      {"fijo": 13673.0,      "t15_50": 684.2,      "t50_100": 665.5,      "t100_200": 548.9,      "t200_500": 488.4,      "t500_1000": 438.9,      "t1000_plus": 415.8},
    "AYSEN":          {"fijo": 22519.2,      "t15_50": 852.5,      "t50_100": 819.5,      "t100_200": 797.5,      "t200_500": 787.6,      "t500_1000": 775.5,      "t1000_plus": 754.6},
    "PUNTA ARENAS":   {"fijo": 22519.2,      "t15_50": 852.5,      "t50_100": 819.5,      "t100_200": 797.5,      "t200_500": 787.6,      "t500_1000": 775.5,      "t1000_plus": 754.6},
    "PUERTO NATALES": {"fijo": 53694.612972, "t15_50": 1707.2,     "t50_100": 1342.0,     "t100_200": 1265.0,     "t200_500": 1265.0,     "t500_1000": 1166.0,     "t1000_plus": 1111.0},
}

# ---------------------------------------------------------------------------
# Mapeo tienda → destino tarifario
# ---------------------------------------------------------------------------
TIENDA_DESTINO = {
    "Tienda Antofagasta":       "ANTOFAGASTA",
    "Tienda Chicureo":          "SANTIAGO",
    "Tienda Chillan":           "CHILLAN",
    "Tienda Costanera":         "SANTIAGO",
    "Tienda Coyhaique":         "COYHAIQUE",
    "Tienda La Serena":         "COQUIMBO",
    "Tienda Laguna":            "VIÑA DEL MAR",
    "Tienda Los Ángeles":       "LOS ANGELES",
    "Tienda Los Angeles":       "LOS ANGELES",
    "Tienda Mall Curicó":       "CURICO",
    "Tienda Mall Curico":       "CURICO",
    "Tienda Marina":            "VIÑA DEL MAR",
    "Tienda Concon":            "VIÑA DEL MAR",
    "Tienda Osorno":            "OSORNO",
    "Tienda Mall Cenco Osorno": "OSORNO",
    "Tienda Parque Arauco":     "SANTIAGO",
    "Tienda Mall Parque Arauco":"SANTIAGO",
    "Tienda Pichilemu":         "PICHILEMU",
    "Tienda Pucon":             "PUCON",
    "Tienda Puerto Montt":      "PUERTO MONTT",
    "Tienda Puerto Varas":      "PUERTO VARAS",
    "Tienda San Fernando":      "PICHILEMU",
    "Tienda Mall San Fernando": "PICHILEMU",
    "TIenda Talca":             "TALCA",
    "Tienda Talca":             "TALCA",
    "Tienda Temuco":            "TEMUCO",
    "Tienda Trebol":            "CONCEPCION",
    "Tienda Mallplaza Trebol":  "CONCEPCION",
    "Tienda Vespucio":          "SANTIAGO",
    "Tienda Vitacura":          "SANTIAGO",
    "Tienda Nueva Costanera":   "SANTIAGO",
    "Ecommerce":                "SANTIAGO",
}

_TIENDAS_LISTA = list(TIENDA_DESTINO.keys())


def _resolver_destino(tienda: str) -> str | None:
    tienda = tienda.strip()
    if tienda in TIENDA_DESTINO:
        return TIENDA_DESTINO[tienda]
    result = process.extractOne(tienda, _TIENDAS_LISTA, scorer=fuzz.WRatio, score_cutoff=75)
    if result:
        return TIENDA_DESTINO[result[0]]
    return None


def _primera_milla(peso_vol: float) -> float:
    for limite, costo in PRIMERA_MILLA:
        if peso_vol <= limite:
            return costo
    return PRIMERA_MILLA[-1][1]


def _flete_variable(peso_vol: float, tarifa: dict) -> float:
    if peso_vol <= 15:
        return 0
    if peso_vol <= 50:
        rate = tarifa["t15_50"]
    elif peso_vol <= 100:
        rate = tarifa["t50_100"]
    elif peso_vol <= 200:
        rate = tarifa["t100_200"]
    elif peso_vol <= 500:
        rate = tarifa["t200_500"]
    elif peso_vol <= 1000:
        rate = tarifa["t500_1000"]
    else:
        rate = tarifa["t1000_plus"]
    return (peso_vol - 15) * rate


def _calcular_pallets(n_bultos: int) -> dict:
    """Devuelve distribución de pallets y peso volumétrico total."""
    n_pallets    = math.ceil(n_bultos / CAJAS_POR_PALLET)
    resto        = n_bultos % CAJAS_POR_PALLET or CAJAS_POR_PALLET
    capas_ultimo = math.ceil(resto / CAJAS_POR_CAPA)
    altura_lleno = CAPAS_POR_PALLET * CAJA_ALTO + PALLET_BASE
    altura_ultimo = capas_ultimo * CAJA_ALTO + PALLET_BASE
    pallets_llenos = n_pallets - 1 if resto != CAJAS_POR_PALLET else n_pallets
    vol = (pallets_llenos * PALLET_L * PALLET_W * altura_lleno
           + (0 if pallets_llenos == n_pallets else PALLET_L * PALLET_W * altura_ultimo))
    return {
        "n_pallets":   n_pallets,
        "vol_m3":      round(vol, 4),
        "peso_vol_kg": round(vol * 250, 1),
    }


def calcular_costo_99min(n_bultos: int, tienda: str) -> dict:
    """
    Retorna desglose de costo 99 Minutos para n_bultos hacia tienda.
    Devuelve None en costo_total si la tienda no tiene destino mapeado.
    """
    pallet_info = _calcular_pallets(n_bultos)
    peso_vol    = pallet_info["peso_vol_kg"]
    destino     = _resolver_destino(tienda)

    if destino is None or destino not in TARIFAS:
        return {
            "destino":        destino,
            "n_pallets":      pallet_info["n_pallets"],
            "vol_m3":         pallet_info["vol_m3"],
            "peso_vol_kg":    peso_vol,
            "primera_milla":  None,
            "costo_fijo":     None,
            "costo_variable": None,
            "costo_total":    None,
            "instruccion":    INSTRUCCION_PALLETIZADO,
            "advertencia":    f"Sin tarifa para '{tienda}'",
        }

    tarifa         = TARIFAS[destino]
    primera_milla  = _primera_milla(peso_vol)
    costo_fijo     = tarifa["fijo"]
    costo_variable = _flete_variable(peso_vol, tarifa)
    costo_total    = primera_milla + costo_fijo + costo_variable

    return {
        "destino":        destino,
        "n_pallets":      pallet_info["n_pallets"],
        "vol_m3":         pallet_info["vol_m3"],
        "peso_vol_kg":    peso_vol,
        "primera_milla":  round(primera_milla),
        "costo_fijo":     round(costo_fijo),
        "costo_variable": round(costo_variable),
        "costo_total":    round(costo_total),
        "instruccion":    INSTRUCCION_PALLETIZADO,
        "advertencia":    None,
    }
