// WetterOnline radar card: step through, pause, and zoom the radar frames of the
// WetterOnline integration. Served and loaded by the integration itself.

const API_URL = "/api/wetteronline/radar";
const REFRESH_MS = 10 * 60 * 1000;
const SWIPE_STEP_PX = 24;

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
    editor: {
      entity: "WetterOnline-Entität des Orts",
      layer: "Karte beim Öffnen",
      period: "Zeitraum beim Öffnen",
      zoom: "Zoomstufe beim Öffnen",
      frame_duration: "Dauer pro Bild",
      autoplay: "Automatisch abspielen",
      title: "Titel",
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
    editor: {
      entity: "WetterOnline entity of the location",
      layer: "Map when opened",
      period: "Period when opened",
      zoom: "Zoom level when opened",
      frame_duration: "Duration per frame",
      autoplay: "Play automatically",
      title: "Title",
    },
  },
};
const DAY_OFFSETS = { animation: 0, today: 0, tomorrow: 1, in_2_days: 2, in_3_days: 3, in_4_days: 4 };

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
    flex: none; border: 1px solid var(--divider-color); border-radius: 16px;
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
  .status {
    position: absolute; inset: 0; display: flex; flex-direction: column; gap: 8px;
    align-items: center; justify-content: center; color: var(--primary-text-color); text-align: center;
  }
  .status span { background: var(--card-background-color); padding: 6px 12px; border-radius: 8px; }
  .controls { display: flex; align-items: center; gap: 2px; padding: 4px 6px 0; }
  .icon-button {
    flex: none; width: 40px; height: 40px; border: none; border-radius: 50%; background: none;
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
        { name: "zoom", selector: { number: { min: 7, max: 10, mode: "slider" } } },
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
    this._selection = { layer: config.layer, period: config.period, zoom: config.zoom };
    this._playing = this._config.autoplay;
    (this._frames || []).forEach((frame) => URL.revokeObjectURL(frame.url));
    this._frames = [];
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
    }
  }

  connectedCallback() {
    this._refreshTimer = setInterval(() => this._load(), REFRESH_MS);
    this._syncPlayback();
  }

  disconnectedCallback() {
    clearInterval(this._refreshTimer);
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
        <div class="viewport">
          <img alt="" />
          <div class="time" hidden><span class="label"></span><span class="badge" hidden>${text.now}</span></div>
          <div class="credits"></div>
          <div class="status" hidden></div>
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

  async _load() {
    if (!this._hass || !this._config) return;
    const token = (this._loadToken = (this._loadToken || 0) + 1);
    const keepId = this._frames[this._index]?.id;
    this._setStatus("loading");
    try {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(this._selection)) {
        if (value !== undefined && value !== null && value !== "") params.set(key, value);
      }
      const response = await this._hass.fetchWithAuth(
        `${API_URL}/${encodeURIComponent(this._config.entity)}?${params}`
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const blobs = await Promise.all(
        data.frames.map(async (frame) => {
          const frameResponse = await this._hass.fetchWithAuth(frame.url);
          if (!frameResponse.ok) throw new Error(`HTTP ${frameResponse.status}`);
          return frameResponse.blob();
        })
      );
      if (token !== this._loadToken) return;
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
      this._data = { ...data, now: new Date(data.now) };
      this._selection = { layer: data.layer, period: data.period, zoom: data.zoom };
      const kept = samePeriod ? frames.findIndex((frame) => frame.id === keepId) : -1;
      this._index = kept >= 0 ? kept : this._nowIndex();
      previous.forEach((frame) => URL.revokeObjectURL(frame.url));
      this._setStatus();
      this._renderChips();
      this._renderTimeline();
      this._show(this._index);
      this._syncPlayback();
    } catch (err) {
      if (token === this._loadToken) this._setStatus("error", err);
    }
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
    const levels = this._data?.zoom_levels || [];
    const index = levels.indexOf(this._data?.zoom);
    const next = levels[index + delta];
    if (next !== undefined) this._select({ zoom: next });
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
  description: "Weather, rain, and cloud radar of the WetterOnline integration with day selection, pause, and zoom.",
  preview: false,
  documentationURL: "https://github.com/GLG9/home-assistant-wetteronline",
});
