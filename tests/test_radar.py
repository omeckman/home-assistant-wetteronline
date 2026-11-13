"""Radar projection tests."""

import base64
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from aiohttp import ClientSession
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from PIL import Image

from custom_components.wetteronline.camera import (
    CLOUDS,
    CURRENT,
    IN_2_DAYS,
    IN_3_DAYS,
    IN_4_DAYS,
    TODAY,
    TOMORROW,
    WEATHER,
    ZOOM_LEVELS,
    RadarRenderer,
    Timeline,
    _label,
    _step_time,
    _world,
    max_pan,
)


def test_web_mercator_tile() -> None:
    x, y = _world(52.517, 13.4)
    assert (int(x), int(y)) == (137, 83)


def test_view_stays_inside_fetched_blocks() -> None:
    """Locations anywhere inside a tile get a fully covered 768 px view at every zoom."""
    for latitude, longitude in ((52.517, 13.4), (48.14, 11.58), (50.94, 6.96), (53.55, 10.0)):
        renderer = RadarRenderer(None, latitude, longitude)  # type: ignore[arg-type]
        for zoom in ZOOM_LEVELS:
            view = renderer.view(zoom)
            left, top, right, bottom = view.crop
            assert left >= 0 and top >= 0
            assert right <= view.columns * 512 and bottom <= view.rows * 512
            assert view.origins[0] == (view.left, view.top)
            assert all(x % 2 == 0 and y % 2 == 0 for x, y in view.origins)
    with pytest.raises(ValueError):
        renderer.view(6)


def test_moved_views_cover_exactly_the_overview() -> None:
    """Half-view steps reach the edges of the zoom-7 overview but not beyond."""
    renderer = RadarRenderer(None, 48.14, 11.58)  # type: ignore[arg-type]
    overview = renderer.view(7)
    overview_left = overview.origin[0] / 2**7
    overview_right = (overview.origin[0] + 768) / 2**7
    for zoom in ZOOM_LEVELS:
        limit = max_pan(zoom)
        for pan_x in range(-limit, limit + 1):
            for pan_y in range(-limit, limit + 1):
                view = renderer.view(zoom, pan_x, pan_y)
                left, top, right, bottom = view.crop
                assert left >= 0 and top >= 0
                assert right <= view.columns * 512 and bottom <= view.rows * 512
                # The location marker moves by half a view per step.
                assert abs(view.marker[0] - view.center[0] + pan_x * 384) <= 1
        # In world units of zoom 0, the outermost views end at the overview's edges.
        scale = 2**zoom
        assert renderer.view(zoom, -limit, 0).origin[0] / scale == pytest.approx(
            overview_left, abs=2 / scale
        )
        assert (renderer.view(zoom, limit, 0).origin[0] + 768) / scale == pytest.approx(
            overview_right, abs=2 / scale
        )
    assert (max_pan(7), max_pan(8), max_pan(9)) == (0, 1, 3)
    with pytest.raises(ValueError):
        renderer.view(8, 2, 0)


def test_card_views_snap_to_half_tiles() -> None:
    """Nearby centers, e.g. a moving phone, share the same frames."""
    renderer = RadarRenderer(None, 52.517, 13.4)  # type: ignore[arg-type]
    first = renderer.view(8, center=(48.1400, 11.5800), snap=True)
    nearby = renderer.view(8, center=(48.1405, 11.5806), snap=True)
    exact = renderer.view(8, center=(48.1400, 11.5800))

    assert first.origin == nearby.origin
    assert first.marker != nearby.marker
    assert exact.center == exact.marker


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

        await renderer._radar_layers(_timestep("20261113-0530-1"), renderer.view())

    descriptors = sorted(_descriptor(call.args[0]) for call in renderer._fetch.await_args_list)
    assert renderer.view().origins == [(136, 82), (138, 82), (136, 84), (138, 84)]
    assert descriptors == sorted(
        f"r|2;;{qx};{qy};false|area/eu/2026/11/13/05/30/v1/ZL7/522/sprite/{tile}.png;"
        f"area/gl/2026/11/13/05/30/v2/ZL7/522/border/{tile}.png"
        for tile, qx, qy in (("68_40", 0, 1), ("68_40", 1, 1), ("68_42", 0, 0), ("68_42", 1, 0))
    )


