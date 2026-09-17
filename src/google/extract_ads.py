"""FASE 2 (Google): extractor del piloto Interbank/BCP/Yape en Google Ads
Transparency Center.

Piloto acotado (por indicacion explicita): filtro obligatorio "Last 30 days",
pero dentro de esa ventana solo se capturan los 10 anuncios mas recientes por
cuenta anunciante (un dominio puede resolver a varias cuentas anunciantes
distintas, y se capturan por separado).

Si en cualquier momento se detecta una senal de bloqueo/CAPTCHA, la corrida
de esa entidad se detiene y se reporta explicitamente -- nunca se asume que
la pagina "no cargo" y se sigue reintentando.

No descarga imagenes/videos de los creativos, solo texto y URLs de
referencia.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright

from config.google_domains import GOOGLE_DOMAINS
from src.google.browser import (
    USER_AGENT,
    accept_cookies_if_present,
    apply_last_30_days_filter,
    build_search_url,
    collect_creative_links,
    detect_block,
    extract_ad_text_from_adframe,
    group_by_advertiser,
    open_full_ads_grid,
    polite_wait,
    read_ads_count,
    safe_goto,
)

OUTPUT_DIR = PROJECT_ROOT / "output" / "google"
ADS_PER_ADVERTISER = 10
MAX_SCROLLS = 25
MIN_LINKS_TARGET = 60


def parse_creative_detail(page) -> dict:
    """Extrae los campos disponibles de la pagina de detalle de un anuncio.

    Se apoya en el texto plano de la pagina (via inner_text) en vez de
    clases CSS de Angular, porque esas clases (_ngcontent-XXX) cambian de
    hash entre cargas y no son un selector estable. No hay tag <h1>: el
    nombre del anunciante aparece como texto plano entre 'Ad details' y
    'The information about this ad'.
    """
    text = page.inner_text("body")

    def _search(pattern: str):
        match = re.search(pattern, text)
        return match.group(1).strip() if match else None

    # El texto/CTA real del anuncio no vive en el body principal, sino en un
    # iframe de ad-serving en vivo (ver extract_ad_text_from_adframe). Para
    # creativos de formato Image/Video no hay texto (son solo visuales).
    ad_text = extract_ad_text_from_adframe(page)

    return {
        "advertiser_name": _search(
            r"Ad details\n(.+?)\nThe information about this ad"
        ),
        "last_shown": _search(r"Last shown:\s*([A-Za-z]+ \d{1,2}, \d{4})"),
        "first_shown": _search(r"First shown:\s*([A-Za-z]+ \d{1,2}, \d{4})"),
        "format": _search(r"Format:\s*(\w+)"),
        "shown_in": _search(r"Shown in ([^\n]+)"),
        "variations": _search(r"(\d+ of \d+ variations)"),
        "ad_text_raw": ad_text,
    }


def extract_entity(page, entity: str, domain: str, region: str) -> dict:
    print(f"\n=== {entity} ({domain}, region={region}) ===")
    if not safe_goto(page, build_search_url(domain, region)):
        print("  ERROR DE RED: no se pudo cargar la busqueda por dominio tras varios intentos.")
        return {
            "entity": entity,
            "domain": domain,
            "region": region,
            "blocked": False,
            "network_error": True,
        }
    accept_cookies_if_present(page)
    page.wait_for_timeout(3000)

    block_reason = detect_block(page)
    if block_reason:
        print(f"  BLOQUEADO al abrir la busqueda por dominio: {block_reason}")
        return {
            "entity": entity,
            "domain": domain,
            "region": region,
            "blocked": True,
            "block_reason": block_reason,
        }

    open_full_ads_grid(page)
    block_reason = detect_block(page)
    if block_reason:
        print(f"  BLOQUEADO al expandir la grilla completa: {block_reason}")
        return {
            "entity": entity,
            "domain": domain,
            "region": region,
            "blocked": True,
            "block_reason": block_reason,
        }

    apply_last_30_days_filter(page)
    block_reason = detect_block(page)
    if block_reason:
        print(f"  BLOQUEADO al aplicar el filtro de fecha: {block_reason}")
        return {
            "entity": entity,
            "domain": domain,
            "region": region,
            "blocked": True,
            "block_reason": block_reason,
        }

    ads_count_label = read_ads_count(page)
    print(f"  Conteo reportado por el sitio (Last 30 days): {ads_count_label}")

    ordered_links = collect_creative_links(
        page, max_scrolls=MAX_SCROLLS, target_min_links=MIN_LINKS_TARGET
    )
    print(f"  Creative links unicos encontrados tras scroll: {len(ordered_links)}")

    block_reason = detect_block(page)
    if block_reason:
        print(f"  BLOQUEADO durante el scroll de la grilla: {block_reason}")
        return {
            "entity": entity,
            "domain": domain,
            "region": region,
            "blocked": True,
            "block_reason": block_reason,
        }

    groups = group_by_advertiser(ordered_links, limit_per_advertiser=ADS_PER_ADVERTISER)
    print(f"  Cuentas anunciantes distintas detectadas: {len(groups)}")

    advertiser_accounts = []
    for advertiser_id, ads in groups.items():
        account_ads = []
        for ad in ads:
            detail_url = f"https://adstransparency.google.com{ad['href']}"
            polite_wait()
            if not safe_goto(page, detail_url):
                print(
                    f"  ERROR DE RED al abrir detalle de {ad['creative_id']} -- se "
                    "salta este anuncio, no se aborta la corrida."
                )
                account_ads.append(
                    {
                        "advertiser_id": advertiser_id,
                        "creative_id": ad["creative_id"],
                        "detail_url": detail_url,
                        "network_error": True,
                    }
                )
                continue
            page.wait_for_timeout(3000)

            block_reason = detect_block(page)
            if block_reason:
                print(
                    f"  BLOQUEADO al abrir detalle de {ad['creative_id']}: {block_reason}"
                )
                return {
                    "entity": entity,
                    "domain": domain,
                    "region": region,
                    "blocked": True,
                    "block_reason": block_reason,
                    "partial_advertiser_accounts": advertiser_accounts,
                }

            fields = parse_creative_detail(page)
            account_ads.append(
                {
                    "advertiser_id": advertiser_id,
                    "creative_id": ad["creative_id"],
                    "detail_url": detail_url,
                    **fields,
                }
            )

        advertiser_name = account_ads[0]["advertiser_name"] if account_ads else None
        advertiser_accounts.append(
            {
                "advertiser_id": advertiser_id,
                "advertiser_name": advertiser_name,
                "ads_captured": len(account_ads),
                "ads": account_ads,
            }
        )

    return {
        "entity": entity,
        "domain": domain,
        "region": region,
        "blocked": False,
        "filter_applied": "Last 30 days",
        "ads_per_advertiser_cap": ADS_PER_ADVERTISER,
        "ads_count_reported_by_site": ads_count_label,
        "advertiser_accounts": advertiser_accounts,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        for cfg in GOOGLE_DOMAINS:
            result = extract_entity(page, cfg["entity"], cfg["domain"], cfg["region"])

            out_path = OUTPUT_DIR / f"{cfg['entity']}_google_ads.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"  Guardado en {out_path}")

            total_ads = sum(
                a["ads_captured"] for a in result.get("advertiser_accounts", [])
            )
            summary.append(
                {
                    "entity": cfg["entity"],
                    "domain": cfg["domain"],
                    "blocked": result.get("blocked", False),
                    "network_error": result.get("network_error", False),
                    "advertiser_accounts": len(result.get("advertiser_accounts", [])),
                    "ads_captured": total_ads,
                }
            )

            if result.get("blocked"):
                print(
                    f"  Entidad {cfg['entity']} detenida por bloqueo -- no continuo "
                    "automaticamente con las demas entidades sin que lo revisemos."
                )
                break

            polite_wait()

        browser.close()

    print("\n" + "=" * 70)
    print("RESUMEN DE LA CORRIDA")
    print("=" * 70)
    for row in summary:
        status = "BLOQUEADO" if row["blocked"] else ("ERROR_RED" if row["network_error"] else "OK")
        print(
            f"{row['entity']:<12} {status:<10} cuentas={row['advertiser_accounts']:<3} "
            f"ads={row['ads_captured']}"
        )
    print(
        "\nLimitaciones conocidas de este piloto:\n"
        "- 'first_shown' no siempre viene expuesto por Google para anuncios que "
        "siguen activos (solo 'last_shown').\n"
        "- 'variations' indica cuantas variantes tiene el creative pero no las "
        "enumera todas (queda para una siguiente iteracion).\n"
        "- 'ad_text_raw' es best-effort: para anuncios Image/Video no hay texto "
        "(son solo visuales, es esperado); para anuncios Text/Local a veces viene "
        "vacio porque el contenido se sirve desde un iframe de ad-serving en vivo "
        "que no siempre termina de renderizar en automatizacion headless.\n"
        "- solo se escanearon los primeros anuncios cargados via scroll, por lo "
        "que podria haber cuentas anunciantes adicionales no detectadas fuera de "
        "esa ventana."
    )


if __name__ == "__main__":
    main()
