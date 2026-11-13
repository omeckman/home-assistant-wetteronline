"""WetterOnline weather, rain, and cloud radar cameras."""

from __future__ import annotations

import asyncio
import base64
import math
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, override
from urllib.parse import urlencode

from aiohttp import ClientError, ClientSession
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw

from . import WetterOnlineConfigEntry
from .const import ATTRIBUTION, RADAR_INTERVAL
from .coordinator import WeatherOnlineDataUpdateCoordinator

METADATA_URL = "https://tiles.wo-cloud.com/metadata"
COMPOSITE_URL = "https://tiles.wo-cloud.com/composite"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
HEADERS = {
    "User-Agent": "HomeAssistant-WetterOnline/2.0 (+https://github.com/GLG9/home-assistant-wetteronline)"
}
# Dashboards reload camera images every 10 seconds, so one loop must finish before that.
ANIMATION_LOOP_MS = 9000
MAX_FRAME_MS = 650
MAX_PARALLEL_TILES = 8


@dataclass(frozen=True, slots=True)
class RadarTiles:
    """A WetterOnline tile layer that the composite service can render."""

    key: str
    composite_type: str
    tile_suffix: str


@dataclass(frozen=True, slots=True)
class RadarLayer:
    """Tile layers drawn together on a base map."""

    tiles: tuple[RadarTiles, ...]
    translation_key: str
    unique_id_key: str
    wetteronline_map: bool
    credits: str


@dataclass(frozen=True, slots=True)
class RadarPeriod:
    """A WetterOnline radar time range rendered as an animation."""

    key: str
    api_name: str
    max_age: timedelta


RAIN_TILES = RadarTiles(key="rain", composite_type="r", tile_suffix="/sprite")
CLOUD_TILES = RadarTiles(key="clouds", composite_type="c", tile_suffix="")
RAIN = RadarLayer(
    tiles=(RAIN_TILES,),
    translation_key="rain_radar",
    unique_id_key="rain",
    wetteronline_map=False,
    credits="WetterOnline · © OpenStreetMap",
)
CLOUDS = RadarLayer(
    tiles=(CLOUD_TILES,),
    translation_key="cloud_radar",
    unique_id_key="clouds",
    wetteronline_map=True,
    credits="WetterOnline",
)
# Like WetterOnline's WetterRadar; keeps the unique ids of the former rain-only cameras.
WEATHER = RadarLayer(
    tiles=(CLOUD_TILES, RAIN_TILES),
    translation_key="weather_radar",
    unique_id_key="radar",
    wetteronline_map=True,
    credits="WetterOnline",
)
CURRENT = RadarPeriod("animation", "periodCurrentLowRes", RADAR_INTERVAL)
TODAY = RadarPeriod("today", "periodPrognose24h", timedelta(minutes=30))
TOMORROW = RadarPeriod("tomorrow", "periodTomorrow", timedelta(minutes=30))


def _world(latitude: float, longitude: float, zoom: int = 8) -> tuple[float, float]:
    """Return the Web Mercator position in tile units."""
    lat = math.radians(max(min(latitude, 85.0511), -85.0511))
    n = 2**zoom
    return (
        (longitude + 180.0) / 360.0 * n,
        (1.0 - math.asinh(math.tan(lat)) / math.pi) / 2.0 * n,
    )


def _layer_path(layer: dict[str, Any], time_path: list[str]) -> str:
    return f"{layer['ptypPath']}{layer['path']}/{'/'.join(time_path)}"