async def test_radar_tiles_scale_with_zoom() -> None:
    """Higher zoom levels request smaller parts of the zoom-7 radar tile."""
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._fetch = AsyncMock(return_value=b"tile")  # type: ignore[method-assign]
        step = _timestep("20261113-0530-1")
        await renderer._radar_layer(step, 68, 40, zoom=7)
        zoom_7 = _descriptor(renderer._fetch.await_args.args[0])
        # Zoom-9 tile 278 is in zoom-7 tile 69, the third quarter of the even pair 68.
        await renderer._radar_layer(step, 278, 166, zoom=9)
        zoom_9 = _descriptor(renderer._fetch.await_args.args[0])

    assert zoom_7.startswith("r|1;;0;0;false|area/eu/2026/11/13/05/30/v1/ZL7/522/sprite/68_40.png;")
    assert zoom_9.startswith("r|4;;3;3;false|area/eu/2026/11/13/05/30/v1/ZL7/522/sprite/68_40.png;")


async def test_card_frames_have_no_footer_and_are_cached() -> None:
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "defaultIndex": 1,
                "timesteps": _hours(datetime(2026, 11, 13, tzinfo=UTC), 3),
            }
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            return_value=[b"", b"", b"", b""]
        )

        frames = await renderer.frames(CURRENT, 8)
        again = await renderer.frames(CURRENT, 8)

    assert frames is again
    assert renderer._metadata.await_count == 1
    assert frames.step_ids == ("20261113-0000-1", "20261113-0100-1", "20261113-0200-1")
    image = Image.open(BytesIO(frames.images[0]))
    assert image.format == "WEBP"
    assert image.size == (768, 768)
    # No footer band darkens the bottom of the map.
    assert (
        sum(abs(a - b) for a, b in zip(image.getpixel((700, 760)), (220, 231, 237), strict=True))
        < 12
    )


async def test_weather_radar_draws_rain_over_clouds() -> None:
    step = _timestep("20261113-0530-1", "clouds")
    step["layers"]["europe"]["rain"] = step["layers"]["europe"]["clouds"]
    step["layers"]["global"]["rain"] = step["layers"]["global"]["clouds"]
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4, WEATHER)
        renderer._fetch = AsyncMock(return_value=b"tile")  # type: ignore[method-assign]
        await renderer._radar_layer(step, 136, 82)

    clouds, rain = _descriptor(renderer._fetch.await_args.args[0]).split("$")
    assert clouds.startswith("c|2;;0;1;false|area/eu/2026/11/13/05/30/v1/ZL7/522/68_40.png;")
    assert rain.startswith("r|2;;0;1;false|area/eu/2026/11/13/05/30/v1/ZL7/522/sprite/68_40.png;")


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
        background, overlay = await renderer._base_map(renderer.view())

    assert cloud_descriptor.startswith("c|2;;0;1;false|area/eu/2026/11/13/05/30/v1/ZL7/522/68_40")
    assert background and overlay
    descriptors = {call.args[0] for call in renderer._composite.await_args_list}
    assert "topo|1;;0;0|geo/topo/v4/ZL8/512/136_82.jpg" in descriptors
    assert "i|1;;0;0|geo/overlay/v29/ZL8/512/136_82.png" in descriptors


def _hours(start: datetime, count: int, minutes: int = 60) -> list[dict]:
    return [
        {"id": f"{start + timedelta(minutes=minutes * index):%Y%m%d-%H%M}-1"}
        for index in range(count)
    ]


