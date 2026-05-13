"""
tarifario_shipper.py
====================
Cálculo de costos Shipper Logistic para reposiciones Wild Lama.

Categorías de camión:
  L      = ≤ 150 bultos
  XL     = 151–500 bultos
  Rampla = > 500 bultos (solo Grandes Tiendas: Falabella, Paris, Ripley) — $220.000 fijo

Pioneta: $40.000 adicional según destino.
"""

from rapidfuzz import process, fuzz

RAMPLA_COSTO  = 220_000
PIONETA_COSTO =  40_000

# ---------------------------------------------------------------------------
# Tarifas directas por destino
# pioneta=True indica que ese destino/ruta incluye pioneta
# ---------------------------------------------------------------------------
TARIFAS = {
    "ANTOFAGASTA":    {"L": 1_200_000, "XL": 1_700_000, "pioneta": False},
    "LA SERENA":      {"L":   550_000, "XL":   650_000, "pioneta": False},
    "LAGUNA":         {"L":   280_000, "XL":   280_000, "pioneta": False},
    "MARINA":         {"L":   280_000, "XL":   280_000, "pioneta": False},
    "ECOMMERCE":      {"L":   130_000, "XL":   130_000, "pioneta": False},
    "PARQUE ARAUCO":  {"L":   130_000, "XL":   130_000, "pioneta": True},
    "COSTANERA":      {"L":   130_000, "XL":   130_000, "pioneta": True},
    "VITACURA":       {"L":   130_000, "XL":   130_000, "pioneta": False},
    "CHICUREO":       {"L":   130_000, "XL":   130_000, "pioneta": False},
    "VESPUCIO":       {"L":   130_000, "XL":   130_000, "pioneta": False},
    "GRANDES TIENDAS":{"L":   220_000, "XL":   220_000, "pioneta": False},
    "MAYORISTAS":     {"L":   150_000, "XL":   150_000, "pioneta": False},
    "PICHILEMU":      {"L":   280_000, "XL":   280_000, "pioneta": False},
    "SAN FERNANDO":   {"L":   280_000, "XL":   280_000, "pioneta": False},
    "CURICO":         {"L":   300_000, "XL":   400_000, "pioneta": False},
    "CHILLAN":        {"L":   300_000, "XL":   400_000, "pioneta": True},
    "TALCA":          {"L":   450_000, "XL":   500_000, "pioneta": False},
    "CONCEPCION":     {"L":   700_000, "XL":   900_000, "pioneta": False},
    "LOS ANGELES":    {"L":   850_000, "XL": 1_150_000, "pioneta": False},
    "TEMUCO":         {"L": 1_000_000, "XL": 1_200_000, "pioneta": False},
    "PUCON":          {"L": 1_100_000, "XL": 1_400_000, "pioneta": False},
    "PUERTO MONTT":   {"L": 1_600_000, "XL": 2_200_000, "pioneta": False},
    "PUERTO VARAS":   {"L": 1_600_000, "XL": 2_200_000, "pioneta": False},
    "OSORNO":         {"L": 1_600_000, "XL": 2_200_000, "pioneta": False},
    "COYHAIQUE":      {"L": 2_200_000, "XL": 2_600_000, "pioneta": False},
}

# ---------------------------------------------------------------------------
# Rutas combinadas — costo del camión dividido entre todas las tiendas de la ruta
# ---------------------------------------------------------------------------
RUTAS = [
    {
        "nombre":   "Santiago combinado",
        "destinos": ["ECOMMERCE", "PARQUE ARAUCO", "COSTANERA", "VITACURA", "CHICUREO", "VESPUCIO"],
        "L":   180_000, "XL":   180_000, "pioneta": True,
    },
    {
        "nombre":   "Pichilemu + San Fernando",
        "destinos": ["PICHILEMU", "SAN FERNANDO"],
        "L":   400_000, "XL":   400_000, "pioneta": False,
    },
    {
        "nombre":   "Sur: Curicó-Talca-Chillán-Trébol-LA",
        "destinos": ["CURICO", "TALCA", "CHILLAN", "CONCEPCION", "LOS ANGELES"],
        "L":   850_000, "XL": 1_150_000, "pioneta": True,
    },
    {
        "nombre":   "Largo: Temuco-Pucón-PV-PM-Osorno",
        "destinos": ["TEMUCO", "PUCON", "PUERTO VARAS", "PUERTO MONTT", "OSORNO"],
        "L": 1_600_000, "XL": 2_200_000, "pioneta": True,
    },
    {
        "nombre":   "Largo + Coyhaique",
        "destinos": ["TEMUCO", "PUCON", "PUERTO VARAS", "PUERTO MONTT", "OSORNO", "COYHAIQUE"],
        "L": 2_000_000, "XL": 2_600_000, "pioneta": True,
    },
    {
        "nombre":   "Norte: Chicureo-Laguna-La Serena",
        "destinos": ["CHICUREO", "LAGUNA", "MARINA", "LA SERENA"],
        "L":   600_000, "XL":   750_000, "pioneta": False,
    },
    {
        "nombre":   "Norte + Antofagasta",
        "destinos": ["CHICUREO", "LAGUNA", "MARINA", "LA SERENA", "ANTOFAGASTA"],
        "L": 1_200_000, "XL": 1_700_000, "pioneta": False,
    },
]

