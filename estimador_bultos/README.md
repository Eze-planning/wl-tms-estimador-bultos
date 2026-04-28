# Estimador de Bultos — Wild Lama TMS

## Descripción
Aplicación web que estima la cantidad de bultos (cajas de despacho) 
para pedidos a tiendas propias, basándose en el histórico real de 
embalaje almacenado en BigQuery.

Parte del proyecto TMS de Wild Lama, orientado a optimizar rutas, 
visibilidad de pedidos y acceso ágil a reportes logísticos.

## Autor
Ezequiel Ortiz — Área de Planning & Logistics

## Tier
Tier 3 — Crítica (conecta a GCP/BigQuery)

## Estructura del proyecto
```
estimador_bultos/
├── app.py          # Backend FastAPI (puerto 8080)
├── modelo.py       # Lógica de estimación y conexión a BigQuery
├── index.html      # Frontend web
├── requirements.txt
└── .env.example    # Variables de entorno necesarias
valgreti_scraper/
└── valgreti_scraper.py  # Bot de descarga automática desde Valgreti
```
## Variables de entorno necesarias
Ver `.env.example`

## Cómo correr localmente
```bash
pip install -r requirements.txt
python app.py
```
Abrir `index.html` en el browser.

## Base de datos
- **Proyecto GCP:** prj-wlcl-p-data-share
- **Dataset:** sandbox
- **Tablas:**
  - `log_embalaje` — histórico de embalaje por caja
  - `documento_salida` — órdenes de despacho
  - `log_recepcion` — recepciones de mercadería
  - `dims.product_dim` — dimensión de productos (solo lectura)

## Scraper Valgreti
Descarga automática 3 veces al día (7:00, 12:00, 17:30) desde Valgreti 
hacia BigQuery. Requiere despliegue en Cloud Run.