async def test_today_combines_observations_since_midnight_with_forecast(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-13T07:50:00+00:00")  # 08:50 local
    # Observations every 5 minutes from 23:30 local, forecast hourly from 09:00 local.
    past = _hours(datetime(2026, 11, 12, 22, 30, tzinfo=UTC), 105, minutes=5)
    forecast = _hours(datetime(2026, 11, 13, 8, tzinfo=UTC), 25)
    metadata = {"periodLast12h": {"timesteps": past}, "periodPrognose24h": {"timesteps": forecast}}
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(side_effect=metadata.get)  # type: ignore[method-assign]

        steps = await renderer._animation_steps(TODAY, dt_util.now())

    assert [call.args[0] for call in renderer._metadata.await_args_list] == [
        "periodLast12h",
        "periodPrognose24h",
    ]
    local_hours = [dt_util.as_local(_step_time(step["id"])).hour for step in steps]
    assert local_hours == list(range(24))


async def test_tomorrow_animation_uses_local_calendar_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-13T10:00:00+00:00")
    steps = _hours(datetime(2026, 11, 13, 22, tzinfo=UTC), 98)  # 23:00 today to 00:00 + 5
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"defaultIndex": 0, "timesteps": steps}
        )

        tomorrow = await renderer._animation_steps(TOMORROW, dt_util.now())
        in_2_days = await renderer._animation_steps(IN_2_DAYS, dt_util.now())
        in_3_days = await renderer._animation_steps(IN_3_DAYS, dt_util.now())
        in_4_days = await renderer._animation_steps(IN_4_DAYS, dt_util.now())
        current = await renderer._animation_steps(CURRENT, dt_util.now())

    assert tomorrow == steps[1:25]
    assert in_2_days == steps[25:49]
    assert in_3_days == steps[49:73]
    assert in_4_days == steps[73:97]
    assert current == steps[:7]


async def test_forecast_animation_loops_before_dashboard_refresh(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-13T10:00:00+00:00")
    steps = _hours(datetime(2026, 11, 13, 23, tzinfo=UTC), 24)
    async with ClientSession() as session:
        renderer = RadarRenderer(session, 52.517, 13.4)
        renderer._metadata = AsyncMock(  # type: ignore[method-assign]
            return_value={"defaultIndex": 0, "timesteps": steps}
        )
        renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
        renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
            return_value=[b"", b"", b"", b""]
        )

        animation = await renderer.animation(TOMORROW)

    assert animation is not None
    image = Image.open(BytesIO(animation))
    assert image.n_frames == 24
    assert image.info["duration"] * image.n_frames <= 9000


async def test_frame_label_uses_local_weekday_and_language(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    time = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)

    assert _label(time, "de") == "Fr 15:00"
    assert _label(time, "en") == "Fri 15:00"
    assert RadarRenderer(None, 0, 0, language="de-CH").language == "de"  # type: ignore[arg-type]
    assert RadarRenderer(None, 0, 0, language="fr").language == "en"  # type: ignore[arg-type]


async def test_timeline_marks_now(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    now = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)  # 12:00 local
    current = [now - timedelta(minutes=90), now + timedelta(minutes=90)]
    today = Timeline.for_day(dt_util.as_local(now).date(), now)

    assert Timeline.for_frames(current, now).position(now) == 0.5
    assert dt_util.as_local(today.start).hour == 0
    assert today.end - today.start == timedelta(hours=24)
    assert today.position(now) == 0.5
    assert Timeline.for_day(date(2026, 11, 14), now).now is None


async def test_timeline_ticks_use_local_hours(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    timeline = Timeline(
        datetime(2026, 11, 13, 23, tzinfo=UTC), datetime(2026, 11, 14, 22, tzinfo=UTC), None
    )

    local_hours = [dt_util.as_local(tick).hour for tick in timeline.ticks()]
    assert local_hours == [0, 6, 12, 18]
    day = Timeline.for_day(date(2026, 11, 14), datetime(2026, 11, 13, tzinfo=UTC))
    assert [dt_util.as_local(tick).hour for tick in day.ticks()] == [0, 6, 12, 18, 0]


async def test_footer_can_be_drawn_at_the_top() -> None:
    async with ClientSession() as session:
        bottom = RadarRenderer(session, 52.517, 13.4)
        top = RadarRenderer(session, 52.517, 13.4, footer_at_top=True)
        for renderer in (bottom, top):
            renderer._metadata = AsyncMock(  # type: ignore[method-assign]
                return_value={"defaultIndex": 0, "timesteps": [{"id": "20261113-0530-1"}]}
            )
            renderer._base_map = AsyncMock(return_value=_base_map())  # type: ignore[method-assign]
            renderer._radar_layers = AsyncMock(  # type: ignore[method-assign]
                return_value=[b"", b"", b"", b""]
            )

        bottom_image = Image.open(BytesIO(await bottom.current()))
        top_image = Image.open(BytesIO(await top.current()))

    map_color = (220, 231, 237)
    assert bottom_image.getpixel((700, 2)) == map_color
    assert bottom_image.getpixel((700, 765)) != map_color
    assert top_image.getpixel((700, 2)) != map_color
    assert top_image.getpixel((700, 765)) == map_color
