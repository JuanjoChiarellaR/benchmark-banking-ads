"""Paso 1 (reconocimiento), segunda pasada: confirma si el filtro de fecha
se puede aplicar directo por query param, y busca cuantas cuentas
anunciantes distintas aparecen para interbank.pe al hacer scroll.

No es parte del pipeline final.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright

from src.google.browser import USER_AGENT, accept_cookies_if_present, detect_block

RECON_DIR = PROJECT_ROOT / "output" / "google" / "_recon"

TEST_URL = (
    "https://adstransparency.google.com/?region=PE&domain=interbank.pe"
    "&preset-date=Last+30+days"
)


def main() -> None:
    RECON_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Navegando directo a: {TEST_URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(TEST_URL, wait_until="load", timeout=30000)
        accept_cookies_if_present(page)
        page.wait_for_timeout(4000)

        block_reason = detect_block(page)
        if block_reason:
            print(f"BLOQUEADO: {block_reason}")
            browser.close()
            sys.exit(1)

        count_text = page.locator("text=/[0-9].*ads?/i").first
        try:
            print("Texto de conteo (deberia ser ~500 si el filtro aplico):", count_text.inner_text(timeout=2000))
        except Exception as exc:
            print("No se pudo leer el conteo:", exc)

        page.screenshot(path=str(RECON_DIR / "direct_url_filter.png"))

        print("\n--- Scrolleando para cargar mas tarjetas y ver cuentas anunciantes distintas ---")
        for i in range(8):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1200)

        html = page.content()
        (RECON_DIR / "interbank_scrolled.html").write_text(html, encoding="utf-8")

        advertiser_ids = page.evaluate(
            """
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="/advertiser/"]'));
                const seen = new Map();
                for (const a of links) {
                    const m = a.getAttribute('href').match(/advertiser\\/(AR[0-9]+)/);
                    if (!m) continue;
                    const id = m[1];
                    if (!seen.has(id)) {
                        // buscar el nombre del anunciante cerca de este link (tarjeta contenedora)
                        let card = a.closest('creative-grid-item, div');
                        let name = card ? card.textContent.trim().slice(0, 60) : '';
                        seen.set(id, name);
                    }
                }
                return Array.from(seen.entries());
            }
            """
        )
        print(f"Cuentas anunciantes (AR id) distintas encontradas: {len(advertiser_ids)}")
        for aid, name_snippet in advertiser_ids:
            print(f"  {aid} -> {name_snippet!r}")

        block_reason = detect_block(page)
        if block_reason:
            print(f"BLOQUEADO durante el scroll: {block_reason}")

        browser.close()


if __name__ == "__main__":
    main()
