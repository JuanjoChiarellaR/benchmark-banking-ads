# Benchmark de pauta publicitaria banking/fintech (Meta + Google)

Proyecto de portafolio: benchmark de volumen y tipo de contenido publicitario
de bancos y fintechs en Meta Ad Library y Google Ads Transparency Center.
LinkedIn queda fuera de esta automatización (su `robots.txt` la bloquea
explícitamente).

## Fases

- **Fase 1 (implementada):** resolución de identidad de los 13 `page_id` de
  Meta recolectados manualmente. Ver `src/meta/resolve_pages.py`.
- **Fase 2 (pendiente):** extracción completa de anuncios (Meta + Google) para
  el piloto de 3 entidades peruanas (Interbank, BCP, Yape), una vez confirmado
  el mapeo de la Fase 1.

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

## Notas y limitaciones conocidas de las fuentes

- **Meta Ad Library API:** para anuncios comerciales normales (no políticos,
  no servidos en la UE), los campos de gasto/impresiones/audiencia estimada
  (`spend`, `impressions`, `estimated_audience_size`, `currency`, etc.) casi
  siempre vienen vacíos — están documentados como disponibles solo para
  `POLITICAL_AND_ISSUE_ADS`. Es una limitación conocida de la fuente, no un
  error del script.
- **Google Ads Transparency Center:** es una SPA sin API pública; la
  extracción de Fase 2 requiere Playwright. Se verificó
  `https://adstransparency.google.com/robots.txt` y devuelve 404 (no publica
  reglas propias de crawling en ese subdominio); aun así se aplica
  rate-limiting conservador entre acciones del navegador.
