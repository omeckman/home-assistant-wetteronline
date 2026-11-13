"""Integration setup and entity tests."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wetteronline import async_migrate_entry
from custom_components.wetteronline.const import CONF_LOCATION, CONF_LOCATION_ID, DOMAIN

from .test_config_flow import sample_data


async def test_setup_creates_weather_sensors_warning_and_radar(hass: HomeAssistant) -> None:
    """All platforms load from one coordinator refresh."""
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

    assert hass.states.get("weather.berlin") is not None
    assert hass.states.get("binary_sensor.berlin_weather_warning") is not None
    assert hass.states.get("camera.berlin_weather_radar") is not None
    assert hass.states.get("camera.berlin_weather_radar_animation") is not None
    assert hass.states.get("sensor.berlin_temperature").state == "20.0"


async def test_pollen_sensors_are_named_without_translation(hass: HomeAssistant) -> None:
    """Pollen types without a translation keep their name instead of the device name."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Berlin",
        unique_id="10382",
        version=2,
        data={CONF_LOCATION: "/wetter/berlin", CONF_LOCATION_ID: "10382"},
    )
    entry.add_to_hass(hass)
    data = sample_data()
    data.pollen = [
        {
            "date": "2026-07-12T00:00:00+02:00",
            "pollen": [{"name": "Hasel", "value": 0}, {"name": "Zeder", "value": 1}],
        }
    ]
    with patch(
        "custom_components.wetteronline.wetteronline_api.WetterOnline.async_get_weather",
        new=AsyncMock(return_value=data),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.berlin_pollen_hazel") is not None
    assert hass.states.get("sensor.berlin_pollen_zeder") is not None
    assert hass.states.get("sensor.berlin") is None


async def test_migration_preserves_weather_entity_and_device(hass: HomeAssistant) -> None:
    """Version-one registry entries are moved to stable geo ids."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My weather",
        unique_id="My weather",
        version=1,
        data={"name": "My weather", "url_wetteronline": "/wetter/berlin"},
    )
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    old_entity = entity_registry.async_get_or_create(
        "weather", DOMAIN, "My weather", config_entry=entry
    )
    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "My weather")}
    )

    with patch(
        "custom_components.wetteronline.wetteronline_api.WetterOnline.async_get_weather",
        new=AsyncMock(return_value=sample_data()),
    ):
        assert await async_migrate_entry(hass, entry)

    assert entry.version == 2
    assert entry.unique_id == "10382"
    assert entity_registry.async_get(old_entity.entity_id).unique_id == "10382_weather"
    assert device_registry.async_get(old_device.id).identifiers == {(DOMAIN, "10382")}
