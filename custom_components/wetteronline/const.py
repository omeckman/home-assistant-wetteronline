"""Constants for the WetterOnline integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wetteronline"
ATTRIBUTION: Final = "Data provided by WetterOnline"
MANUFACTURER: Final = "WetterOnline"
CONF_LOCATION: Final = "location"
CONF_LOCATION_ID: Final = "location_id"
CONF_URL_WETTERONLINE: Final = "url_wetteronline"  # v1 migration
UPDATE_INTERVAL: Final = timedelta(minutes=15)
RADAR_INTERVAL: Final = timedelta(minutes=5)

# WetterOnline symbol families. Prefixes contain day/night and cloud amount;
# suffixes describe precipitation and thunderstorm intensity.
SYMBOL_CONDITION_MAP: Final[dict[str, str]] = {
    "so": "sunny",
    "mo": "clear-night",
    "wb": "partlycloudy",
    "bw": "partlycloudy",
    "mb": "cloudy",
    "mw": "cloudy",
    "bd": "cloudy",
    "md": "cloudy",
    "mm": "fog",
    "am": "fog",
    "nm": "fog",
}


def map_condition(symbol: str | None) -> str | None:
    """Map a WetterOnline symbol to a Home Assistant condition."""
    if not symbol:
        return None
    value = symbol.lower()
    # Precipitation suffix codes (verified against WetterOnline's symbol assets):
    #   r = rain, s = rain showers, sn/sns = snow (showers),
    #   sr/srs = sleet (showers), g/gr/sg = thunderstorm.
    # A trailing digit 1-3 gives the intensity; "_" is padding.
    precipitation = value[2:].rstrip("_")
    kind = precipitation.rstrip("0123456789")
    if "g" in kind:
        return "lightning-rainy"
    if kind.startswith("sr"):
        return "snowy-rainy"
    if kind.startswith("sn"):
        return "snowy"
    if kind in ("r", "s"):
        return "pouring" if precipitation.endswith(("2", "3")) else "rainy"
    return SYMBOL_CONDITION_MAP.get(value[:2], "exceptional")
