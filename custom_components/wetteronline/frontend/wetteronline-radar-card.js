// WetterOnline radar card: step through, pause, zoom, and move the radar frames of the
// WetterOnline integration. Served and loaded by the integration itself.

const API_URL = "/api/wetteronline/radar";
const REFRESH_MS = 10 * 60 * 1000;
// Views opened before are kept for a while, so going back to them needs no download.
const CACHE_MS = 5 * 60 * 1000;
const CACHED_VIEWS = 6;
const SWIPE_STEP_PX = 24;
const TRACKER_RELOAD_MS = 3000;
const DEFAULT_ZOOM = 7;
// At zoom 6, a view around the middle of Germany shows all of it.
const GERMANY = { latitude: 51.16, longitude: 10.45, zoom: 6 };
const SELECTION_KEYS = ["layer", "period", "zoom", "pan_x", "pan_y"];

const TEXT = {
  de: {
    periods: { animation: "Jetzt", today: "Heute", tomorrow: "Morgen" },
    layers: { weather: "Wetter", rain: "Regen", clouds: "Wolken" },
    now: "jetzt",
    loading: "Lade Radar …",
    error: "Radar nicht verfügbar",
    retry: "Erneut versuchen",
    play: "Abspielen",
    pause: "Pause",
    previous: "Zurück",
    next: "Weiter",
    zoomIn: "Näher",
    zoomOut: "Weiter weg",
    myLocation: "Mein Standort",
    germany: "Deutschland",
    recenter: "Zur Mitte",
    move: { left: "Nach links", right: "Nach rechts", up: "Nach oben", down: "Nach unten" },
    editor: {
      entity: "WetterOnline-Entität des Orts",
      layer: "Karte beim Öffnen",
      period: "Zeitraum beim Öffnen",
      zoom: "Zoomstufe beim Öffnen",
      frame_duration: "Dauer pro Bild",
      autoplay: "Automatisch abspielen",
      title: "Titel",
      tracker: "Mein Standort aus (Standard: eigene Person)",
      center: "Mitte beim Öffnen",
    },
  },
  en: {
    periods: { animation: "Now", today: "Today", tomorrow: "Tomorrow" },
    layers: { weather: "Weather", rain: "Rain", clouds: "Clouds" },
    now: "now",
    loading: "Loading radar …",
    error: "Radar not available",
    retry: "Retry",
    play: "Play",
    pause: "Pause",
    previous: "Previous",
    next: "Next",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    myLocation: "My location",
    germany: "Germany",
    recenter: "Back to center",
    move: { left: "Move left", right: "Move right", up: "Move up", down: "Move down" },
    editor: {
      entity: "WetterOnline entity of the location",
      layer: "Map when opened",
      period: "Period when opened",
      zoom: "Zoom level when opened",
      frame_duration: "Duration per frame",
      autoplay: "Play automatically",
      title: "Title",
      tracker: "My location from (default: own person)",
      center: "Center when opened",
    },
  },
};
const DAY_OFFSETS = { animation: 0, today: 0, tomorrow: 1, in_2_days: 2, in_3_days: 3, in_4_days: 4 };

const MARKER_COLORS = { location: "#00a7d1", tracker: "#ff9800", place: "#9c27b0" };

// Web Mercator world pixel of a coordinate at a zoom level, as used by the frames.
const worldPixel = (latitude, longitude, zoom) => {
  const size = 256 * 2 ** zoom;
  const lat = (Math.max(Math.min(latitude, 85.0511), -85.0511) * Math.PI) / 180;
  return [((longitude + 180) / 360) * size, ((1 - Math.asinh(Math.tan(lat)) / Math.PI) / 2) * size];
};

const languageOf = (hass) =>
  ((hass && (hass.locale?.language || hass.language)) || navigator.language || "en").split("-")[0];
const textFor = (hass) => TEXT[languageOf(hass)] || TEXT.en;

