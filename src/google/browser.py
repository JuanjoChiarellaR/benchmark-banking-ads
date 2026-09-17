"""Helpers compartidos para el scraper de Google Ads Transparency Center."""

import html
import random
import re
import time
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://adstransparency.google.com"

MIN_DELAY_SECONDS = 3.0
MAX_DELAY_SECONDS = 5.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Senales de que Google esta bloqueando/desafiando al navegador automatizado.
# Ante cualquiera de estas, hay que detenerse y reportar -- nunca asumir que
# la pagina "no cargo" y seguir reintentando.
BLOCK_SIGNALS = [
    "unusual traffic",
    "verify you're a human",
    "verify you are a human",
    "our systems have detected unusual traffic",
    "g-recaptcha",
    "hcaptcha",
    "captcha-form",
]


class BlockedError(RuntimeError):
    """Se detecto una senal de bloqueo/CAPTCHA por parte de Google."""


def polite_wait() -> None:
    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))


def build_search_url(domain: str, region: str) -> str:
    return f"{BASE_URL}/?region={region}&domain={domain}"


def safe_goto(
    page,
    url: str,
    attempts: int = 3,
    wait_until: str = "domcontentloaded",
    timeout: int = 30000,
) -> bool:
    """Navega con reintentos ante timeouts de red transitorios.

    Un timeout de red no es lo mismo que un bloqueo/CAPTCHA (eso lo maneja
    detect_block por separado) -- es una falla de conectividad puntual, y
    no debe tumbar toda la corrida. Devuelve False si los reintentos se
    agotaron, para que quien llama decida como registrar/saltar ese caso.
    """
    for attempt in range(attempts):
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            if attempt == attempts - 1:
                return False
            time.sleep(2 + attempt)
    return False


def accept_cookies_if_present(page) -> None:
    """Cierra el dialogo de consentimiento de cookies si aparece. Best-effort."""
    candidates = [
        "button:has-text('Accept all')",
        "button:has-text('Aceptar todo')",
        "button:has-text('I agree')",
        "button:has-text('Acepto')",
    ]
    for selector in candidates:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2000):
                button.click()
                return
        except Exception:
            continue


def detect_block(page) -> Optional[str]:
    """Devuelve una descripcion de la senal de bloqueo encontrada, o None."""
    try:
        content = page.content().lower()
    except Exception as exc:
        return f"no se pudo leer el contenido de la pagina: {exc}"

    for signal in BLOCK_SIGNALS:
        if signal in content:
            return f"texto/senal de bloqueo detectada en el HTML: '{signal}'"

    try:
        if page.locator("iframe[src*='recaptcha']").count() > 0:
            return "iframe de reCAPTCHA presente en la pagina"
        if page.locator("iframe[src*='hcaptcha']").count() > 0:
            return "iframe de hCaptcha presente en la pagina"
    except Exception:
        pass

    return None


def open_full_ads_grid(page) -> None:
    """Hace click en 'See all ads' para expandir la grilla completa.

    La pagina de busqueda por dominio arranca mostrando solo un preview de
    4 tarjetas -- sin este click, el resto de anuncios ni siquiera esta en
    el DOM (no es un tema de scroll).
    """
    link = page.get_by_text("See all ads")
    if link.count() > 0:
        link.first.click()
        page.wait_for_timeout(2000)


def apply_last_30_days_filter(page) -> None:
    """Abre el dropdown de fecha, selecciona 'Last 30 days' y confirma con OK.

    Confirmado por reconocimiento manual: el query param `preset-date` que
    aparece en la URL despues de aplicar el filtro NO sirve como atajo (no
    aplica el filtro si se navega directo con ese param) -- hay que operar
    el dropdown.
    """
    filter_button = page.locator("text=Any time").first
    if filter_button.count() == 0:
        if page.locator("text=Last 30 days").first.count() > 0:
            return  # ya esta aplicado (ej. sesion persistida)
        raise RuntimeError("No se encontro el boton de filtro de fecha ('Any time').")

    filter_button.click()
    page.wait_for_timeout(500)
    page.get_by_text("Last 30 days", exact=True).click()
    page.wait_for_timeout(300)
    ok_button = page.get_by_text("OK", exact=True)
    if ok_button.count() > 0:
        ok_button.first.click()
    page.wait_for_timeout(2500)


def read_ads_count(page) -> Optional[str]:
    try:
        return page.locator("text=/[0-9].*ads?/i").first.inner_text(timeout=2000)
    except Exception:
        return None


def collect_creative_links(
    page, max_scrolls: int = 25, target_min_links: int = 60
) -> List[Tuple[Tuple[str, str], str]]:
    """Scrollea la grilla de resultados y devuelve pares ((advertiser_id,
    creative_id), href) en el orden en que aparecieron por primera vez en el
    DOM (se asume orden = mas reciente primero, que es el default del sitio).
    """
    seen: Dict[Tuple[str, str], str] = {}
    for _ in range(max_scrolls):
        links = page.evaluate(
            """
            () => Array.from(
                document.querySelectorAll('a[href*="/advertiser/"][href*="/creative/"]')
            ).map(a => a.getAttribute('href'))
            """
        )
        for href in links:
            match = re.search(r"advertiser/(AR\d+)/creative/(CR\d+)", href)
            if not match:
                continue
            key = (match.group(1), match.group(2))
            if key not in seen:
                seen[key] = href
        if len(seen) >= target_min_links:
            break
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1000)
    return list(seen.items())


def extract_ad_text_from_adframe(page, timeout_ms: int = 6000) -> Optional[str]:
    """Intenta extraer el texto visible del creativo desde el iframe
    'adframe' que Google usa para renderizar la vista previa del anuncio.

    Best-effort: el iframe es de un servidor de anuncios en vivo (ad
    serving), no contenido estatico, y en automatizacion headless a veces
    no llega a poblarse a tiempo o el creativo es puramente visual (Image/
    Video), en cuyo caso no hay texto que extraer. Devuelve None si no se
    pudo obtener nada -- no se trata como error.
    """
    best_text = ""
    for frame in page.frames:
        if "adframe" not in frame.url:
            continue
        try:
            raw_html = frame.locator("body").inner_html(timeout=timeout_ms)
        except Exception:
            continue
        cleaned = _clean_adframe_html(raw_html)
        if len(cleaned) > len(best_text):
            best_text = cleaned
    return best_text or None


def _clean_adframe_html(raw_html: str) -> str:
    """Quita <style>/<script> y tags, deja texto plano separado por '|'.

    Necesario porque el iframe de Google incluye reglas CSS embebidas que
    (por una particularidad de como Chrome headless expone innerText en
    ese frame) terminan mezcladas con el texto visible real.
    """
    raw_html = re.sub(r"<style[^>]*>.*?</style>", " ", raw_html, flags=re.DOTALL)
    raw_html = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " | ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s*\|\s*(\|\s*)+", " | ", text)
    text = re.sub(r"[ \t]+", " ", text).strip(" |")
    return text


def group_by_advertiser(
    ordered_links: List[Tuple[Tuple[str, str], str]], limit_per_advertiser: int = 10
) -> Dict[str, List[dict]]:
    """Agrupa los creative links por advertiser_id, tomando como maximo
    `limit_per_advertiser` por cuenta, en el orden en que se encontraron
    (mas recientes primero)."""
    groups: Dict[str, List[dict]] = {}
    for (advertiser_id, creative_id), href in ordered_links:
        bucket = groups.setdefault(advertiser_id, [])
        if len(bucket) < limit_per_advertiser:
            bucket.append({"creative_id": creative_id, "href": href})
    return groups
