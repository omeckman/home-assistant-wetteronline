"""Tests for the structured WetterOnline page parser."""

import json

import pytest

from custom_components.wetteronline.const import map_condition
from custom_components.wetteronline.wetteronline_api import (
    WetterOnlineInvalidLocation,
    WetterOnlineParseError,
    normalize_location,
    parse_weather_page,
)


def _html() -> str:
    global_data = {
        "geo": {
            "gid": "10382",
            "locationname": "Berlin",
            "lat": "52.517",
            "lon": "13.4",
            "alt": "50",
        },
        "timeZone": "Europe/Berlin",
    }
    shortcast = {
        "current": {"air_temperature": {"celsius": 18}, "symbol": "mo____"},
        "hours": [{"date": "2026-07-12T00:00:00+02:00", "visibility": {"meter": 20000}}],
    }
    forecast = {"days": [{"date": "2026-07-12T00:00:00+02:00", "symbol": "so____"}]}
    state = {
        "https://api/astro/days/v1": {
            "days": [{"date": "2026-07-12", "sun": {"rise": "2026-07-12T05:00:00+02:00"}}]
        },
        "https://api/blending/forecast/v1": forecast,
        "https://api/blending/texts/v1": [
            {
                "date": "2026-07-12",
                "text": "Aktuell <WOCurrentTemperature>18</WOCurrentTemperature> Grad.",
            }
        ],
        "https://api/blending/shortcast/v1": shortcast,
        "https://api/pollen/v4": {
            "days": [{"date": "2026-07-12", "pollen": [{"name": "Gräser", "value": 2}]}]
        },
    }
    return f'<script id="ng-state" type="application/json">{json.dumps(state)}</script><script id="wo-global-json" type="application/json">{json.dumps(global_data)}</script>'


def test_parse_reordered_scripts_and_data() -> None:
    data = parse_weather_page(_html(), "/wetter/berlin")
    assert data.location.gid == "10382"
    assert data.location.name == "Berlin"
    assert data.current["air_temperature"]["celsius"] == 18
    assert len(data.hourly) == 1
    assert len(data.daily) == 1
    assert data.pollen[0]["pollen"][0]["name"] == "Gräser"
    assert data.forecast_texts[0]["text"] == "Aktuell 18 Grad."


@pytest.mark.parametrize(
    ("symbol", "condition"),
    [
        ("so____", "sunny"),
        ("mo____", "clear-night"),
        ("wb____", "partlycloudy"),
        ("wbr1__", "rainy"),
        ("wbr2__", "pouring"),
        ("mdr3__", "pouring"),
        ("wbs1__", "rainy"),
        ("bds2__", "pouring"),
        ("wbsn1_", "snowy"),
        ("bdsn2_", "snowy"),
        ("wbsns1", "snowy"),
        ("wbsns3", "snowy"),
        ("wbsr1_", "snowy-rainy"),
        ("wbsrs2", "snowy-rainy"),
        ("wbg1__", "lightning-rainy"),
        ("wbgr1_", "lightning-rainy"),
        ("wbsg__", "lightning-rainy"),
        ("ap____", "exceptional"),
    ],
)
def test_condition_mapping(symbol: str, condition: str) -> None:
    assert map_condition(symbol) == condition


def test_invalid_page() -> None:
    with pytest.raises(WetterOnlineParseError):
        parse_weather_page("<html></html>", "/wetter/missing")


def test_non_location_page() -> None:
    html = '<script id="wo-global-json">{}</script><script id="ng-state">{}</script>'
    with pytest.raises(WetterOnlineInvalidLocation):
        parse_weather_page(html, "/")


def test_location_normalization() -> None:
    assert normalize_location("wetter/berlin") == "/wetter/berlin"
    assert normalize_location("https://www.wetteronline.de/wetter/bonn") == "/wetter/bonn"