const STYLE = `
  :host { display: block; }
  [hidden] { display: none !important; }
  ha-card { overflow: hidden; }
  .title { padding: 12px 16px 0; font-size: 1.2em; font-weight: 500; }
  .chips { display: flex; gap: 6px; padding: 8px 12px 0; overflow-x: auto; scrollbar-width: none; }
  .chips::-webkit-scrollbar { display: none; }
  .chip {
    flex: none; border: 1px solid var(--divider-color); border-radius: 6px;
    background: none; color: var(--primary-text-color); padding: 4px 12px;
    font: inherit; font-size: 0.9em; cursor: pointer;
  }
  .chip.selected { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .viewport { position: relative; margin-top: 8px; aspect-ratio: 1; background: var(--secondary-background-color); touch-action: pan-y; user-select: none; }
  .viewport img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; transition: opacity 0.2s; }
  .viewport.busy img { opacity: 0.5; }
  .time {
    position: absolute; top: 8px; left: 8px; padding: 2px 10px; border-radius: 8px;
    background: rgba(0, 0, 0, 0.45); color: #fff; font-size: 1.6em; font-weight: 600;
    text-shadow: 0 0 3px #000; display: flex; align-items: center; gap: 8px;
  }
  .badge { font-size: 0.55em; font-weight: 600; background: #fff; color: #000; border-radius: 6px; padding: 1px 6px; text-shadow: none; }
  .credits { position: absolute; right: 6px; bottom: 4px; color: #fff; font-size: 0.7em; text-shadow: 0 0 2px #000, 0 0 2px #000; }
  .marker {
    position: absolute; width: 14px; height: 14px; margin: -10px 0 0 -10px; border-radius: 50%;
    border: 3px solid #fff; box-shadow: 0 0 3px rgba(0, 0, 0, 0.6); pointer-events: none;
  }
  .map-button {
    position: absolute; width: 36px; height: 36px; border: none; border-radius: 6px; padding: 0;
    background: rgba(0, 0, 0, 0.45); color: #fff; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
  }
  .map-button:hover { background: rgba(0, 0, 0, 0.65); }
  .move-left { left: 6px; top: 50%; transform: translateY(-50%); }
  .move-right { right: 6px; top: 50%; transform: translateY(-50%); }
  .move-up { top: 6px; left: 50%; transform: translateX(-50%); }
  .move-down { bottom: 6px; left: 50%; transform: translateX(-50%); }
  .recenter { left: 6px; bottom: 6px; }
  .spinner {
    position: absolute; top: 6px; right: 6px; width: 36px; height: 36px; border-radius: 6px;
    background: rgba(0, 0, 0, 0.45); display: flex; align-items: center; justify-content: center;
    pointer-events: none;
  }
  .spinner::after {
    content: ""; width: 16px; height: 16px; border-radius: 50%;
    border: 3px solid rgba(255, 255, 255, 0.3); border-top-color: #fff;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status {
    position: absolute; inset: 0; display: flex; flex-direction: column; gap: 8px;
    align-items: center; justify-content: center; color: var(--primary-text-color); text-align: center;
  }
  .status span { background: var(--card-background-color); padding: 6px 12px; border-radius: 8px; }
  .controls { display: flex; align-items: center; gap: 2px; padding: 4px 6px 0; }
  .icon-button {
    flex: none; width: 40px; height: 40px; border: none; border-radius: 6px; background: none;
    color: var(--primary-text-color); cursor: pointer; display: flex; align-items: center; justify-content: center;
  }
  .icon-button:disabled { color: var(--disabled-text-color); cursor: default; }
  .icon-button:not(:disabled):hover { background: var(--secondary-background-color); }
  .timeline { position: relative; flex: 1; min-width: 0; padding: 0 9px 22px; }
  .timeline input { width: calc(100% + 18px); margin: 0 -9px; accent-color: var(--primary-color); }
  .ticks { position: absolute; left: 9px; right: 9px; top: 26px; height: 18px; font-size: 0.75em; color: var(--secondary-text-color); }
  .ticks span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
  .ticks span.now { color: var(--primary-text-color); font-weight: 700; }
  .now-mark { position: absolute; top: 2px; width: 3px; height: 22px; margin-left: -1.5px; background: var(--primary-text-color); border-radius: 2px; pointer-events: none; }
  .spacer { height: 8px; }
`;

class WetterOnlineRadarCard extends HTMLElement {
  static getStubConfig(hass) {
    const entities = Object.values(hass.entities || {}).filter((entry) => entry.platform === "wetteronline");
    const entity = entities.find((entry) => entry.entity_id.startsWith("camera.")) || entities[0];
    return { entity: entity ? entity.entity_id : "" };
  }

