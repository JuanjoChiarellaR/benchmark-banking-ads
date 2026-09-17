# Benchmark de pauta publicitaria banking/fintech (Meta + Google)

Proyecto de portafolio: benchmark de volumen y tipo de contenido publicitario
de bancos y fintechs en Meta Ad Library y Google Ads Transparency Center.
LinkedIn queda fuera de esta automatización (su `robots.txt` la bloquea
explícitamente).

## Fases

- **Fase 1 (Meta, implementada pero pausada):** resolución de identidad de
  los 13 `page_id` de Meta recolectados manualmente. Ver
  `src/meta/resolve_pages.py`. Pausada porque la cuenta de Facebook Developer
  usada para generar el token aún no completó la verificación de identidad
  que Meta exige para el Ad Library API (no es un bug del script).
- **Fase 2 (Google, piloto implementado):** extracción acotada de anuncios en
  Google Ads Transparency Center para las 3 entidades peruanas del piloto
  (Interbank, BCP, Yape). Ver `src/google/extract_ads.py`.
- **Fase 2 (Meta):** queda pendiente hasta reanudar Meta.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar META_ACCESS_TOKEN con tu token de Meta
```

`META_ACCESS_TOKEN` nunca se hardcodea ni se commitea (`.env` está en
`.gitignore`).

## Correr Fase 1

```bash
python src/meta/resolve_pages.py
```

Esto llama a `ads_archive` (Graph API v26.0) para cada uno de los 13
`page_id` en `config/meta_page_ids.py`, imprime una tabla
`page_id | country | page_name | ads_found` y la guarda en
`output/meta/page_resolution.csv`. No extrae anuncios completos ni toca
Google — se detiene ahí a la espera de confirmar qué `page_id` corresponde
a cada entidad.

## Correr Fase 2 (Google)

```bash
playwright install chromium   # una sola vez
python src/google/extract_ads.py
```

Para cada dominio en `config/google_domains.py` (`interbank.pe`,
`viabcp.com`, `yape.com.pe`):

1. Abre la búsqueda por dominio en Google Ads Transparency Center
   (`region=PE`) y aplica el filtro **"Last 30 days"** (nunca "Any time").
2. Agrupa los anuncios encontrados por **cuenta anunciante** — un dominio
   puede resolver a varias cuentas distintas (confirmado: `viabcp.com`
   agrupa 4 cuentas, incluyendo agencias de medios terceras y anuncios
   cruzados de otras marcas).
3. Por cada cuenta, captura los **10 anuncios más recientes** (piloto
   acotado a propósito, para validar el pipeline antes de correr algo más
   pesado sobre las 10 entidades restantes).
4. Si en cualquier momento detecta una señal de bloqueo/CAPTCHA, **se
   detiene y lo reporta explícitamente** — no asume que la página "no
   cargó" y sigue reintentando.

Guarda un JSON por entidad en `output/google/<entity>_google_ads.json` y
un resumen en consola al final de la corrida.

## Notas y limitaciones conocidas de las fuentes

- **Meta Ad Library API:** para anuncios comerciales normales (no políticos,
  no servidos en la UE), los campos de gasto/impresiones/audiencia estimada
  (`spend`, `impressions`, `estimated_audience_size`, `currency`, etc.) casi
  siempre vienen vacíos — están documentados como disponibles solo para
  `POLITICAL_AND_ISSUE_ADS`. Es una limitación conocida de la fuente, no un
  error del script.
- **Google Ads Transparency Center:** es una SPA (Angular) sin API pública;
  la extracción usa Playwright. Se verificó
  `https://adstransparency.google.com/robots.txt` y devuelve 404 (no publica
  reglas propias de crawling en ese subdominio); aun así se aplica
  rate-limiting conservador entre acciones del navegador. El filtro de fecha
  no se puede aplicar por query param directo (`preset-date` en la URL no
  tiene efecto si se navega ahí de entrada) — hay que operar el dropdown de
  la UI. El texto del anuncio (`ad_text_raw`) es **best-effort**: vive en un
  iframe de ad-serving en vivo (`/adframe`) que a veces no termina de
  renderizar en automatización headless, y para anuncios de formato
  Image/Video directamente no hay texto (son solo visuales, es esperado).
  `first_shown` tampoco viene expuesto de forma consistente — Google solo
  garantiza `last_shown` para anuncios que siguen activos.
