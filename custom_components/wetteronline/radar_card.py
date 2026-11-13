"""Radar card: frame API and dashboard card for WetterOnline radar animations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiohttp import web
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .camera import (
    ANIMATION_PERIODS,
    CURRENT,
    DEFAULT_ZOOM,
    LAYERS,
    RADAR_RENDERERS,
    WEATHER,
    ZOOM_LEVELS,
    RadarFrames,
    RadarPeriod,
    RadarRenderer,
    _step_time,
    max_pan,
)
from .const import DOMAIN

CARD_URL = "/wetteronline_static/wetteronline-radar-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "wetteronline-radar-card.js"
API_URL = "/api/wetteronline/radar"


async def async_setup_radar_card(hass: HomeAssistant) -> None:
    """Serve the radar card, load it in the frontend, and register the frame API."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    # The frontend is always loaded in Home Assistant, but not in the tests.
    if "frontend" in hass.config.components:
        # The content hash makes browsers load a changed card even without a new version.
        version = await hass.async_add_executor_job(_file_hash, CARD_PATH)
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    hass.http.register_view(RadarFramesView())
    hass.http.register_view(RadarFrameView())


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Selection:
    """The radar frames requested for a WetterOnline location."""

    renderer: RadarRenderer
    period: RadarPeriod
    zoom: int
    pan_x: int
    pan_y: int
    center: tuple[float, float] | None
    location_name: str

    @property
    def query(self) -> str:
        """Return the query string that selects these frames again."""
        query = (
            f"layer={self.renderer.layer.key}&period={self.period.key}&zoom={self.zoom}"
            f"&pan_x={self.pan_x}&pan_y={self.pan_y}"
        )
        if self.center:
            query += f"&lat={self.center[0]:.5f}&lon={self.center[1]:.5f}"
        return query

    async def frames(self) -> RadarFrames:
        """Return the rendered frames."""
        try:
            frames = await self.renderer.frames(
                self.period, self.zoom, self.pan_x, self.pan_y, self.center
            )
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        if frames is None:
            raise web.HTTPServiceUnavailable(text="WetterOnline radar is not available")
        return frames


def _number[T: (int, float)](request: web.Request, name: str, kind: type[T], default: T) -> T:
    try:
        return kind(request.query.get(name, default))
    except ValueError as err:
        raise web.HTTPBadRequest(text=f"Invalid {name}") from err


def _selection(request: web.Request, entity_id: str) -> Selection:
    """Return the frames requested for the location of a WetterOnline entity."""
    hass = request.app[KEY_HASS]
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != DOMAIN or entry.config_entry_id is None:
        raise web.HTTPNotFound
    renderers = hass.data.get(RADAR_RENDERERS, {}).get(entry.config_entry_id)
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if not renderers or config_entry is None:
        raise web.HTTPNotFound
    # Without parameters, a radar camera opens its own layer and period.
    unique_id = entry.unique_id
    layer_key = request.query.get("layer") or next(
        (layer.key for layer in LAYERS if f"_{layer.unique_id_key}_" in unique_id), WEATHER.key
    )
    period_key = request.query.get("period") or next(
        (period.key for period in ANIMATION_PERIODS if unique_id.endswith(f"_{period.key}")),
        CURRENT.key,
    )
    periods = {period.key: period for period in ANIMATION_PERIODS}
    zoom = _number(request, "zoom", int, DEFAULT_ZOOM)
    if layer_key not in renderers or period_key not in periods or zoom not in ZOOM_LEVELS:
        raise web.HTTPBadRequest(text="Unsupported layer, period, or zoom")
    center = None
    if "lat" in request.query or "lon" in request.query:
        latitude = _number(request, "lat", float, 0.0)
        longitude = _number(request, "lon", float, 0.0)
        if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
            raise web.HTTPBadRequest(text="Invalid lat or lon")
        center = (latitude, longitude)
    return Selection(
        renderer=renderers[layer_key],
        period=periods[period_key],
        zoom=zoom,
        pan_x=_number(request, "pan_x", int, 0),
        pan_y=_number(request, "pan_y", int, 0),
        center=center,
        location_name=config_entry.title,
    )


class RadarFramesView(HomeAssistantView):
    """List the frames of a radar animation."""

    url = API_URL + "/{entity_id}"
    name = "api:wetteronline:radar"

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        """Render the frames if needed and return their times, URLs, and map section."""
        selection = _selection(request, entity_id)
        frames = await selection.frames()
        renderer, timeline, view = selection.renderer, frames.timeline, frames.view

        def iso(time: datetime | None) -> str | None:
            return time.isoformat() if time else None

        return self.json(
            {
                "layer": renderer.layer.key,
                "layers": [layer.key for layer in LAYERS],
                "period": selection.period.key,
                "periods": [period.key for period in ANIMATION_PERIODS],
                "zoom": selection.zoom,
                "zoom_levels": list(ZOOM_LEVELS),
                "pan_x": selection.pan_x,
                "pan_y": selection.pan_y,
                "max_pan": max_pan(selection.zoom),
                "location": {
                    "name": selection.location_name,
                    "latitude": renderer.latitude,
                    "longitude": renderer.longitude,
                },
                # World pixels of the frames' top-left corner, to place markers on them.
                "view": {"zoom": view.zoom, "x": view.origin[0], "y": view.origin[1], "size": 768},
                "now": dt_util.utcnow().isoformat(),
                "start": iso(timeline.start if timeline else None),
                "end": iso(timeline.end if timeline else None),
                "credits": renderer.layer.credits,
                "frames": [
                    {
                        "id": step_id,
                        "time": iso(_step_time(step_id)),
                        "url": f"{API_URL}/{entity_id}/{step_id}?{selection.query}",
                    }
                    for step_id in frames.step_ids
                ],
            }
        )


class RadarFrameView(HomeAssistantView):
    """Return one radar frame as WebP image."""

    url = API_URL + "/{entity_id}/{step_id}"
    name = "api:wetteronline:radar:frame"

    async def get(self, request: web.Request, entity_id: str, step_id: str) -> web.Response:
        """Return the cached frame image."""
        frames = await _selection(request, entity_id).frames()
        if step_id not in frames.step_ids:
            raise web.HTTPNotFound
        return web.Response(
            body=frames.images[frames.step_ids.index(step_id)],
            content_type="image/webp",
            headers={"Cache-Control": "private, max-age=300"},
        )
