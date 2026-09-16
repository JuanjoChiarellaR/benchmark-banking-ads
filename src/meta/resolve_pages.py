"""FASE 1: resolucion de identidad de los 13 page_id de Meta Ad Library.

Llama a ads_archive para cada page_id con un limite bajo de anuncios,
extrae page_name tal cual lo devuelve la API (sin adivinar nada), imprime
una tabla page_id -> country -> page_name y la guarda en CSV.

No hace ninguna extraccion completa de anuncios (eso es Fase 2, bloqueada
hasta confirmar el mapeo de entidades resultante de esta corrida).
"""

import csv
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from config.meta_page_ids import META_PAGE_IDS
from src.meta.client import BETWEEN_CALLS_SECONDS, MetaAPIError, call_ads_archive

OUTPUT_PATH = PROJECT_ROOT / "output" / "meta" / "page_resolution.csv"

# ad_active_status=ALL (no ACTIVE) solo para esta fase de resolucion de
# identidad: maximiza la chance de encontrar al menos un anuncio con
# page_name aunque el page_id no tenga pauta activa en este momento.
# Fase 2 si respeta ACTIVE estrictamente, porque ahi el objetivo es medir
# pauta vigente.
RESOLUTION_AD_STATUS = "ALL"
RESOLUTION_LIMIT = 3


def resolve_page(page_id: str, country: str) -> dict:
    params = {
        "search_page_ids": f'["{page_id}"]',
        "ad_reached_countries": f'["{country}"]',
        "ad_active_status": RESOLUTION_AD_STATUS,
        "fields": "page_name,page_id,ad_delivery_start_time",
        "limit": RESOLUTION_LIMIT,
    }
    try:
        data = call_ads_archive(params)
    except MetaAPIError as exc:
        return {
            "page_id": page_id,
            "country": country,
            "page_name": "ERROR",
            "ads_found": False,
            "note": str(exc),
        }

    ads = data.get("data", [])
    if not ads:
        return {
            "page_id": page_id,
            "country": country,
            "page_name": "NOT_RESOLVED",
            "ads_found": False,
            "note": f"0 anuncios encontrados (ad_active_status={RESOLUTION_AD_STATUS})",
        }

    page_name = ads[0].get("page_name", "NOT_RESOLVED")
    return {
        "page_id": page_id,
        "country": country,
        "page_name": page_name,
        "ads_found": True,
        "note": f"{len(ads)} anuncio(s) encontrados",
    }


def main() -> None:
    results = []
    total = len(META_PAGE_IDS)
    for i, entry in enumerate(META_PAGE_IDS):
        print(
            f"[{i + 1}/{total}] Resolviendo page_id={entry['page_id']} "
            f"(country={entry['country']})..."
        )
        results.append(resolve_page(entry["page_id"], entry["country"]))
        if i < total - 1:
            time.sleep(BETWEEN_CALLS_SECONDS)

    print("\n" + "=" * 90)
    print(f"{'page_id':<20} {'country':<8} {'page_name':<35} {'ads_found':<10}")
    print("-" * 90)
    for r in results:
        print(
            f"{r['page_id']:<20} {r['country']:<8} {r['page_name']:<35} "
            f"{str(r['ads_found']):<10}"
        )
    print("=" * 90)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["page_id", "country", "page_name", "ads_found", "note"]
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResultado guardado en {OUTPUT_PATH}")
    not_resolved = [r for r in results if not r["ads_found"]]
    if not_resolved:
        print(
            f"\n{len(not_resolved)} page_id no se pudieron resolver "
            "(revisar columna 'note' en el CSV)."
        )
    print(
        "\nFASE 1 completa. Confirma cuales page_id (country=PE) corresponden a "
        "Interbank, BCP y Yape antes de avanzar a Fase 2."
    )


if __name__ == "__main__":
    main()
