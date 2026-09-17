"""Dominios MVP para el piloto de Google Ads Transparency Center.

region es el codigo ISO de pais a pasar en el parametro `region` de
adstransparency.google.com. entity es la etiqueta legible que usamos
para nombrar los archivos de salida.
"""

GOOGLE_DOMAINS = [
    {"entity": "interbank", "domain": "interbank.pe", "region": "PE"},
    {"entity": "bcp", "domain": "viabcp.com", "region": "PE"},
    {"entity": "yape", "domain": "yape.com.pe", "region": "PE"},
]
