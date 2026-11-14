# WetterOnline for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/GLG9/home-assistant-wetteronline)](https://github.com/GLG9/home-assistant-wetteronline/releases)
[![Validate](https://github.com/GLG9/home-assistant-wetteronline/actions/workflows/validate.yml/badge.svg)](https://github.com/GLG9/home-assistant-wetteronline/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Unofficial Home Assistant integration for the freely accessible location pages on
[WetterOnline](https://www.wetteronline.de/). No account or API key is required.

> [!IMPORTANT]
> WetterOnline does not provide a supported public API. This integration reads
> structured data embedded in the public website. Website changes can temporarily
> break individual entities until the integration is updated.

## Features

- Setup and reconfiguration through the Home Assistant user interface
- Search by city, postal code, WetterOnline path, or complete location URL
- Support for multiple locations
- Current conditions and a native Home Assistant weather entity
- Hourly forecast for up to 49 hours
- Daily forecast for up to 14 days
- Sensors for temperature, apparent temperature, dew point, pressure, humidity,
  wind speed, wind direction, gusts, visibility, precipitation, UV index, sunshine,
  smog, and WetterOnline weather symbols
- Additional data for pollen, warnings, sunrise and sunset, moon information,
  forecast text, editorial content, and nearby water stations when available
- Location-centred WetterOnline weather radar (clouds and precipitation), rain radar,
  and cloud radar cameras, each as a current image, a current animation, and hourly
  animations for today (observed radar since midnight, then forecast), tomorrow, and
  in two to four days (disabled by default)
- A radar dashboard card to switch map and day, pause, step through the hours, zoom,
  move the map, and center it on your phone or your own places
- Diagnostics and migration from the original 1.x config-entry format
- Updates every 15 minutes

The exact entities depend on the data WetterOnline provides for the selected location.

## Installation with HACS

### Recommended: add the repository automatically

HACS must already be installed and configured in Home Assistant.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=GLG9&repository=home-assistant-wetteronline&category=integration)

1. Select **Open link** and choose your Home Assistant instance.
2. HACS opens the WetterOnline repository.
3. Select **Download** and install the latest release.
4. Restart Home Assistant when HACS asks you to do so.
5. Continue with [Configure the integration](#configure-the-integration).

### Add the custom repository manually

1. Open **HACS** in Home Assistant.
2. Select the three-dot menu in the upper-right corner.
3. Select **Custom repositories**.
4. Enter `https://github.com/GLG9/home-assistant-wetteronline`.
5. Select **Integration** as the category and choose **Add**.
6. Open **WetterOnline**, select **Download**, and install the latest release.
7. Restart Home Assistant.

## Manual installation without HACS

1. Download the source code for the latest release.
2. Copy `custom_components/wetteronline` into your Home Assistant configuration so
   the final path is `/config/custom_components/wetteronline`.
3. Restart Home Assistant.
4. Continue with [Configure the integration](#configure-the-integration).

Updates installed manually must also be applied manually.

## Configure the integration

[![Open your Home Assistant instance and start setting up WetterOnline.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wetteronline)

Alternatively:

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **WetterOnline**.
4. Enter one of the following:
   - a city, for example `Berlin`
   - a postal code, for example `10115`
   - a WetterOnline path, for example `/wetter/berlin`
   - a complete WetterOnline location URL
5. Select the correct result when more than one location matches.

To change an existing location, open the integration entry and select
**Reconfigure**. You can add the integration multiple times for different places.

Select **Configure** on the integration entry to show the time and timeline of the
radar images at the top instead of the bottom.

## Radar card

The integration ships a dashboard card that shows the radar frames with controls
instead of a fast-running animation. It is loaded automatically; no extra resource
or HACS frontend repository is needed.

- Switch between now, today, tomorrow, and the next three days
- Switch between weather radar (clouds and precipitation), rain radar, and cloud radar
- Play, pause, step frame by frame, drag the slider, or swipe over the map
- Zoom in four steps (about the size of Germany, overview, ×2, ×4) and move the zoomed map
  with the arrows at its edges, within the area of the widest step
- Center the map on the WetterOnline location, on your phone's position, or on your own
  places, or show all of Germany
- Views one move or zoom step away are prepared in the background, so they open quickly

Add it with **Add card → WetterOnline Radar**, or in YAML:

```yaml
type: custom:wetteronline-radar-card
entity: camera.berlin_weather_radar
```

`entity` can be any WetterOnline entity of the location; a radar camera also selects
its map and period when the card opens. With "My location", the map follows the phone
once it moved an eighth of the map away. Optional settings:

| Option | Default | Description |
| --- | --- | --- |
| `title` | none | Card title |
| `layer` | from the entity | Map when opened: `weather`, `rain`, or `clouds` |
| `period` | from the entity | `animation` (now), `today`, `tomorrow`, `in_2_days`, `in_3_days`, or `in_4_days` |
| `zoom` | `7`; `6` with `center: germany` | Zoom level when opened: `6` (about the size of Germany), `7` (overview), `8` (×2), or `9` (×4) |
| `center` | `location` | Center when opened: `location`, `tracker`, `germany`, or the name of a place |
| `tracker` | own person | Person or device tracker for "My location"; by default the person of the user looking at the card |
| `places` | none | Own centers, each with `name`, `latitude`, and `longitude` |
| `frame_duration` | `1000` | Milliseconds per frame while playing |
| `autoplay` | `true` | Start playing when opened |
| `periods` | all | Periods offered as buttons, for example `[animation, today, tomorrow]` |
| `layers` | all | Maps offered as buttons, for example `[weather, rain]` |

For example, with an own place to check the weather at a holiday home:

```yaml
type: custom:wetteronline-radar-card
entity: camera.berlin_weather_radar
places:
  - name: Holiday home
    latitude: 54.18
    longitude: 7.89
```

## Troubleshooting

### WetterOnline is not shown after installation

- Confirm that `/config/custom_components/wetteronline/manifest.json` exists.
- Restart Home Assistant completely; reloading YAML is not sufficient.
- Clear the browser cache or reload the Home Assistant frontend.
- Check **Settings → System → Logs** for messages containing `wetteronline`.

### Setup or updates fail

- Verify that Home Assistant can reach `www.wetteronline.de`.
- Try a complete WetterOnline location URL instead of only a city name.
- Check whether the public WetterOnline page for the location is available.
- Download the latest release because WetterOnline website changes may require a
  parser update.

When reporting a problem, attach the integration diagnostics from
**Settings → Devices & services → WetterOnline → Download diagnostics**. Remove any
information you do not want to share before uploading it publicly.

## Data source and attribution

All weather data is provided by WetterOnline. The rain radar uses WetterOnline
precipitation layers over map data from © OpenStreetMap contributors; the weather and
cloud radars use WetterOnline satellite and precipitation layers over the WetterOnline
radar map. This project is
not affiliated with or endorsed by WetterOnline.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run pytest
```

The repository also runs Ruff, pytest, Home Assistant Hassfest, and HACS validation
through GitHub Actions.

## License

MIT — see [LICENSE](LICENSE).