"""WetterOnline weather, rain, and cloud radar cameras."""

from __future__ import annotations

import asyncio
import base64
import math
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from io import BytesIO
from typing import Any, override
from urllib.parse import urlencode

from aiohttp import ClientError, ClientSession
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw, ImageFont

from . import WetterOnlineConfigEntry
from .const import ATTRIBUTION, CONF_TIMELINE_POSITION, RADAR_INTERVAL, TIMELINE_TOP
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
# Part of the GIF web palette, so the timeline is not dithered.
ACCENT = "#0099cc"
WEEKDAYS = {
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
NOW_LABELS = {"de": "jetzt", "en": "now"}


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
    day_offset: int | None = None
    enabled_default: bool = True


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
TODAY = RadarPeriod("today", "periodPrognose24h", timedelta(minutes=30), day_offset=0)
TOMORROW = RadarPeriod("tomorrow", "periodTomorrow", timedelta(minutes=30), day_offset=1)
IN_2_DAYS = RadarPeriod(
    "in_2_days", "periodDayThree", timedelta(minutes=30), day_offset=2, enabled_default=False
)
IN_3_DAYS = RadarPeriod(
    "in_3_days", "periodDayFour", timedelta(minutes=30), day_offset=3, enabled_default=False
)
# Beyond WetterOnline's own day periods; covered by periodDayFour until its forecast ends.
IN_4_DAYS = RadarPeriod(
    "in_4_days", "periodDayFour", timedelta(minutes=30), day_offset=4, enabled_default=False
)
# Observed radar periods for today's hours before now, smallest download first.
PAST_PERIODS = ((6, "periodLast6h"), (12, "periodLast12h"), (24, "periodLast24h"))


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


def _hourly_steps(steps: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    """Return the first step for every local full hour of a calendar day."""
    by_time: dict[datetime, dict[str, Any]] = {}
    for step in steps:
        time = _step_time(step["id"])
        if time and (local := dt_util.as_local(time)).date() == day and local.minute == 0:
            by_time.setdefault(time, step)
    return [by_time[time] for time in sorted(by_time)]


def _label(time: datetime, language: str) -> str:
    local = dt_util.as_local(time)
    return f"{WEEKDAYS[language][local.weekday()]} {local:%H:%M}"


@cache
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size)


@dataclass(frozen=True, slots=True)
class Timeline:
    """Time range shown as a progress bar below animation frames."""

    start: datetime
    end: datetime
    now: datetime | None

    @classmethod
    def for_frames(cls, times: list[datetime], now: datetime) -> Timeline:
        """Span the frames and mark now when it falls inside them."""
        return cls(times[0], times[-1], now if times[0] <= now <= times[-1] else None)

    @classmethod
    def for_day(cls, day: date, now: datetime) -> Timeline:
        """Span a local calendar day from 00:00 to 24:00."""
        start = dt_util.start_of_local_day(day)
        end = dt_util.start_of_local_day(day + timedelta(days=1))
        return cls(start, end, now if start <= now <= end else None)

    def position(self, time: datetime) -> float:
        """Return the relative position of a time on the bar."""
        span = (self.end - self.start).total_seconds()
        if span <= 0:
            return 0.0
        return min(max((time - self.start).total_seconds() / span, 0.0), 1.0)

    def ticks(self) -> list[datetime]:
        """Return local full hours at an interval that keeps the labels apart."""
        hours = (self.end - self.start).total_seconds() / 3600
        interval = 1 if hours <= 4 else 3 if hours <= 12 else 6
        time = self.start.replace(minute=self.start.minute // 30 * 30, second=0, microsecond=0)
        ticks = []
        while time <= self.end:
            local = dt_util.as_local(time)
            if time >= self.start and local.minute == 0 and local.hour % interval == 0:
                ticks.append(time)
            time += timedelta(minutes=30)
        return ticks


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
        self,
        session: ClientSession,
        latitude: float,
        longitude: float,
        layer: RadarLayer = RAIN,
        language: str = "en",
        footer_at_top: bool = False,
    ) -> None:
        self.session = session
        self.latitude = latitude
        self.longitude = longitude
        self.layer = layer
        self.language = language.split("-")[0] if language.split("-")[0] in WEEKDAYS else "en"
        self.footer_at_top = footer_at_top
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

    async def _metadata(self, period: str) -> dict[str, Any]:
        return await self._get_json(
            {"lg": "wr", "newMetadata": "true", "period": period, "type": "period"}
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
        self,
        base: tuple[bytes, bytes | None],
        radar_layers: list[bytes],
        step_id: str,
        timeline: Timeline | None = None,
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
        self._draw_footer(image, step_id, timeline)
        return image

    def _draw_footer(self, image: Image.Image, step_id: str, timeline: Timeline | None) -> None:
        time = _step_time(step_id)
        width, height = image.size
        footer_height = 120 if timeline and time else 68
        top = 0 if self.footer_at_top else height - footer_height
        band = Image.new("RGBA", image.size)
        ImageDraw.Draw(band).rectangle((0, top, width, top + footer_height), fill=(0, 0, 0, 170))
        image.alpha_composite(band)
        draw = ImageDraw.Draw(image)
        draw.text(
            (18, top + 6),
            _label(time, self.language) if time else step_id,
            fill="white",
            font=_font(50),
            stroke_width=1,
            stroke_fill="white",
        )
        credits_font = _font(17)
        credits_x = width - 18 - draw.textlength(self.layer.credits, font=credits_font)
        draw.text((credits_x, top + 26), self.layer.credits, fill="#d0d0d0", font=credits_font)
        if timeline and time:
            self._draw_timeline(draw, timeline, time, top + 70, width)

    def _draw_timeline(
        self, draw: ImageDraw.ImageDraw, timeline: Timeline, time: datetime, y: int, width: int
    ) -> None:
        left, right = 28, width - 28
        font = _font(20)

        def x_at(moment: datetime) -> float:
            return left + (right - left) * timeline.position(moment)

        def text_left(x: float, text: str) -> float:
            text_width = draw.textlength(text, font=font)
            return min(max(x - text_width / 2, 4), width - 4 - text_width)

        now_text = NOW_LABELS[self.language]
        now_x = x_at(timeline.now) if timeline.now else None
        now_left = text_left(now_x, now_text) if now_x is not None else None
        now_right = (now_left or 0) + draw.textlength(now_text, font=font)
        for tick in timeline.ticks():
            x = x_at(tick)
            draw.line((x, y - 4, x, y + 18), fill="#a0a0a0", width=2)
            text = f"{dt_util.as_local(tick):%H:%M}"
            tick_left = text_left(x, text)
            tick_right = tick_left + draw.textlength(text, font=font)
            if now_left is not None and tick_left < now_right + 10 and tick_right > now_left - 10:
                continue
            draw.text((tick_left, y + 22), text, fill="#d0d0d0", font=font)
        draw.rounded_rectangle((left, y, right, y + 14), radius=7, fill="#5a5a5a")
        frame_x = x_at(time)
        draw.rounded_rectangle((left, y, max(frame_x, left + 14), y + 14), radius=7, fill=ACCENT)
        if now_x is not None and now_left is not None:
            draw.line((now_x, y - 10, now_x, y + 22), fill="white", width=4)
            draw.text(
                (now_left, y + 22),
                now_text,
                fill="white",
                font=font,
                stroke_width=1,
                stroke_fill="white",
            )
        draw.ellipse(
            (frame_x - 12, y - 5, frame_x + 12, y + 19), fill=ACCENT, outline="white", width=3
        )

    async def _animation_steps(self, period: RadarPeriod, now: datetime) -> list[dict[str, Any]]:
        if period.day_offset is None:
            metadata = await self._metadata(period.api_name)
            index = int(metadata["defaultIndex"])
            steps: list[dict[str, Any]] = metadata["timesteps"]
            return steps[max(0, index - 6) : index + 7]
        # WetterOnline forecasts cover several days and are filtered to the local calendar day.
        names = [period.api_name]
        if period.day_offset == 0:
            # Today also shows the observed hours since midnight.
            hours = (now - dt_util.start_of_local_day(now)).total_seconds() / 3600
            names.insert(
                0, next((name for limit, name in PAST_PERIODS if hours <= limit), names[0])
            )
        metadata_list = await asyncio.gather(*(self._metadata(name) for name in names))
        steps = [step for metadata in metadata_list for step in metadata["timesteps"]]
        return _hourly_steps(steps, now.date() + timedelta(days=period.day_offset))

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
        metadata, base = await asyncio.gather(self._metadata(CURRENT.api_name), self._base_map())
        step = metadata["timesteps"][metadata["defaultIndex"]]
        radar = await self._radar_layers(step)
        image = await asyncio.to_thread(self._compose_frame, base, radar, step["id"])
        out = BytesIO()
        await asyncio.to_thread(image.convert("RGB").save, out, "PNG")
        return out.getvalue()

    async def _render_animation(self, period: RadarPeriod) -> bytes | None:
        now = dt_util.now()
        steps, base = await asyncio.gather(self._animation_steps(period, now), self._base_map())
        layers = await asyncio.gather(
            *(self._radar_layers(step) for step in steps), return_exceptions=True
        )
        available = [
            (step["id"], layer)
            for step, layer in zip(steps, layers, strict=True)
            if isinstance(layer, list)
        ]
        if not available:
            return None
        times = [time for step_id, _ in available if (time := _step_time(step_id))]
        if period.day_offset is not None:
            timeline: Timeline | None = Timeline.for_day(
                now.date() + timedelta(days=period.day_offset), now
            )
        else:
            timeline = Timeline.for_frames(times, now) if times else None
        frames = [
            await asyncio.to_thread(self._compose_frame, base, layer, step_id, timeline)
            for step_id, layer in available
        ]
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
    footer_at_top = entry.options.get(CONF_TIMELINE_POSITION) == TIMELINE_TOP
    async_add_entities(
        WetterOnlineRadarCamera(coordinator, renderer, period)
        for renderer in (
            RadarRenderer(
                session,
                location.latitude,
                location.longitude,
                layer,
                hass.config.language,
                footer_at_top,
            )
            for layer in (WEATHER, RAIN, CLOUDS)
        )
        for period in (None, CURRENT, TODAY, TOMORROW, IN_2_DAYS, IN_3_DAYS, IN_4_DAYS)
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
        self._attr_entity_registry_enabled_default = not period or period.enabled_default
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
