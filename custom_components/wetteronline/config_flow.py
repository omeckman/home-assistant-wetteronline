"""Config flow for WetterOnline."""

from __future__ import annotations

from asyncio import timeout
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_LOCATION,
    CONF_LOCATION_ID,
    CONF_TIMELINE_POSITION,
    DOMAIN,
    TIMELINE_BOTTOM,
    TIMELINE_TOP,
)
from .wetteronline_api import (
    SearchResult,
    WetterOnline,
    WetterOnlineConnectionError,
    WetterOnlineError,
    WetterOnlineInvalidLocation,
    normalize_location,
)


class WetterOnlineFlowHandler(ConfigFlow, domain=DOMAIN):
    """Configure a WetterOnline location."""

    VERSION = 2
    _results: dict[str, SearchResult]
    _reconfigure = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WetterOnlineOptionsFlow:
        """Return the options flow."""
        return WetterOnlineOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Accept a place search, path, or complete URL."""
        return await self._async_location_step(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the configured location."""
        self._reconfigure = True
        return await self._async_location_step(user_input, "reconfigure")

    async def _async_location_step(
        self, user_input: dict[str, Any] | None, step_id: str = "user"
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            value = user_input[CONF_LOCATION].strip()
            session = async_get_clientsession(self.hass)
            try:
                async with timeout(20):
                    if value.startswith(("/", "http://", "https://", "wetter/")):
                        return await self._async_create_for_path(normalize_location(value))
                    results = await WetterOnline.async_search(session, value)
                    if not results:
                        raise WetterOnlineInvalidLocation("No search results")
                    self._results = {result.key: result for result in results}
                    if len(results) == 1:
                        path = await WetterOnline.async_resolve_search(session, results[0].key)
                        return await self._async_create_for_path(path)
                    return await self.async_step_select()
            except WetterOnlineConnectionError:
                errors["base"] = "cannot_connect"
            except WetterOnlineError:
                errors["base"] = "invalid_location"
            except TimeoutError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_LOCATION): str}),
            errors=errors,
        )

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select one of multiple search results."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                async with timeout(20):
                    path = await WetterOnline.async_resolve_search(
                        async_get_clientsession(self.hass), user_input[CONF_LOCATION_ID]
                    )
                    return await self._async_create_for_path(path)
            except WetterOnlineConnectionError:
                errors["base"] = "cannot_connect"
            except WetterOnlineError:
                errors["base"] = "invalid_location"
            except TimeoutError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_ID): vol.In(
                        {key: result.label for key, result in self._results.items()}
                    )
                }
            ),
            errors=errors,
        )

    async def _async_create_for_path(self, path: str) -> ConfigFlowResult:
        client = WetterOnline(async_get_clientsession(self.hass), path)
        data = await client.async_get_weather()
        await self.async_set_unique_id(data.location.gid)
        entry_data = {
            CONF_LOCATION: data.location.path,
            CONF_LOCATION_ID: data.location.gid,
        }
        if self._reconfigure:
            entry = self._get_reconfigure_entry()
            if any(
                configured.entry_id != entry.entry_id and configured.unique_id == data.location.gid
                for configured in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")

            old_gid = str(entry.unique_id or entry.data.get(CONF_LOCATION_ID, ""))
            if old_gid and old_gid != data.location.gid:
                entity_registry = er.async_get(self.hass)
                for registry_entry in er.async_entries_for_config_entry(
                    entity_registry, entry.entry_id
                ):
                    if registry_entry.unique_id.startswith(f"{old_gid}_"):
                        entity_registry.async_update_entity(
                            registry_entry.entity_id,
                            new_unique_id=registry_entry.unique_id.replace(
                                old_gid, data.location.gid, 1
                            ),
                        )
                device_registry = dr.async_get(self.hass)
                for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
                    if (DOMAIN, old_gid) in device.identifiers:
                        device_registry.async_update_device(
                            device.id,
                            new_identifiers={(DOMAIN, data.location.gid)},
                        )
            return self.async_update_reload_and_abort(
                entry,
                data_updates=entry_data,
                title=data.location.name,
                unique_id=data.location.gid,
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=data.location.name, data=entry_data)


class WetterOnlineOptionsFlow(OptionsFlowWithReload):
    """Change how WetterOnline radar images are drawn."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose where radar images show the time and timeline."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_TIMELINE_POSITION, default=TIMELINE_BOTTOM
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[TIMELINE_BOTTOM, TIMELINE_TOP],
                                translation_key=CONF_TIMELINE_POSITION,
                                mode=SelectSelectorMode.LIST,
                            )
                        )
                    }
                ),
                self.config_entry.options,
            ),
        )
