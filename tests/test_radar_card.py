"""Radar card frame API tests."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.wetteronline.camera import MapView, RadarFrames, RadarRenderer
from custom_components.wetteronline.const import CONF_LOCATION, CONF_LOCATION_ID, DOMAIN
from custom_components.wetteronline.radar_card import CARD_URL

from .test_config_flow import sample_data

FRAMES = RadarFrames(
    ("20261113-0800-1", "20261113-0900-1"),
    (b"first", b"second"),
    None,
    MapView.around(52.517, 13.4, 8, snap=True),
)


async def _setup(hass: HomeAssistant) -> None:
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


async def test_frames_default_to_the_cameras_layer_and_period(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    await _setup(hass)
    client = await hass_client()
    with patch.object(RadarRenderer, "frames", autospec=True, return_value=FRAMES) as frames:
        response = await client.get("/api/wetteronline/radar/camera.berlin_rain_radar_tomorrow")
        data = await response.json()
        frame = await client.get(data["frames"][1]["url"])
        body = await frame.read()

    assert response.status == 200
    assert (data["layer"], data["period"], data["zoom"]) == ("rain", "tomorrow", 8)
    assert data["layers"] == ["weather", "rain", "clouds"]
    assert data["frames"][0] == {
        "id": "20261113-0800-1",
        "time": "2026-11-13T08:00:00+00:00",
        "url": "/api/wetteronline/radar/camera.berlin_rain_radar_tomorrow/20261113-0800-1"
        "?layer=rain&period=tomorrow&zoom=8&pan_x=0&pan_y=0",
    }
    assert data["location"] == {"name": "Berlin", "latitude": 52.517, "longitude": 13.4}
    assert (data["pan_x"], data["pan_y"], data["max_pan"]) == (0, 0, 3)
    assert data["view"] == {
        "zoom": 8,
        "x": FRAMES.view.origin[0],
        "y": FRAMES.view.origin[1],
        "size": 768,
    }
    # Berlin's center snapped to the half tile 137.5 at zoom 8, minus half a view.
    assert FRAMES.view.origin[0] == (137.5 - 1.5) * 256
    assert frame.status == 200
    assert frame.content_type == "image/webp"
    assert body == b"second"
    renderer, period, zoom, pan_x, pan_y, center = frames.await_args_list[0].args
    assert (renderer.layer.key, period.key, zoom, pan_x, pan_y, center) == (
        "rain",
        "tomorrow",
        8,
        0,
        0,
        None,
    )


async def test_frames_follow_the_selected_layer_period_and_zoom(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    await _setup(hass)
    client = await hass_client()
    with patch.object(RadarRenderer, "frames", autospec=True, return_value=FRAMES) as frames:
        # Any entity of the location works, e.g. the weather entity.
        response = await client.get(
            "/api/wetteronline/radar/weather.berlin?layer=clouds&period=in_3_days&zoom=9"
            "&pan_x=-3&pan_y=2&lat=48.13743&lon=11.57549"
        )
        data = await response.json()

    assert response.status == 200
    assert (data["layer"], data["period"], data["zoom"]) == ("clouds", "in_3_days", 9)
    assert (data["pan_x"], data["pan_y"], data["max_pan"]) == (-3, 2, 7)
    assert data["credits"] == "WetterOnline"
    assert data["frames"][0]["url"].endswith(
        "?layer=clouds&period=in_3_days&zoom=9&pan_x=-3&pan_y=2&lat=48.13743&lon=11.57549"
    )
    assert frames.await_args.args[3:] == (-3, 2, (48.13743, 11.57549))


async def test_invalid_requests_are_rejected(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _setup(hass)
    client = await hass_client()
    with patch.object(RadarRenderer, "frames", AsyncMock(return_value=FRAMES)):
        unknown_entity = await client.get("/api/wetteronline/radar/camera.unknown")
        bad_zoom = await client.get("/api/wetteronline/radar/weather.berlin?zoom=12")
        bad_period = await client.get("/api/wetteronline/radar/weather.berlin?period=yesterday")
        unknown_frame = await client.get("/api/wetteronline/radar/weather.berlin/20200101-0000-1")
        bad_lat = await client.get("/api/wetteronline/radar/weather.berlin?lat=95&lon=10")
        bad_number = await client.get("/api/wetteronline/radar/weather.berlin?pan_x=left")
    # The renderer rejects moving beyond the overview before it fetches anything.
    too_far = await client.get("/api/wetteronline/radar/weather.berlin?zoom=8&pan_x=4")
    with patch.object(RadarRenderer, "frames", AsyncMock(return_value=None)):
        unavailable = await client.get("/api/wetteronline/radar/weather.berlin")
    anonymous = await (await hass_client_no_auth()).get("/api/wetteronline/radar/weather.berlin")

    assert unknown_entity.status == 404
    assert bad_zoom.status == 400
    assert bad_period.status == 400
    assert unknown_frame.status == 404
    assert bad_lat.status == 400
    assert bad_number.status == 400
    assert too_far.status == 400
    assert unavailable.status == 503
    assert anonymous.status == 401


async def test_card_script_is_served(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    await _setup(hass)
    response = await (await hass_client()).get(CARD_URL)

    assert response.status == 200
    assert 'customElements.define("wetteronline-radar-card"' in await response.text()
