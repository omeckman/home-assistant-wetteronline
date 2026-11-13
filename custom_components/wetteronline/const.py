"""Constants for the WetterOnline integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wetteronline"
ATTRIBUTION: Final = "Data provided by WetterOnline"
MANUFACTURER: Final = "WetterOnline"
CONF_LOCATION: Final = "location"
CONF_LOCATION_ID: Final = "location_id"
CONF_URL_WETTERONLINE: Final = "url_wetteronline"  # v1 migration
CONF_TIMELINE_POSITION: Final = "timeline_position"
TIMELINE_BOTTOM: Final = "bottom"
TIMELINE_TOP: Final = "top"
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
    if "g" in value[2:]:
        return "lightning-rainy"
    if "sn" in value[2:]:
        return "snowy-rainy"
    if "s" in value[2:]:
        return "snowy"
    if "r" in value[2:]:
        return "pouring" if value.endswith(("2_", "3_", "2", "3")) else "rainy"
    return SYMBOL_CONDITION_MAP.get(value[:2], "exceptional")
