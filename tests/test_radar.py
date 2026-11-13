"""Radar projection tests."""

import base64
from io import BytesIO
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientSession
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from PIL import Image

from custom_components.wetteronline.camera import (
    CLOUDS,
    CURRENT,
    TODAY,
    TOMORROW,
    RadarRenderer,
    _world,
)


def test_web_mercator_tile() -> None:
    x, y = _world(52.517, 13.4)
    assert (int(x), int(y)) == (137, 83)


def test_view_stays_inside_fetched_blocks() -> None:
    """Locations anywhere inside a tile get a fully covered 768 px view."""
    for latitude, longitude in ((52.517, 13.4), (48.14, 11.58), (50.94, 6.96), (53.55, 10.0)):
        renderer = RadarRenderer(None, latitude, longitude)  # type: ignore[arg-type]
        left, top, right, bottom = renderer._crop
        assert left >= 0 and top >= 0
        assert right <= renderer._columns * 512 and bottom <= renderer._rows * 512
        assert renderer._origins[0] == (renderer._left, renderer._top)
        assert all(x % 2 == 0 and y % 2 == 0 for x, y in renderer._origins)


def _base_map() -> tuple[bytes, None]:
    out = BytesIO()
    Image.new("RGBA", (1024, 1024), "#dce7ed").save(out, "PNG")
    return out.getvalue(), None


def _timestep(step_id: str, layer: str = "rain") -> dict:
    def entry(path: str) -> dict:
        return {
            "path": path,
            "ptypPath": "area/",
            "timePath": ["2026", "11", "13", "05", "30", "v1"],
            "borderTimePath": ["2026", "11", "13", "05", "30", "v2"],
        }

    return {
        "id": step_id,
        "layers": {"europe": {layer: entry("eu")}, "global": {layer: entry("gl")}},
    }


def _descriptor(url: str) -> str:
    return base64.b64decode(parse_qs(urlparse(url).query)["tiles"][0]).decode()


async def test_current_radar_is_centered_and_cached() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"defaultIndex": 0, "timesteps": [{"id": "202607120000"}]}
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            return_value=[b"", b"", b"", b""]
        )

        first = await renderer.current()
        second = await renderer.current()

    assert first == second
    assert renderer._metadata.await_count == 1
    image = Image.open(BytesIO(first))
    assert image.size == (768, 768)
    assert image.getpixel((384, 384)) == (0, 167, 209)


async def test_animation_skips_unavailable_frames() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "defaultIndex": 1,
                "timesteps": [{"id": "old"}, {"id": "now"}, {"id": "future"}],
            }
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            side_effect=[ValueError("missing"), [b"", b"", b"", b""], ValueError("missing")]
        )

        animation = await renderer.animation()

    assert animation is not None
    image = Image.open(BytesIO(animation))
    assert image.format == "GIF"
    assert image.n_frames == 1


async def test_radar_tiles_select_matching_quadrant() -> None:
    """Every 2x2 zoom-8 block requests its own quarter of the zoom-7 tile."""
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._fetch = AsyncMock(return_value=b"tile")  # type: ignore[method-assign]

        await renderer._radar_layers(_timestep("20261113-0530-1"))

    descriptors = sorted(_descriptor(call.args[0]) for call in renderer._fetch.await_args_list)
    assert renderer._origins == [(136, 82), (138, 82), (136, 84), (138, 84)]
    assert descriptors == sorted(
        f"r|2;;{qx};{qy};false|area/eu/2026/11/13/05/30/v1/ZL7/522/sprite/{tile}.png;"
        f"area/gl/2026/11/13/05/30/v2/ZL7/522/border/{tile}.png"
        for tile, qx, qy in (("68_40", 0, 1), ("68_40", 1, 1), ("68_42", 0, 0), ("68_42", 1, 0))
    )


async def test_cloud_radar_uses_cloud_tiles_and_wetteronline_map() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4, CLOUDS)
        renderer._fetch = AsyncMock(return_value=b"tile")  # type: ignore[method-assign]
        await renderer._radar_layer(_timestep("20261113-0530-1", "clouds"), 136, 82)
        cloud_descriptor = _descriptor(renderer._fetch.await_args.args[0])

        renderer._get_json = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "minZoom": 2,
                "staticLayer": {
                    "path": "geo/",
                    "wrTopography": {"path": "topo/v4/", "type": ["png", "jpg"]},
                    "wrGeooverlay": {"path": "overlay/v29/", "type": ["png"]},
                },
            }
        )
        renderer._composite = AsyncMock(  # type: ignore[method-assign]
            return_value=_base_map()[0]
        )
        background, overlay = await renderer._base_map()

    assert cloud_descriptor.startswith("c|2;;0;1;false|area/eu/2026/11/13/05/30/v1/ZL7/522/68_40")
    assert background and overlay
    descriptors = {call.args[0] for call in renderer._composite.await_args_list}
    assert "topo|1;;0;0|geo/topo/v4/ZL8/512/136_82.jpg" in descriptors
    assert "i|1;;0;0|geo/overlay/v29/ZL8/512/136_82.png" in descriptors


async def test_tomorrow_animation_uses_local_calendar_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-13T10:00:00+00:00")
    steps = [
        {"id": step_id}
        for step_id in (
            "20261113-2200-1",  # 23:00 today
            "20261113-2300-1",  # 00:00 tomorrow
            "20261114-2200-1",  # 23:00 tomorrow
            "20261114-2300-1",  # 00:00 day after tomorrow
        )
    ]
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)

    assert renderer._animation_steps(TOMORROW, {"timesteps": steps}) == steps[1:3]
    assert renderer._animation_steps(TODAY, {"timesteps": steps}) == steps
    assert renderer._animation_steps(CURRENT, {"defaultIndex": 0, "timesteps": steps}) == steps


async def test_forecast_animation_loops_before_dashboard_refresh() -> None:
    steps = [{"id": f"20261114-{hour:02d}00-1"} for hour in range(24)]
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"defaultIndex": 0, "timesteps": steps}
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            return_value=[b"", b"", b"", b""]
        )

        animation = await renderer.animation(TODAY)

    assert animation is not None
    image = Image.open(BytesIO(animation))
    assert image.n_frames == 24
    assert image.info["duration"] * image.n_frames <= 9000
