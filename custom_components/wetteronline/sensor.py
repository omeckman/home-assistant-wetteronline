"""Sensor entities for all structured WetterOnline location data."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    UV_INDEX,
    UnitOfLength,
    UnitOfPressure,
    UnitOfRatio,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WetterOnlineConfigEntry
from .const import map_condition
from .coordinator import WeatherOnlineDataUpdateCoordinator, WetterOnlineEntityMixin
from .wetteronline_api import WetterOnlineData

ValueFn = Callable[[WetterOnlineData], Any]
AttrsFn = Callable[[WetterOnlineData], dict[str, Any] | None]


def _number(value: Any, *keys: str, multiplier: float = 1) -> float | None:
    try:
        for key in keys:
            value = value[key]
        return float(value) * multiplier
    except KeyError, TypeError, ValueError:
        return None


def _current(key: str, *nested: str, multiplier: float = 1) -> ValueFn:
    return lambda data: _number(data.current.get(key), *nested, multiplier=multiplier)


def _wind(data: WetterOnlineData, key: str = "value") -> float | None:
    return _number(data.current.get("wind"), "speed", "kilometer_per_hour", key)


def _hour(data: WetterOnlineData) -> dict[str, Any]:
    return data.hourly[0] if data.hourly else {}


def _day(data: WetterOnlineData) -> dict[str, Any]:
    return data.daily[0] if data.daily else {}


def _today_item(data: WetterOnlineData, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the location's current calendar-day item."""
    today = data.fetched_at.astimezone(ZoneInfo(data.location.timezone)).date()
    return next(
        (
            item
            for item in items
            if isinstance(item.get("date"), str)
            and datetime.fromisoformat(item["date"])
            .astimezone(ZoneInfo(data.location.timezone))
            .date()
            == today
        ),
        items[0] if items else {},
    )


def _water_day(data: WetterOnlineData) -> dict[str, Any]:
    days = data.water.get("days") or []
    return _today_item(data, days)


def _duration_hours(value: Any) -> float | None:
    """Convert the ISO hour/minute duration used by WetterOnline to hours."""
    if not isinstance(value, str) or not value.startswith("PT"):
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
    if not match:
        return None
    return round(float(match.group(1) or 0) + float(match.group(2) or 0) / 60, 2)


def _warning_items(data: WetterOnlineData) -> list[dict[str, Any]]:
    value = data.warnings
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("warnings", "items", "alerts"):
        items = value.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return [value] if value else []


class WetterOnlineSensor(
    WetterOnlineEntityMixin,
    CoordinatorEntity[WeatherOnlineDataUpdateCoordinator],
    SensorEntity,
):
    """A coordinator-backed WetterOnline sensor."""

    def __init__(
        self,
        coordinator: WeatherOnlineDataUpdateCoordinator,
        key: str,
        name: str,
        value_fn: ValueFn,
        *,
        attrs_fn: AttrsFn | None = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        unit: str | None = None,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn
        self._attr_unique_id = f"{coordinator.data.location.gid}_{key}"
        # The name is used when no translation exists, e.g. for new WetterOnline pollen types.
        self.entity_description = SensorEntityDescription(key=key, translation_key=key, name=name)
        self._attr_device_info = coordinator.device_info
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self) -> Any:
        value = self._value_fn(self.coordinator.data)
        if isinstance(value, str):
            return value[:255]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self._attrs_fn(self.coordinator.data) if self._attrs_fn else None


