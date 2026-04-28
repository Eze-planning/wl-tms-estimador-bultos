# Estimador de Bultos — Wild Lama

Estima la cantidad de bultos para pedidos futuros basándose en el histórico real de embalaje en BigQuery.

## Estructura
```
estimador_bultos/
├── modelo.py          ← lógica de estimación + conexión BigQuery
├── app.py             ← backend FastAPI
├── frontend/
│   └── index.html     ← web app
├── requirements.txt
├── .env.example
└── run.bat            ← arrancar en Windows
```

## Setup
1. Copiar `.env.example` a `.env` y completar
2. Poner `bq_service_account.json` en la carpeta
3. Correr `run.bat` (o `python app.py`)
4. Abrir `frontend/index.html` en el browser

## Lógica de fallback
SKU → Subclase → Clase → Sublínea → Línea → Global

## Endpoints
- `POST /estimar` → JSON con detalle y resumen
- `POST /estimar/excel` → descarga Excel con dos hojas
