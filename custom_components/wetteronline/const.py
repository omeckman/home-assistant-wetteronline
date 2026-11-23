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
    #
    # See GLG9/home-assistant-wetteronline#1: every "s" used to be mapped to
    # snow, so rain showers (e.g. "wbs1__") showed up as snow at 20 °C. The
    # codes were verified via the content hashes in WetterOnline's asset
    # manifest: "wbs1__" uses the same image as "wbr1__", "wbsns1" the same
    # as "wbsn1_", while "sr"/"srs" have their own sleet image.
    #
    # Unlike the fix proposed in that issue, we strip the "_" padding before
    # reading the intensity. Otherwise "wbr2__" never ends in "2" and heavy
    # rain never becomes "pouring". Showers ("s") use the same intensity rule
    # as rain because WetterOnline draws "wbs2__" with the same image as
    # "wbr2__".
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
