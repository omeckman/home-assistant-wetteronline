"""WetterOnline Home Assistant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_LOCATION, CONF_LOCATION_ID, CONF_URL_WETTERONLINE, DOMAIN
from .coordinator import WeatherOnlineDataUpdateCoordinator
from .radar_card import async_setup_radar_card
from .wetteronline_api import WetterOnline

PLATFORMS = [Platform.WEATHER, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type WetterOnlineConfigEntry = ConfigEntry[WeatherOnlineDataUpdateCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the radar card shared by all locations."""
    await async_setup_radar_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WetterOnlineConfigEntry) -> bool:
    """Set up WetterOnline from a config entry."""
    client = WetterOnline(async_get_clientsession(hass), entry.data[CONF_LOCATION])
    coordinator = WeatherOnlineDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WetterOnlineConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the original name/url schema to a stable location id."""
    if entry.version >= 2:
        return True
    path = entry.data.get(CONF_URL_WETTERONLINE) or entry.data.get(CONF_LOCATION)
    if not path:
        return False
    old_name = str(entry.data.get(CONF_NAME) or entry.title)
    client = WetterOnline(async_get_clientsession(hass), path)
    data = await client.async_get_weather()

    entity_registry = er.async_get(hass)
    old_weather_entity_id = entity_registry.async_get_entity_id(Platform.WEATHER, DOMAIN, old_name)
    if old_weather_entity_id:
        entity_registry.async_update_entity(
            old_weather_entity_id, new_unique_id=f"{data.location.gid}_weather"
        )

    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_device(identifiers={(DOMAIN, old_name)})
    if old_device:
        device_registry.async_update_device(
            old_device.id, new_identifiers={(DOMAIN, data.location.gid)}
        )

    hass.config_entries.async_update_entry(
        entry,
        data={CONF_LOCATION: data.location.path, CONF_LOCATION_ID: data.location.gid},
        title=data.location.name or entry.data.get(CONF_NAME, entry.title),
        unique_id=data.location.gid,
        version=2,
    )
    return True
