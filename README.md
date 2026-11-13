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