def _step_time(step_id: str) -> datetime | None:
    try:
        return datetime.strptime(step_id[:13], "%Y%m%d-%H%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def _label(step_id: str) -> str:
    time = _step_time(step_id)
    return f"{dt_util.as_local(time):%d.%m. %H:%M}" if time else step_id


def _encode_gif(frames: list[Image.Image], duration: int) -> bytes:
    # The fixed web palette keeps unchanged map areas identical, so GIF frames stay small.
    out = BytesIO()
    frames[0].convert("P").save(
        out,
        "GIF",
        save_all=True,
        append_images=[frame.convert("P") for frame in frames[1:]],
        duration=duration,
        loop=0,
        optimize=True,
    )
    return out.getvalue()


class RadarRenderer:
    """Fetch public radar layers and render them around a location."""

    def __init__(
        self, session: ClientSession, latitude: float, longitude: float, layer: RadarLayer = RAIN
    ) -> None:
        self.session = session
        self.latitude = latitude
        self.longitude = longitude
        self.layer = layer
        self._base: tuple[bytes, bytes | None] | None = None
        self._cache: dict[str, tuple[datetime, bytes]] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tile_limit = asyncio.Semaphore(MAX_PARALLEL_TILES)
        world_x, world_y = _world(latitude, longitude)
        # The 768 px view spans three or four zoom-8 tiles per axis, fetched as 2x2 blocks.
        self._left = math.floor(world_x - 1.5) // 2 * 2
        self._top = math.floor(world_y - 1.5) // 2 * 2
        self._columns = (math.floor(world_x + 1.5) - self._left) // 2 + 1
        self._rows = (math.floor(world_y + 1.5) - self._top) // 2 + 1
        marker_x = int((world_x - self._left) * 256)
        marker_y = int((world_y - self._top) * 256)
        self._marker = (marker_x, marker_y)
        self._crop = (marker_x - 384, marker_y - 384, marker_x + 384, marker_y + 384)
        self._origins = [
            (self._left + 2 * column, self._top + 2 * row)
            for row in range(self._rows)
            for column in range(self._columns)
        ]

    async def _get_json(self, params: dict[str, str]) -> dict[str, Any]:
        async with self.session.get(METADATA_URL, params=params, headers=HEADERS) as response:
            response.raise_for_status()
            return await response.json()

    async def _metadata(self, period: RadarPeriod) -> dict[str, Any]:
        return await self._get_json(
            {"lg": "wr", "newMetadata": "true", "period": period.api_name, "type": "period"}
        )

    async def _fetch(self, url: str) -> bytes:
        async with self._tile_limit, self.session.get(url, headers=HEADERS) as response:
            response.raise_for_status()
            return await response.read()

    async def _composite(self, descriptor: str, time: str | None = None) -> bytes:
        params = {"k": "0", "lg": "wr", "tiles": base64.b64encode(descriptor.encode()).decode()}
        if time:
            params |= {"format": "webp", "time": time}
        return await self._fetch(f"{COMPOSITE_URL}?{urlencode(params)}")

    async def _base_map(self) -> tuple[bytes, bytes | None]:
        """Return the cached background and the optional overlay drawn above the radar."""
        if not self._base:
            if self.layer.wetteronline_map:
                self._base = await self._wetteronline_map()
            else:
                self._base = (await self._osm_map(), None)
        return self._base

    async def _osm_map(self) -> bytes:
        urls = [
            OSM_URL.format(z=8, x=self._left + dx, y=self._top + dy)
            for dy in range(2 * self._rows)
            for dx in range(2 * self._columns)
        ]
        tiles = await asyncio.gather(*(self._fetch(url) for url in urls))
        return await asyncio.to_thread(self._compose_tiles, tiles, 256, 2 * self._columns)

    async def _wetteronline_map(self) -> tuple[bytes, bytes]:
        geo = await self._get_json({"type": "geo"})
        static = geo["staticLayer"]

        def descriptor(composite_type: str, name: str, x: int, y: int) -> str:
            layer = static[name]
            ext = layer["type"][min(8 - int(geo["minZoom"]), len(layer["type"]) - 1)]
            return f"{composite_type}|1;;0;0|{static['path']}{layer['path']}ZL8/512/{x}_{y}.{ext}"

        topography, overlay = await asyncio.gather(
            asyncio.gather(
                *(
                    self._composite(descriptor("topo", "wrTopography", x, y))
                    for x, y in self._origins
                )
            ),
            asyncio.gather(
                *(self._composite(descriptor("i", "wrGeooverlay", x, y)) for x, y in self._origins)
            ),
        )
        return (
            await asyncio.to_thread(self._compose_tiles, topography, 512, self._columns),
            await asyncio.to_thread(self._compose_tiles, overlay, 512, self._columns),
        )

    def _compose_tiles(self, tiles: list[bytes], size: int, columns: int) -> bytes:
        canvas = Image.new("RGBA", (columns * size, len(tiles) // columns * size))
        for index, raw in enumerate(tiles):
            image = Image.open(BytesIO(raw)).convert("RGBA").resize((size, size))
            canvas.alpha_composite(image, ((index % columns) * size, (index // columns) * size))
        out = BytesIO()
        canvas.save(out, "PNG")
        return out.getvalue()

    async def _radar_layer(self, timestep: dict[str, Any], x0: int, y0: int) -> bytes:
        # Zoom-7 tiles cover 4x4 zoom-8 tiles; scale 2 selects the 2x2 quadrant at x0/y0.
        x7, y7 = x0 // 4 * 2, y0 // 4 * 2
        quadrant_x, quadrant_y = x0 // 2 % 2, y0 // 2 % 2
        layers = timestep.get("layers") or {}
        entries = []
        for tiles in self.layer.tiles:
            europe = (layers.get("europe") or {}).get(tiles.key)
            global_layer = (layers.get("global") or {}).get(tiles.key)
            if not europe or not global_layer:
                continue
            border_time = global_layer.get("borderTimePath") or global_layer["timePath"]
            entries.append(
                f"{tiles.composite_type}|2;;{quadrant_x};{quadrant_y};false|"
                f"{_layer_path(europe, europe['timePath'])}/ZL7/522{tiles.tile_suffix}/{x7}_{y7}.png;"
                f"{_layer_path(global_layer, border_time)}/ZL7/522/border/{x7}_{y7}.png"
            )
        if not entries:
            raise ValueError("No WetterOnline radar layer for this timestep")
        # The composite service draws "$"-separated entries in order, so rain covers clouds.
        return await self._composite("$".join(entries), timestep["id"])

    async def _radar_layers(self, timestep: dict[str, Any]) -> list[bytes]:
        layers = await asyncio.gather(
            *(self._radar_layer(timestep, x, y) for x, y in self._origins),
            return_exceptions=True,
        )
        tiles = [layer if isinstance(layer, bytes) else b"" for layer in layers]
        if not any(tiles):
            raise ValueError(f"No WetterOnline radar tiles for {timestep['id']}")
        return tiles

    def _compose_frame(
        self, base: tuple[bytes, bytes | None], radar_layers: list[bytes], label: str
    ) -> Image.Image:
        background, overlay = base
        image = Image.open(BytesIO(background)).convert("RGBA")
        for (x, y), radar in zip(self._origins, radar_layers, strict=True):
            if radar:
                layer = Image.open(BytesIO(radar)).convert("RGBA").resize((512, 512))
                image.alpha_composite(layer, ((x - self._left) * 256, (y - self._top) * 256))
        if overlay:
            image.alpha_composite(Image.open(BytesIO(overlay)).convert("RGBA"))
        draw = ImageDraw.Draw(image)
        px, py = self._marker
        draw.ellipse(
            (px - 10, py - 10, px + 10, py + 10),
            fill="#00a7d1",
            outline="white",
            width=3,
        )
        image = image.crop(self._crop)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 738, 768, 768), fill=(0, 0, 0, 175))
        draw.text((10, 746), f"{label} · {self.layer.credits}", fill="white")
        return image

    def _animation_steps(
        self, period: RadarPeriod, metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = metadata["timesteps"]
        if period is CURRENT:
            index = int(metadata["defaultIndex"])
            return steps[max(0, index - 6) : index + 7]
        if period is TOMORROW:
            # WetterOnline delivers several days and filters them to the local calendar day.
            tomorrow = dt_util.now().date() + timedelta(days=1)
            return [
                step
                for step in steps
                if (time := _step_time(step["id"])) and dt_util.as_local(time).date() == tomorrow
            ]
        return steps

    async def _cached(
        self, key: str, max_age: timedelta, render: Callable[[], Awaitable[bytes | None]]
    ) -> bytes | None:
        cached = self._cache.get(key)
        if cached and datetime.now(UTC) - cached[0] < max_age:
            return cached[1]
        async with self._locks[key]:
            cached = self._cache.get(key)
            if cached and datetime.now(UTC) - cached[0] < max_age:
                return cached[1]
            try:
                image = await render()
            except ClientError, TimeoutError, KeyError, ValueError, OSError:
                image = None
            if image is None:
                return cached[1] if cached else None
            self._cache[key] = (datetime.now(UTC), image)
            return image

    async def current(self) -> bytes | None:
        """Return a cached current radar PNG."""
        return await self._cached("current", RADAR_INTERVAL, self._render_current)

    async def animation(self, period: RadarPeriod = CURRENT) -> bytes | None:
        """Return a cached radar GIF for the period."""
        return await self._cached(
            period.key, period.max_age, lambda: self._render_animation(period)
        )

    async def _render_current(self) -> bytes:
        metadata, base = await asyncio.gather(self._metadata(CURRENT), self._base_map())
        step = metadata["timesteps"][metadata["defaultIndex"]]
        radar = await self._radar_layers(step)
        image = await asyncio.to_thread(self._compose_frame, base, radar, _label(step["id"]))
        out = BytesIO()
        await asyncio.to_thread(image.convert("RGB").save, out, "PNG")
        return out.getvalue()

    async def _render_animation(self, period: RadarPeriod) -> bytes | None:
        metadata, base = await asyncio.gather(self._metadata(period), self._base_map())
        steps = self._animation_steps(period, metadata)
        layers = await asyncio.gather(
            *(self._radar_layers(step) for step in steps), return_exceptions=True
        )
        frames = [
            await asyncio.to_thread(self._compose_frame, base, layer, _label(step["id"]))
            for step, layer in zip(steps, layers, strict=True)
            if isinstance(layer, list)
        ]
        if not frames:
            return None
        duration = min(MAX_FRAME_MS, ANIMATION_LOOP_MS // len(frames))
        return await asyncio.to_thread(_encode_gif, frames, duration)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WetterOnlineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up weather, rain, and cloud radar cameras."""
    coordinator = entry.runtime_data
    location = coordinator.data.location
    session = async_get_clientsession(hass)
    async_add_entities(
        WetterOnlineRadarCamera(coordinator, renderer, period)
        for renderer in (
            RadarRenderer(session, location.latitude, location.longitude, layer)
            for layer in (WEATHER, RAIN, CLOUDS)
        )
        for period in (None, CURRENT, TODAY, TOMORROW)
    )


class WetterOnlineRadarCamera(Camera):
    """A WetterOnline radar still image or animation camera."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WeatherOnlineDataUpdateCoordinator,
        renderer: RadarRenderer,
        period: RadarPeriod | None,
    ) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.renderer = renderer
        self.period = period
        layer = renderer.layer
        self._attr_translation_key = (
            f"{layer.translation_key}_{period.key}" if period else layer.translation_key
        )
        self._attr_unique_id = (
            f"{coordinator.data.location.gid}_{layer.unique_id_key}_"
            f"{period.key if period else 'current'}"
        )
        self._attr_device_info = coordinator.device_info
        self.content_type = "image/gif" if period else "image/png"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if self.period:
            return await self.renderer.animation(self.period)
        return await self.renderer.current()
