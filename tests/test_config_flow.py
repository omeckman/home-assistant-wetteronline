"""Config flow tests."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wetteronline.const import (
    CONF_LOCATION,
    CONF_LOCATION_ID,
    CONF_TIMELINE_POSITION,
    DOMAIN,
    TIMELINE_TOP,
)
from custom_components.wetteronline.wetteronline_api import Location, WetterOnlineData


def sample_data() -> WetterOnlineData:
    """Return representative normalized data."""
    wind = {
        "direction": 180,
        "speed": {"kilometer_per_hour": {"value": "10", "max_gust": "20"}},
    }
    return WetterOnlineData(
        location=Location("10382", "Berlin", 52.517, 13.4, 50, "Europe/Berlin", "/wetter/berlin"),
        current={
            "air_temperature": {"celsius": 20},
            "apparent_temperature": {"celsius": 19},
            "dew_point": {"celsius": 10},
            "humidity": 0.5,
            "air_pressure": {"hpa": "1015"},
            "precipitation": {"probability": 0.1, "type": "rain"},
            "symbol": "wb____",
            "wind": wind,
        },
        hourly=[
            {
                "date": "2026-07-12T12:00:00+02:00",
                "air_temperature": {"celsius": 21},
                "apparent_temperature": {"celsius": 20},
                "humidity": 0.5,
                "precipitation": {"probability": 0.2, "type": "rain"},
                "visibility": {"meter": 20000},
                "symbol": "wb____",
                "wind": wind,
            }
        ],
        daily=[
            {
                "date": "2026-07-12T00:00:00+02:00",
                "air_temperature": {"max": {"celsius": 25}, "min": {"celsius": 12}},
                "apparent_temperature": {"max": {"celsius": 24}},
                "humidity": 0.5,
                "precipitation": {"probability": 0.2, "type": "rain"},
                "symbol": "so____",
                "wind": wind,
                "uv_index": {"value": 5},
                "sunshine_duration": {"hours": 8},
            }
        ],
    )


async def test_user_flow_with_path(hass: HomeAssistant) -> None:
    """A valid URL/path creates a stable config entry."""
    with patch(
        "custom_components.wetteronline.wetteronline_api.WetterOnline.async_get_weather",
        new=AsyncMock(return_value=sample_data()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_LOCATION: "/wetter/berlin"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Berlin"
    assert result["data"] == {CONF_LOCATION: "/wetter/berlin", CONF_LOCATION_ID: "10382"}


async def test_user_flow_with_search(hass: HomeAssistant) -> None:
    """An ambiguous text search presents a location selector."""
    search = [
        type("Result", (), {"key": "1", "label": "Berlin"})(),
        type("Result", (), {"key": "2", "label": "Berlin, USA"})(),
    ]
    with patch(
        "custom_components.wetteronline.wetteronline_api.WetterOnline.async_search",
        new=AsyncMock(return_value=search),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_LOCATION: "Berlin"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select"


async def test_reconfigure_changes_location_and_registry_ids(hass: HomeAssistant) -> None:
    """Reconfigure can move an existing entry without duplicating entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bonn",
        unique_id="10518",
        version=2,
        data={CONF_LOCATION: "/wetter/bonn", CONF_LOCATION_ID: "10518"},
    )
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    weather = entity_registry.async_get_or_create(
        "weather", DOMAIN, "10518_weather", config_entry=entry
    )
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "10518")}
    )

    with (
        patch(
            "custom_components.wetteronline.wetteronline_api.WetterOnline.async_get_weather",
            new=AsyncMock(return_value=sample_data()),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
            data={CONF_LOCATION: "/wetter/berlin"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "10382"
    assert entity_registry.async_get(weather.entity_id).unique_id == "10382_weather"
    assert device_registry.async_get(device.id).identifiers == {(DOMAIN, "10382")}


async def test_options_flow_moves_timeline_and_reloads(hass: HomeAssistant) -> None:
    """The timeline position is an option that reloads the radar cameras."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Berlin",
        unique_id="10382",
        version=2,
        data={CONF_LOCATION: "/wetter/berlin", CONF_LOCATION_ID: "10382"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.wetteronline.wetteronline_api.WetterOnline.async_get_weather",
        new=AsyncMock(return_value=sample_data()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        with patch.object(
            hass.config_entries,
            "async_schedule_reload",
            wraps=hass.config_entries.async_schedule_reload,
        ) as schedule_reload:
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], {CONF_TIMELINE_POSITION: TIMELINE_TOP}
            )
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_TIMELINE_POSITION: TIMELINE_TOP}
    schedule_reload.assert_called_once_with(entry.entry_id)