def _measurement(
    coordinator: WeatherOnlineDataUpdateCoordinator,
    key: str,
    name: str,
    fn: ValueFn,
    device_class: SensorDeviceClass | None,
    unit: str | None,
) -> WetterOnlineSensor:
    return WetterOnlineSensor(
        coordinator,
        key,
        name,
        fn,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        unit=unit,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create every available WetterOnline sensor."""
    c = entry.runtime_data
    sensors: list[SensorEntity] = [
        WetterOnlineSensor(
            c,
            "condition",
            "Condition",
            lambda d: map_condition(d.current.get("symbol")),
            icon="mdi:weather-partly-cloudy",
        ),
        WetterOnlineSensor(
            c,
            "weather_symbol",
            "Weather symbol",
            lambda d: d.current.get("symbol"),
            icon="mdi:code-tags",
        ),
        _measurement(
            c,
            "temperature",
            "Temperature",
            _current("air_temperature", "celsius"),
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        _measurement(
            c,
            "apparent_temperature",
            "Apparent temperature",
            _current("apparent_temperature", "celsius"),
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        _measurement(
            c,
            "dew_point",
            "Dew point",
            _current("dew_point", "celsius"),
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        _measurement(
            c,
            "humidity",
            "Humidity",
            _current("humidity", multiplier=100),
            SensorDeviceClass.HUMIDITY,
            UnitOfRatio.PERCENTAGE,
        ),
        _measurement(
            c,
            "pressure",
            "Pressure",
            _current("air_pressure", "hpa"),
            SensorDeviceClass.PRESSURE,
            UnitOfPressure.HPA,
        ),
        WetterOnlineSensor(
            c,
            "pressure_tendency",
            "Pressure tendency",
            lambda d: d.current.get("air_pressure_tendency_category"),
            icon="mdi:gauge",
        ),
        _measurement(
            c,
            "wind_speed",
            "Wind speed",
            _wind,
            SensorDeviceClass.WIND_SPEED,
            UnitOfSpeed.KILOMETERS_PER_HOUR,
        ),
        _measurement(
            c,
            "wind_gust",
            "Wind gust",
            lambda d: _wind(d, "max_gust"),
            SensorDeviceClass.WIND_SPEED,
            UnitOfSpeed.KILOMETERS_PER_HOUR,
        ),
        WetterOnlineSensor(
            c,
            "wind_bearing",
            "Wind bearing",
            lambda d: _number(d.current.get("wind"), "direction"),
            device_class=SensorDeviceClass.WIND_DIRECTION,
            state_class=SensorStateClass.MEASUREMENT_ANGLE,
            unit=DEGREE,
        ),
        _measurement(
            c,
            "visibility",
            "Visibility",
            lambda d: _number(_hour(d), "visibility", "meter"),
            SensorDeviceClass.DISTANCE,
            UnitOfLength.METERS,
        ),
        WetterOnlineSensor(
            c,
            "precipitation_type",
            "Precipitation type",
            lambda d: (d.current.get("precipitation") or {}).get("type"),
            icon="mdi:weather-rainy",
        ),
        _measurement(
            c,
            "precipitation_probability",
            "Precipitation probability",
            lambda d: _number(d.current.get("precipitation"), "probability", multiplier=100),
            None,
            UnitOfRatio.PERCENTAGE,
        ),
        WetterOnlineSensor(
            c,
            "uv_index",
            "UV index",
            lambda d: _number(_day(d), "uv_index", "value"),
            state_class=SensorStateClass.MEASUREMENT,
            unit=UV_INDEX,
            icon="mdi:sun-wireless",
        ),
        WetterOnlineSensor(
            c,
            "solar_elevation",
            "Solar elevation",
            _current("solar_elevation"),
            state_class=SensorStateClass.MEASUREMENT_ANGLE,
            unit=DEGREE,
            icon="mdi:weather-sunset-up",
        ),
        WetterOnlineSensor(
            c, "smog_level", "Smog level", lambda d: d.current.get("smog_level"), icon="mdi:blur"
        ),
        _measurement(
            c,
            "convection_probability",
            "Convection probability",
            lambda d: _number(_hour(d), "convection_probability", multiplier=100),
            None,
            UnitOfRatio.PERCENTAGE,
        ),
        _measurement(
            c,
            "sunshine_duration",
            "Sunshine duration",
            lambda d: _number(_day(d), "sunshine_duration", "hours"),
            SensorDeviceClass.DURATION,
            UnitOfTime.HOURS,
        ),
        WetterOnlineSensor(
            c,
            "warning_count",
            "Warning count",
            lambda d: len(_warning_items(d)),
            attrs_fn=lambda d: {"warnings": _warning_items(d)},
            icon="mdi:alert",
        ),
        WetterOnlineSensor(
            c,
            "forecast_text",
            "Forecast text",
            lambda d: d.forecast_texts[0].get("text") if d.forecast_texts else None,
            attrs_fn=lambda d: {"forecast": d.forecast_texts},
            icon="mdi:text-box-outline",
        ),
        WetterOnlineSensor(
            c,
            "editorial",
            "Editorial notification",
            lambda d: d.editorial.get("title") or d.editorial.get("body"),
            attrs_fn=lambda d: d.editorial or None,
            icon="mdi:newspaper",
        ),
    ]

    pollen_names = sorted(
        {
            item.get("name")
            for day in c.data.pollen
            for item in day.get("pollen", [])
            if item.get("name")
        }
    )
    for pollen_name in pollen_names:

        def pollen_value(data: WetterOnlineData, name: str = pollen_name) -> Any:
            for item in _today_item(data, data.pollen).get("pollen", []):
                if item.get("name") == name:
                    return item.get("value")
            return None

        def pollen_attrs(data: WetterOnlineData, name: str = pollen_name) -> dict[str, Any]:
            return {
                "forecast": [
                    {
                        "date": day.get("date"),
                        "value": next(
                            (
                                x.get("value")
                                for x in day.get("pollen", [])
                                if x.get("name") == name
                            ),
                            None,
                        ),
                    }
                    for day in data.pollen
                ]
            }

        key = "pollen_" + pollen_name.lower().replace("ß", "ss").replace("ä", "ae").replace(
            "ö", "oe"
        ).replace("ü", "ue")
        sensors.append(
            WetterOnlineSensor(
                c,
                key,
                f"Pollen {pollen_name}",
                pollen_value,
                attrs_fn=pollen_attrs,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:flower-pollen",
            )
        )

    astro = [
        (
            "sunrise",
            "Sunrise",
            lambda x: (x.get("sun") or {}).get("rise"),
            SensorDeviceClass.TIMESTAMP,
            None,
        ),
        (
            "sunset",
            "Sunset",
            lambda x: (x.get("sun") or {}).get("set"),
            SensorDeviceClass.TIMESTAMP,
            None,
        ),
        (
            "day_length",
            "Day length",
            lambda x: _duration_hours((x.get("sun") or {}).get("day_length")),
            SensorDeviceClass.DURATION,
            UnitOfTime.HOURS,
        ),
        (
            "moonrise",
            "Moonrise",
            lambda x: (x.get("moon") or {}).get("rise"),
            SensorDeviceClass.TIMESTAMP,
            None,
        ),
        (
            "moonset",
            "Moonset",
            lambda x: (x.get("moon") or {}).get("set"),
            SensorDeviceClass.TIMESTAMP,
            None,
        ),
        ("moon_age", "Moon age", lambda x: (x.get("moon") or {}).get("age"), None, None),
    ]
    for key, name, fn, device_class, astro_unit in astro:

        def astro_value(
            data: WetterOnlineData,
            getter: Callable[[dict[str, Any]], Any] = fn,
            dc: SensorDeviceClass | None = device_class,
        ) -> Any:
            day = _today_item(data, data.astronomy)
            value = getter(day)
            if dc == SensorDeviceClass.TIMESTAMP and isinstance(value, str):
                return datetime.fromisoformat(value)
            return value

        sensors.append(
            WetterOnlineSensor(
                c,
                key,
                name,
                astro_value,
                device_class=device_class,
                unit=astro_unit,
                icon="mdi:weather-sunset" if "sun" in key else "mdi:moon-waning-crescent",
            )
        )

    water = [
        (
            "water_temperature",
            "Water temperature",
            lambda d: _number(_water_day(d), "temperature", "water"),
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        (
            "water_air_temperature",
            "Water location air temperature",
            lambda d: _number(_water_day(d), "temperature", "air"),
            SensorDeviceClass.TEMPERATURE,
            UnitOfTemperature.CELSIUS,
        ),
        (
            "water_uv_index",
            "Water location UV index",
            lambda d: _number(_water_day(d), "uv_index", "value"),
            None,
            UV_INDEX,
        ),
        (
            "water_wind_speed",
            "Water location wind speed",
            lambda d: _number(_water_day(d), "wind", "speed", "kilometer_per_hour", "value"),
            SensorDeviceClass.WIND_SPEED,
            UnitOfSpeed.KILOMETERS_PER_HOUR,
        ),
        (
            "water_wind_gust",
            "Water location wind gust",
            lambda d: _number(_water_day(d), "wind", "speed", "kilometer_per_hour", "max_gust"),
            SensorDeviceClass.WIND_SPEED,
            UnitOfSpeed.KILOMETERS_PER_HOUR,
        ),
        (
            "water_wind_bearing",
            "Water location wind bearing",
            lambda d: _number(_water_day(d), "wind", "direction"),
            SensorDeviceClass.WIND_DIRECTION,
            DEGREE,
        ),
    ]
    for key, name, fn, device_class, unit in water:
        if device_class == SensorDeviceClass.WIND_DIRECTION:
            sensors.append(
                WetterOnlineSensor(
                    c,
                    key,
                    name,
                    fn,
                    device_class=device_class,
                    state_class=SensorStateClass.MEASUREMENT_ANGLE,
                    unit=unit,
                )
            )
        else:
            sensors.append(_measurement(c, key, name, fn, device_class, unit))

    async_add_entities(sensors)