# ---------------------------------------------------------------------------
# Grandes tiendas — destinos con opción Rampla para >500 bultos
# ---------------------------------------------------------------------------
GRANDES_TIENDAS = {"GRANDES TIENDAS"}

# ---------------------------------------------------------------------------
# Mapeo tienda → destino tarifario
# ---------------------------------------------------------------------------
TIENDA_DESTINO = {
    "Tienda Antofagasta":        "ANTOFAGASTA",
    "Tienda La Serena":          "LA SERENA",
    "Tienda Laguna":             "LAGUNA",
    "Tienda Marina":             "MARINA",
    "Tienda Concon":             "MARINA",
    "Ecommerce":                 "ECOMMERCE",
    "Tienda Parque Arauco":      "PARQUE ARAUCO",
    "Tienda Mall Parque Arauco": "PARQUE ARAUCO",
    "Tienda Costanera":          "COSTANERA",
    "Tienda Nueva Costanera":    "COSTANERA",
    "Tienda Vitacura":           "VITACURA",
    "Tienda Chicureo":           "CHICUREO",
    "Tienda Vespucio":           "VESPUCIO",
    "Tienda Pichilemu":          "PICHILEMU",
    "Tienda San Fernando":       "SAN FERNANDO",
    "Tienda Mall San Fernando":  "SAN FERNANDO",
    "Tienda Mall Curicó":        "CURICO",
    "Tienda Mall Curico":        "CURICO",
    "TIenda Talca":              "TALCA",
    "Tienda Talca":              "TALCA",
    "Tienda Chillan":            "CHILLAN",
    "Tienda Trebol":             "CONCEPCION",
    "Tienda Mallplaza Trebol":   "CONCEPCION",
    "Tienda Los Ángeles":        "LOS ANGELES",
    "Tienda Los Angeles":        "LOS ANGELES",
    "Tienda Temuco":             "TEMUCO",
    "Tienda Pucon":              "PUCON",
    "Tienda Puerto Montt":       "PUERTO MONTT",
    "Tienda Puerto Varas":       "PUERTO VARAS",
    "Tienda Osorno":             "OSORNO",
    "Tienda Mall Cenco Osorno":  "OSORNO",
    "Tienda Coyhaique":          "COYHAIQUE",
    "Paris":                     "GRANDES TIENDAS",
    "Ripley":                    "GRANDES TIENDAS",
    "Falabella":                 "GRANDES TIENDAS",
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


def _categoria_camion(n_bultos: int, es_grande_tienda: bool) -> str:
    if n_bultos <= 150:
        return "L"
    if n_bultos <= 500:
        return "XL"
    if es_grande_tienda:
        return "Rampla"
    return "XL"


def calcular_tabla_shipper(tienda: str) -> dict:
    """
    Devuelve una tabla comparativa L/XL con costo directo y rutas combinadas.
    Siempre muestra ambas columnas; quien planifica elige el camión según el
    total de bultos de la ruta completa.
    """
    destino = _resolver_destino(tienda)

    if destino is None or destino not in TARIFAS:
        return {
            "destino":     destino,
            "directo":     None,
            "rutas":       [],
            "advertencia": f"Sin tarifa para '{tienda}'",
        }

    tarifa    = TARIFAS[destino]
    es_grande = destino in GRANDES_TIENDAS

    directo = {
        "costo_L":     tarifa["L"],
        "costo_XL":    tarifa["XL"],
        "costo_rampla": RAMPLA_COSTO if es_grande else None,
        "pioneta":     PIONETA_COSTO if tarifa["pioneta"] else 0,
    }

    rutas = []
    for ruta in RUTAS:
        if destino not in ruta["destinos"]:
            continue
        n = len(ruta["destinos"])
        rutas.append({
            "nombre":        ruta["nombre"],
            "n_tiendas":     n,
            "costo_ruta_L":  ruta["L"],
            "costo_ruta_XL": ruta["XL"],
            "por_tienda_L":  round(ruta["L"] / n),
            "por_tienda_XL": round(ruta["XL"] / n),
            "pioneta":       PIONETA_COSTO if ruta["pioneta"] else 0,
        })

    return {
        "destino":     destino,
        "directo":     directo,
        "rutas":       rutas,
        "advertencia": None,
    }


def calcular_costo_shipper(n_bultos: int, tienda: str) -> dict:
    """Mantiene compatibilidad; internamente usa calcular_tabla_shipper."""
    return calcular_tabla_shipper(tienda)
