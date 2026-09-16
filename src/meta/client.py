"""Cliente minimo para el endpoint ads_archive de la Meta Ad Library API.

Version de Graph API confirmada como estable actual (ver plan/README):
developers.facebook.com/docs/graph-api/changelog -> v26.0.
"""

import os
import random
import time

import requests

GRAPH_API_VERSION = "v26.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

MAX_RETRIES = 5
BASE_DELAY_SECONDS = 2
MAX_DELAY_SECONDS = 60
BETWEEN_CALLS_SECONDS = 1.5

RATE_LIMIT_HTTP_CODES = {429}
RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}


class MetaAPIError(RuntimeError):
    pass


def get_access_token() -> str:
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "META_ACCESS_TOKEN no esta seteado. Definilo como variable de "
            "entorno (o en un .env local, ver .env.example) antes de correr "
            "el script. Nunca lo hardcodees en el codigo."
        )
    return token


def _mask(token: str) -> str:
    return f"{token[:6]}..." if len(token) > 6 else "***"


def call_ads_archive(params: dict) -> dict:
    """Llama a GET /ads_archive con reintentos y backoff exponencial ante rate limits."""
    token = get_access_token()
    url = f"{BASE_URL}/ads_archive"
    query = dict(params)
    query["access_token"] = token

    attempt = 0
    while True:
        response = requests.get(url, params=query, timeout=30)

        if response.status_code == 200:
            return response.json()

        try:
            error_body = response.json().get("error", {})
        except ValueError:
            error_body = {}
        error_code = error_body.get("code")
        is_rate_limited = (
            response.status_code in RATE_LIMIT_HTTP_CODES
            or error_code in RATE_LIMIT_ERROR_CODES
        )

        if is_rate_limited and attempt < MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
            else:
                delay = BASE_DELAY_SECONDS * (2 ** attempt) + random.uniform(0, 1)
            delay = min(delay, MAX_DELAY_SECONDS)
            print(
                f"  Rate limit detectado (intento {attempt + 1}/{MAX_RETRIES}). "
                f"Esperando {delay:.1f}s..."
            )
            time.sleep(delay)
            attempt += 1
            continue

        raise MetaAPIError(
            f"Error {response.status_code} llamando a ads_archive: "
            f"{error_body.get('message', response.text)} "
            f"(token usado: {_mask(token)})"
        )