  static getConfigForm() {
    const text = textFor(document.querySelector("home-assistant")?.hass);
    const options = (keys, labels) => keys.map((value) => ({ value, label: labels[value] || value }));
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { filter: { integration: "wetteronline" } } } },
        { name: "title", selector: { text: {} } },
        { name: "layer", selector: { select: { mode: "dropdown", options: options(["weather", "rain", "clouds"], text.layers) } } },
        {
          name: "period",
          selector: { select: { mode: "dropdown", options: options(Object.keys(DAY_OFFSETS), { ...text.periods, in_2_days: "+2", in_3_days: "+3", in_4_days: "+4" }) } },
        },
        { name: "zoom", selector: { number: { min: 6, max: 9, mode: "slider" } } },
        { name: "tracker", selector: { entity: { filter: [{ domain: "person" }, { domain: "device_tracker" }] } } },
        {
          name: "center",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "location", label: "WetterOnline" },
                { value: "tracker", label: text.myLocation },
                { value: "germany", label: text.germany },
              ],
            },
          },
        },
        { name: "frame_duration", selector: { number: { min: 200, max: 5000, step: 100, unit_of_measurement: "ms" } } },
        { name: "autoplay", selector: { boolean: {} } },
      ],
      computeLabel: (schema) => text.editor[schema.name] || schema.name,
    };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Please choose a WetterOnline entity");
    }
    this._config = { frame_duration: 1000, autoplay: true, ...config };
    this._config.places = (Array.isArray(config.places) ? config.places : [])
      .map((place) => ({ ...place, latitude: Number(place.latitude), longitude: Number(place.longitude) }))
      .filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude));
    const placeIndex = this._config.places.findIndex((place) => place.name === config.center);
    this._center =
      placeIndex >= 0 ? `place:${placeIndex}` : ["tracker", "germany"].includes(config.center) ? config.center : "location";
    // By default the card opens with the overview of its center, or all of Germany.
    const zoom = config.zoom ?? (this._center === "germany" ? GERMANY.zoom : DEFAULT_ZOOM);
    this._selection = { layer: config.layer, period: config.period, zoom, pan_x: 0, pan_y: 0 };
    this._playing = this._config.autoplay;
    (this._frames || []).forEach((frame) => URL.revokeObjectURL(frame.url));
    this._frames = [];
    this._views = new Map();
    this._data = undefined;
    this._index = 0;
    if (this.shadowRoot) {
      this._render();
      this._load();
    }
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) {
      this._render();
      this._load();
      return;
    }
    if (!this._data) return;
    // Follow the phone: markers move at once, the map once it left the loaded section.
    const trackerKey = JSON.stringify(this._trackerPoint());
    if (trackerKey !== this._trackerKey) {
      this._trackerKey = trackerKey;
      this._renderCenters();
      this._renderMarkers();
      if (this._center === "tracker" && this._trackerLeftCenter()) {
        clearTimeout(this._trackerTimer);
        this._trackerTimer = setTimeout(() => this._load({ prefetch: false }), TRACKER_RELOAD_MS);
      }
    }
  }

  connectedCallback() {
    this._refreshTimer = setInterval(() => this._load({ refresh: true, prefetch: false }), REFRESH_MS);
    this._syncPlayback();
  }

  disconnectedCallback() {
    clearInterval(this._refreshTimer);
    clearTimeout(this._trackerTimer);
    clearInterval(this._playTimer);
    this._playTimer = undefined;
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const text = textFor(this._hass);
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        ${this._config.title ? `<div class="title"></div>` : ""}
        <div class="chips periods"></div>
        <div class="chips layers"></div>
        <div class="chips centers"></div>
        <div class="viewport">
          <img alt="" />
          <div class="markers"></div>
          <div class="time" hidden><span class="label"></span><span class="badge" hidden>${text.now}</span></div>
          <div class="credits"></div>
          <button class="map-button move-left" title="${text.move.left}" hidden><ha-icon icon="mdi:chevron-left"></ha-icon></button>
          <button class="map-button move-right" title="${text.move.right}" hidden><ha-icon icon="mdi:chevron-right"></ha-icon></button>
          <button class="map-button move-up" title="${text.move.up}" hidden><ha-icon icon="mdi:chevron-up"></ha-icon></button>
          <button class="map-button move-down" title="${text.move.down}" hidden><ha-icon icon="mdi:chevron-down"></ha-icon></button>
          <button class="map-button recenter" title="${text.recenter}" hidden><ha-icon icon="mdi:crosshairs"></ha-icon></button>
          <div class="status" hidden></div>
          <div class="spinner" hidden></div>
        </div>
        <div class="controls">
          <button class="icon-button previous" title="${text.previous}"><ha-icon icon="mdi:skip-previous"></ha-icon></button>
          <button class="icon-button play"><ha-icon></ha-icon></button>
          <button class="icon-button next" title="${text.next}"><ha-icon icon="mdi:skip-next"></ha-icon></button>
          <div class="timeline">
            <input type="range" min="0" max="0" step="1" value="0" />
            <div class="now-mark" hidden></div>
            <div class="ticks"></div>
          </div>
          <button class="icon-button zoom-out" title="${text.zoomOut}"><ha-icon icon="mdi:magnify-minus-outline"></ha-icon></button>
          <button class="icon-button zoom-in" title="${text.zoomIn}"><ha-icon icon="mdi:magnify-plus-outline"></ha-icon></button>
        </div>
        <div class="spacer"></div>
      </ha-card>`;
    const root = this.shadowRoot;
    if (this._config.title) {
      root.querySelector(".title").textContent = this._config.title;
    }
    root.querySelector(".previous").addEventListener("click", () => this._step(-1));
    root.querySelector(".next").addEventListener("click", () => this._step(1));
    root.querySelector(".play").addEventListener("click", () => {
      this._playing = !this._playing;
      this._syncPlayback();
      this._update();
    });
    root.querySelector(".zoom-in").addEventListener("click", () => this._zoom(1));
    root.querySelector(".zoom-out").addEventListener("click", () => this._zoom(-1));
    root.querySelector(".move-left").addEventListener("click", () => this._move(-1, 0));
    root.querySelector(".move-right").addEventListener("click", () => this._move(1, 0));
    root.querySelector(".move-up").addEventListener("click", () => this._move(0, -1));
    root.querySelector(".move-down").addEventListener("click", () => this._move(0, 1));
    root.querySelector(".recenter").addEventListener("click", () => this._select({ pan_x: 0, pan_y: 0 }));
    root.querySelector("input").addEventListener("input", (event) => {
      this._pause();
      this._show(Number(event.target.value));
    });
    this._bindSwipe(root.querySelector(".viewport"));
    this._update();
  }

  _bindSwipe(viewport) {
    let startX = null;
    let startIndex = 0;
    viewport.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      startX = event.clientX;
      startIndex = this._index;
    });
    viewport.addEventListener("pointermove", (event) => {
      if (startX === null || !this._frames.length) return;
      const steps = Math.trunc((event.clientX - startX) / SWIPE_STEP_PX);
      if (steps) {
        this._pause();
        this._show(Math.min(Math.max(startIndex + steps, 0), this._frames.length - 1));
      }
    });
    const end = () => {
      startX = null;
    };
    viewport.addEventListener("pointerup", end);
    viewport.addEventListener("pointercancel", end);
    viewport.addEventListener("pointerleave", end);
  }

  async _load({ refresh = false, prefetch = true } = {}) {
    if (!this._hass || !this._config) return;
    const token = (this._loadToken = (this._loadToken || 0) + 1);
    const keepId = this._frames[this._index]?.id;
    const center = this._centerPoint();
    const url = this._viewUrl(this._selection, center);
    const cached = refresh ? undefined : this._cachedView(url);
    if (!cached) this._setStatus("loading");
    try {
      const view = cached || (await this._fetchView(url));
      if (token !== this._loadToken) return;
      if (!cached) this._cacheView(view, center);
      const { data, blobs } = view;
      const frames = data.frames.map((frame, index) => ({
        id: frame.id,
        time: frame.time ? new Date(frame.time) : null,
        url: URL.createObjectURL(blobs[index]),
      }));
      // Decode all frames up front so stepping through them does not flicker.
      await Promise.all(
        frames.map((frame) => {
          const image = new Image();
          image.src = frame.url;
          return image.decode().catch(() => undefined);
        })
      );
      if (token !== this._loadToken) {
        frames.forEach((frame) => URL.revokeObjectURL(frame.url));
        return;
      }
      const previous = this._frames;
      const samePeriod = this._data && this._data.period === data.period;
      this._frames = frames;
      // Now has moved on since a cached view was loaded.
      this._data = { ...data, now: new Date(Date.parse(data.now) + Date.now() - view.time) };
      this._selection = { layer: data.layer, period: data.period, zoom: data.zoom, pan_x: data.pan_x, pan_y: data.pan_y };
      this._trackerKey = JSON.stringify(this._trackerPoint());
      const kept = samePeriod ? frames.findIndex((frame) => frame.id === keepId) : -1;
      this._index = kept >= 0 ? kept : this._nowIndex();
      previous.forEach((frame) => URL.revokeObjectURL(frame.url));
      this._setStatus();
      this._renderChips();
      this._renderCenters();
      this._renderMarkers();
      this._renderTimeline();
      this._show(this._index);
      this._syncPlayback();
      if (prefetch) this._prefetch(token, center);
    } catch (err) {
      if (token === this._loadToken) this._setStatus("error", err);
    }
  }

  _viewUrl(selection, center) {
    const params = new URLSearchParams();
    for (const key of SELECTION_KEYS) {
      const value = selection[key];
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    }
    if (center) {
      params.set("lat", center.latitude.toFixed(5));
      params.set("lon", center.longitude.toFixed(5));
    }
    return `${API_URL}/${encodeURIComponent(this._config.entity)}?${params}`;
  }

  async _fetchView(url) {
    const response = await this._hass.fetchWithAuth(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const blobs = await Promise.all(
      data.frames.map(async (frame) => {
        const frameResponse = await this._hass.fetchWithAuth(frame.url);
        if (!frameResponse.ok) throw new Error(`HTTP ${frameResponse.status}`);
        return frameResponse.blob();
      })
    );
    return { time: Date.now(), data, blobs };
  }

  _cachedView(url) {
    const view = this._views.get(url);
    this._views.delete(url);
    if (!view || Date.now() - view.time >= CACHE_MS) return undefined;
    // Keep the most recently opened views.
    this._views.set(url, view);
    return view;
  }

  _cacheView(view, center) {
    // The returned selection also names the layer and period of the card's entity.
    this._views.set(this._viewUrl(view.data, center), view);
    while (this._views.size > CACHED_VIEWS) this._views.delete(this._views.keys().next().value);
  }

  async _prefetch(token, center) {
    // Let the server prepare the views one move or zoom step away, one after the other, so
    // they open without waiting for WetterOnline. Their frames are downloaded once opened.
    for (const change of this._neighbors()) {
      if (token !== this._loadToken || !this.isConnected) return;
      const url = this._viewUrl({ ...this._selection, ...change }, center);
      if (this._views.has(url)) continue;
      // A view that fails here shows its error once opened.
      await this._hass
        .fetchWithAuth(url)
        .then((response) => response.text())
        .catch(() => undefined);
    }
  }

  _neighbors() {
    return [this._moved(1, 0), this._moved(-1, 0), this._moved(0, 1), this._moved(0, -1), this._zoomed(1), this._zoomed(-1)]
      .filter(Boolean);
  }

  _nowIndex() {
    const now = this._data.now.getTime();
    let best = 0;
    this._frames.forEach((frame, index) => {
      if (frame.time && frame.time.getTime() <= now) best = index;
    });
    return best;
  }

  _nowPosition() {
    // Fractional frame index of now, or null when now is outside the frames.
    const now = this._data.now.getTime();
    const times = this._frames.map((frame) => frame.time && frame.time.getTime());
    if (times.length < 2 || times.some((time) => !time)) return null;
    if (now < times[0] || now > times[times.length - 1]) return null;
    for (let index = 0; index < times.length - 1; index++) {
      if (now <= times[index + 1]) {
        return index + (now - times[index]) / (times[index + 1] - times[index]);
      }
    }
    return times.length - 1;
  }

  _setStatus(state, error) {
    const root = this.shadowRoot;
    if (!root) return;
    const text = textFor(this._hass);
    const status = root.querySelector(".status");
    const viewport = root.querySelector(".viewport");
    viewport.classList.toggle("busy", state === "loading" && this._frames.length > 0);
    root.querySelector(".spinner").hidden = state !== "loading";
    if (!state || (state === "loading" && this._frames.length)) {
      status.hidden = true;
      return;
    }
    status.hidden = false;
    status.innerHTML = "";
    const message = document.createElement("span");
    message.textContent = state === "loading" ? text.loading : text.error;
    status.append(message);
    if (state === "error") {
      if (error) console.warn("WetterOnline radar card:", error);
      const retry = document.createElement("button");
      retry.className = "chip";
      retry.textContent = text.retry;
      retry.addEventListener("click", () => this._load());
      status.append(retry);
    }
  }

  _renderChips() {
    const root = this.shadowRoot;
    const text = textFor(this._hass);
    const periods = this._config.periods || this._data.periods;
    const layers = this._config.layers || this._data.layers;
    const periodRow = root.querySelector(".periods");
    const layerRow = root.querySelector(".layers");
    periodRow.replaceChildren(
      ...periods.map((period) =>
        this._chip(this._periodLabel(period, text), period === this._data.period, () => this._select({ period }))
      )
    );
    layerRow.replaceChildren(
      ...layers.map((layer) =>
        this._chip(text.layers[layer] || layer, layer === this._data.layer, () => this._select({ layer }))
      )
    );
    periodRow.hidden = periods.length < 2;
    layerRow.hidden = layers.length < 2;
    root.querySelector(".credits").textContent = this._data.credits || "";
    const zoomLevels = this._data.zoom_levels;
    root.querySelector(".zoom-in").disabled = this._data.zoom >= zoomLevels[zoomLevels.length - 1];
    root.querySelector(".zoom-out").disabled = this._data.zoom <= zoomLevels[0];
    const { pan_x: panX, pan_y: panY, max_pan: maxPan } = this._data;
    root.querySelector(".move-left").hidden = panX <= -maxPan;
    root.querySelector(".move-right").hidden = panX >= maxPan;
    root.querySelector(".move-up").hidden = panY <= -maxPan;
    root.querySelector(".move-down").hidden = panY >= maxPan;
    root.querySelector(".recenter").hidden = !panX && !panY;
  }

  _trackerPoint() {
    const hass = this._hass;
    if (!hass) return null;
    let entityId = this._config.tracker;
    if (!entityId) {
      // By default "my location" is the person of the user looking at the card.
      const person = Object.values(hass.states).find(
        (state) => state.entity_id.startsWith("person.") && state.attributes.user_id === hass.user?.id
      );
      entityId = person?.entity_id;
    }
    const attributes = (entityId && hass.states[entityId]?.attributes) || {};
    const { latitude, longitude } = attributes;
    return typeof latitude === "number" && typeof longitude === "number" ? { latitude, longitude } : null;
  }

  _centers() {
    const text = textFor(this._hass);
    const centers = [{ key: "location", label: this._data?.location?.name || "WetterOnline", ...this._data?.location }];
    const tracker = this._trackerPoint();
    if (tracker) centers.push({ key: "tracker", label: text.myLocation, ...tracker });
    centers.push({ key: "germany", label: text.germany, latitude: GERMANY.latitude, longitude: GERMANY.longitude });
    this._config.places.forEach((place, index) => {
      centers.push({ ...place, key: `place:${index}`, label: place.name || `${place.latitude}, ${place.longitude}` });
    });
    return centers;
  }

  _centerPoint() {
    // The WetterOnline location is the default center, so it needs no coordinates.
    if (this._center === "location") return null;
    return this._centers().find((center) => center.key === this._center) || null;
  }

  _trackerLeftCenter() {
    // Reload only once the phone is an eighth of the view away from the loaded center,
    // so GPS jitter does not reload the frames again and again.
    const tracker = this._trackerPoint();
    if (!tracker) return false;
    const { view, pan_x: panX, pan_y: panY } = this._data;
    const [x, y] = worldPixel(tracker.latitude, tracker.longitude, view.zoom);
    const centerX = view.x + (view.size / 2) * (1 - panX);
    const centerY = view.y + (view.size / 2) * (1 - panY);
    return Math.hypot(x - centerX, y - centerY) > view.size / 8;
  }

  _renderCenters() {
    const row = this.shadowRoot.querySelector(".centers");
    const centers = this._centers();
    // Without its position, e.g. without GPS, the map shows the WetterOnline location.
    const active = centers.some((center) => center.key === this._center) ? this._center : "location";
    row.hidden = centers.length < 2;
    row.replaceChildren(
      ...centers.map((center) => this._chip(center.label, center.key === active, () => this._selectCenter(center.key)))
    );
  }

  _selectCenter(key) {
    const change = { pan_x: 0, pan_y: 0 };
    // All of Germany needs the widest view; leaving that view returns to the card's zoom.
    if (key === "germany") change.zoom = GERMANY.zoom;
    else if (this._center === "germany" && this._selection.zoom === GERMANY.zoom) {
      change.zoom = this._config.zoom ?? DEFAULT_ZOOM;
    }
    this._center = key;
    this._select(change);
  }

  _renderMarkers() {
    const container = this.shadowRoot.querySelector(".markers");
    const { view, location } = this._data;
    const points = [{ ...location, color: MARKER_COLORS.location }];
    const tracker = this._trackerPoint();
    if (tracker) points.push({ ...tracker, color: MARKER_COLORS.tracker });
    if (this._center.startsWith("place:")) points.push({ ...this._centerPoint(), color: MARKER_COLORS.place });
    container.replaceChildren(
      ...points
        .map((point) => {
          const [x, y] = worldPixel(point.latitude, point.longitude, view.zoom);
          return { ...point, left: ((x - view.x) / view.size) * 100, top: ((y - view.y) / view.size) * 100 };
        })
        .filter((point) => point.left >= 0 && point.left <= 100 && point.top >= 0 && point.top <= 100)
        .map((point) => {
          const marker = document.createElement("div");
          marker.className = "marker";
          marker.style.left = `${point.left}%`;
          marker.style.top = `${point.top}%`;
          marker.style.background = point.color;
          return marker;
        })
    );
  }

  _chip(label, selected, onClick) {
    const chip = document.createElement("button");
    chip.className = selected ? "chip selected" : "chip";
    chip.textContent = label;
    chip.addEventListener("click", onClick);
    return chip;
  }

  _periodLabel(period, text) {
    if (text.periods[period]) return text.periods[period];
    const day = new Date(Date.now() + DAY_OFFSETS[period] * 86400000);
    return this._format(day, { weekday: "short" }).replace(/\.$/, "");
  }

  _renderTimeline() {
    const root = this.shadowRoot;
    const text = textFor(this._hass);
    const input = root.querySelector("input");
    const last = Math.max(this._frames.length - 1, 0);
    input.max = String(last);
    input.disabled = last === 0;
    const ticks = root.querySelector(".ticks");
    ticks.replaceChildren();
    const nowPosition = this._nowPosition();
    const nowMark = root.querySelector(".now-mark");
    const percent = (index) => (last ? (index / last) * 100 : 0);
    nowMark.hidden = nowPosition === null;
    if (nowPosition !== null) {
      // The range thumb travels between half a thumb width from each edge.
      nowMark.style.left = `calc(9px + (100% - 18px) * ${percent(nowPosition) / 100})`;
      const label = document.createElement("span");
      label.className = "now";
      label.textContent = text.now;
      label.style.left = `${percent(nowPosition)}%`;
      ticks.append(label);
    }
    const times = this._frames.map((frame) => frame.time);
    if (times.length < 2 || times.some((time) => !time)) return;
    const hours = (times[times.length - 1] - times[0]) / 3600000;
    const interval = hours <= 4 ? 1 : hours <= 12 ? 3 : 6;
    // Labels are about 32 px wide; skip ticks that would touch the now label.
    const minGap = (38 / (ticks.clientWidth || 200)) * 100;
    times.forEach((time, index) => {
      const { hour, minute } = this._clock(time);
      if (minute !== 0 || hour % interval !== 0) return;
      if (nowPosition !== null && Math.abs(percent(index) - percent(nowPosition)) < minGap) return;
      const label = document.createElement("span");
      label.textContent = `${String(hour).padStart(2, "0")}:00`;
      label.style.left = `${percent(index)}%`;
      ticks.append(label);
    });
  }

  _show(index) {
    if (!this._frames.length) return;
    this._index = index;
    const root = this.shadowRoot;
    const frame = this._frames[index];
    root.querySelector("img").src = frame.url;
    root.querySelector("input").value = String(index);
    const time = root.querySelector(".time");
    time.hidden = !frame.time;
    if (frame.time) {
      const weekday = this._format(frame.time, { weekday: "short" }).replace(/\.$/, "");
      const clock = this._format(frame.time, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
      root.querySelector(".label").textContent = `${weekday} ${clock}`;
    }
    const nowPosition = this._nowPosition();
    root.querySelector(".badge").hidden = nowPosition === null || Math.round(nowPosition) !== index;
    this._update();
  }

  _update() {
    const text = textFor(this._hass);
    const play = this.shadowRoot.querySelector(".play");
    play.title = this._playing ? text.pause : text.play;
    play.querySelector("ha-icon").setAttribute("icon", this._playing ? "mdi:pause" : "mdi:play");
    play.disabled = this._frames.length < 2;
  }

  _clock(date) {
    const parts = new Intl.DateTimeFormat("en", {
      timeZone: this._hass?.config?.time_zone,
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
    }).formatToParts(date);
    const part = (type) => Number(parts.find((item) => item.type === type)?.value);
    return { hour: part("hour"), minute: part("minute") };
  }

  _format(date, options) {
    return new Intl.DateTimeFormat(this._hass?.locale?.language || this._hass?.language || "en", {
      timeZone: this._hass?.config?.time_zone,
      ...options,
    }).format(date);
  }

  _step(delta) {
    if (!this._frames.length) return;
    this._pause();
    const count = this._frames.length;
    this._show((this._index + delta + count) % count);
  }

  _pause() {
    if (this._playing) {
      this._playing = false;
      this._syncPlayback();
    }
  }

  _syncPlayback() {
    clearInterval(this._playTimer);
    this._playTimer = undefined;
    if (this._playing && this.isConnected && this._frames.length > 1) {
      this._playTimer = setInterval(
        () => this._show((this._index + 1) % this._frames.length),
        Number(this._config.frame_duration) || 1000
      );
    }
    if (this.shadowRoot && this._config) this._update();
  }

  _select(change) {
    this._selection = { ...this._selection, ...change };
    this._load();
  }

  _zoom(delta) {
    const change = this._zoomed(delta);
    if (change) this._select(change);
  }

  _move(dx, dy) {
    const change = this._moved(dx, dy);
    if (change) this._select(change);
  }

  _zoomed(delta) {
    const levels = this._data?.zoom_levels || [];
    const next = levels[levels.indexOf(this._data?.zoom) + delta];
    if (next === undefined) return null;
    // Keep roughly the same section: one step is half a view, which doubles per level.
    const maxPan = 2 ** (next - levels[0]) - 1;
    const scale = (pan) => Math.max(-maxPan, Math.min(maxPan, delta > 0 ? pan * 2 : Math.round(pan / 2)));
    return { zoom: next, pan_x: scale(this._data.pan_x), pan_y: scale(this._data.pan_y) };
  }

  _moved(dx, dy) {
    const { pan_x: panX, pan_y: panY, max_pan: maxPan } = this._data || {};
    if (maxPan === undefined) return null;
    const [x, y] = [panX + dx, panY + dy];
    return Math.abs(x) <= maxPan && Math.abs(y) <= maxPan ? { pan_x: x, pan_y: y } : null;
  }
}

// Home Assistant replaces window.customElements with its own registry while it starts.
// The integration loads this file early, so define the card only once Home Assistant
// is defined; otherwise the card would end up in the replaced registry.
const define = () => {
  if (!window.customElements.get("wetteronline-radar-card")) {
    window.customElements.define("wetteronline-radar-card", WetterOnlineRadarCard);
  }
};
if (window.customElements.get("home-assistant")) {
  define();
} else {
  window.customElements.whenDefined("home-assistant").then(define);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "wetteronline-radar-card",
  name: "WetterOnline Radar",
  description: "Weather, rain, and cloud radar of the WetterOnline integration with day selection, pause, zoom, and your location.",
  preview: false,
  documentationURL: "https://github.com/GLG9/home-assistant-wetteronline",
});
