/*
 * BatteryLedger card. Served and loaded by the BatteryLedger integration (no separate install).
 *
 * Data comes from the integration's websocket command battery_ledger/card/setups: each setup's sensors
 * (found by unique ID, so renamed entities still work), battery groups and saved card settings.
 * Admins change the settings with the cog at the bottom right; they're saved per setup by the integration.
 */
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";  // the integration version
// Served next to the card file, with the version so a new release isn't cached.
const LOGO_URL = `${new URL("battery-ledger-logo.png", import.meta.url).pathname}?v=${encodeURIComponent(CARD_VERSION)}`;
const WS_SETUPS = "battery_ledger/card/setups";
const WS_SAVE = "battery_ledger/card/save_settings";
const SECTIONS = ["warranty", "usage", "financials", "health"];
const DECIMAL_CHOICES = [2, 3, 4, 5];
const DATE_STYLES = ["ha", "day_month_year"];

const STRINGS = {
  en: {
    card_name: "BatteryLedger",
    card_description: "Warranty use, cost and health of a BatteryLedger battery.",
    no_setup: "No BatteryLedger setup found. Add one under Settings → Devices & services.",
    loading: "Loading…",
    load_failed: "Couldn't load BatteryLedger data.",
    usable: "{kwh} kWh usable",
    warranty_used: "Warranty Used",
    by_time: "Warranty Used (by age):",
    by_throughput: "Warranty Used (by usage):",
    driver: "Warranty Driver:",
    cycles: "Cycles per day (Average):",
    warranty_ends: "Warranty Ends ({years} years):",
    warranty_ends_usage: "Warranty Ends (by usage):",
    remaining_throughput: "Remaining Warrantied Usage:",
    esl: "Estimated Service Life (ESL):",
    battery_groups: "Battery group:",
    all_groups: "All",
    status_on_track: "On Track | Normal",
    status_ahead_of_time: "Degrading Faster Than Time Curve",
    status_expired: "Warranty Ended",
    driver_age: "Age (Time Elapsed)",
    driver_throughput: "Throughput (Cycles)",
    esl_years: "years",
    eosl: "End of Service Life (EoSL):",
    esl_usage: "Estimated usage at EoSL:",
    of_warranted: "{pct}% of warranted",
    export_cost: "Export Cost:",
    export_basis: "Export Cost Basis:",
    basis_age: "by age",
    basis_usage: "by usage",
    basis_esl: "ESL",
    basis_soh_trend: "SoH trend",
    option_warranty: "Warranty",
    option_age: "Warranty by age",
    option_usage: "Warranty by usage",
    option_esl: "Estimated Service Life (ESL)",
    option_cheapest: "Cheapest",
    of_total: "of {total} kWh",
    left_at_end: "Left at warranty end (projected): {kwh} kWh",
    used: "{kwh} kWh used",
    no_throughput_limit: "This warranty has no throughput limit.",
    cost_consumed: "Value used to date:",
    remaining_value: "Remaining Value:",
    cost_per_kwh: "Cost per kWh:",
    rated: "by usage",
    projected: "by age",
    health: "Health",
    actual_soh: "Actual SoH (battery)",
    actual_soh_measured: "Actual SoH (measured)",
    measured_line: "Measured: {pct}%",
    measuring: "Measuring capacity:",
    measuring_charges: "{runs} of {need} Charges",
    measuring_discharges: "{runs} of {need} Discharges",
    warranty_allows: "Projected SoH (Today)",
    // Actual SoH tile without a reading: why, from the setup's integration (its Store profile)
    soh_no_reading: "No SoH reading from {source}",
    soh_no_reading_unknown: "No SoH reading from the SoH sensor",
    soh_not_set_up: "Not Configured",
    soh_unavailable: "Not available for {brand}",
    soh_not_configured: "No SoH sensor configured",
    above: "{pct}% above warranty",
    below: "{pct}% below warranty",
    eol: "{pct}% End of Warranty",
    curve: "warranty curve {pct}%",
    hardware: "Hardware Capacity:",
    most_used_module: "Most Used Module:",
    soc_spread: "Module SoC Spread:",
    settings: "Card settings",
    settings_button: "Card settings",
    cost_decimals: "Cost per kWh decimal places:",
    date_style: "Date display:",
    date_style_ha: "Home Assistant format",
    date_style_day_month_year: "Day month year (18 Jul 2035)",
    sections: "Display Sections:",
    section_warranty: "Warranty",
    section_usage: "Usage & Throughput",
    section_financials: "Financials",
    section_health: "Health",
    cancel: "Cancel",
    save: "Save",
    save_failed: "Couldn't save the settings.",
    editor_setup: "BatteryLedger setup",
    editor_hint: "Decimal places, date display and sections are set with the cog on the card.",
  },
};

// The warranty_status attribute's text -> the ledger's status codes ("/" is the text before v0.1.18)
const STATUS_CODES = {
  "On Track | Normal": "on_track",
  "On Track / Normal": "on_track",
  "Degrading Faster Than Time Curve": "ahead_of_time",
  "Warranty Ended": "expired",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function strings(hass) {
  const lang = (hass?.locale?.language || hass?.language || "en").split("-")[0];
  return { ...STRINGS.en, ...(STRINGS[lang] || {}) };
}

function fill(text, values) {
  return text.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");
}

const STYLE = `
  :host { --bl-time: var(--info-color, #2b9af3); --bl-tp: var(--success-color, #43a047);
          --bl-warn: var(--warning-color, #ffa600); --bl-bad: var(--error-color, #db4437);
          --bl-ok: var(--success-color, #43a047); --bl-muted: var(--secondary-text-color);
          --bl-tile: var(--secondary-background-color, rgba(127,127,127,.08)); }
  ha-card { display: block; padding: 16px; position: relative; }
  .head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .logo { width: 40px; height: 40px; flex: none; object-fit: contain; }
  .title { font-size: 16px; font-weight: 500; line-height: 1.3; }
  .sub, .lbl { font-size: 12px; color: var(--bl-muted); }
  .grow { flex: 1; min-width: 0; }
  .chip { font-size: 12px; padding: 3px 10px; border-radius: 12px; white-space: nowrap; }
  .chip.ok { background: rgba(67,160,71,.15); color: var(--bl-ok); }
  .chip.warn { background: rgba(255,166,0,.15); color: var(--bl-warn); }
  .chip.bad { background: rgba(219,68,55,.15); color: var(--bl-bad); }
  .chip.muted { background: var(--bl-tile); color: var(--bl-muted); }
  .cog { color: var(--bl-muted); flex: none; margin: -10px 0; }
  section { margin-top: 12px; }
  section:first-of-type { margin-top: 0; }
  .ring-row { display: flex; align-items: center; gap: 18px; }
  .stats { flex: 1; display: grid; gap: 5px; min-width: 0; }
  .stat { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .stat .v { font-size: 14px; font-weight: 500; text-align: right; }
  .driver-end { color: var(--bl-bad); }
  .setup-link { color: var(--primary-color); text-decoration: none; display: inline-flex; align-items: center; gap: 4px; }
  .setup-link ha-icon { --mdc-icon-size: 18px; }
  .setup-link:hover { text-decoration: underline; }
  /* A thin line above each end date, starting its group. */
  .stat.spaced { border-top: 1px solid var(--divider-color, rgba(127,127,127,.25)); padding-top: 5px; }
  /* Thin lines between warranty and Remaining Warrantied Usage, and between Financials and Health, when both are
     shown. The section's own 12px gap is split either side of the line, so the card doesn't grow. */
  section.warranty + section.usage, section.financials + section.health {
    border-top: 1px solid var(--divider-color, rgba(127,127,127,.25)); margin-top: 6px; padding-top: 6px; }
  /* The dot hangs in the gap left of the label, so every label's words start in line. */
  .stat .lbl { position: relative; }
  .dot { position: absolute; left: -14px; top: 50%; transform: translateY(-50%); width: 8px; height: 8px;
         border-radius: 50%; }
  .bar { height: 12px; border-radius: 6px; background: var(--bl-tile); position: relative; margin: 6px 0 4px; }
  .bar .fill { position: absolute; inset: 0 auto 0 0; border-radius: 6px; }
  .bar .mark { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; }
  .spread { display: flex; justify-content: space-between; gap: 8px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
  .tile { background: var(--bl-tile); border-radius: 8px; padding: 8px 12px; min-width: 0; }
  .big { font-size: 22px; font-weight: 500; line-height: 1.3; }
  /* Money tiles: the figure is centred in the space below its label (the cost per kWh tile is taller). */
  .tile.value { display: flex; flex-direction: column; }
  .tile.value .big { flex: 1; display: flex; align-items: center; }
  /* Cost per kWh: its two lines centred together in the same space, a little apart. */
  .tile.value .pair { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 4px;
                      margin-top: 4px; }
  .tiles { align-items: stretch; }
  .tile.value { min-height: 84px; }
  .mid { font-size: 15px; font-weight: 500; }
  .section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .section-head .t { font-size: 15px; font-weight: 500; }
  .foot { border-top: 1px solid var(--divider-color); padding-top: 8px; margin-top: 10px; display: flex;
          justify-content: space-between; align-items: flex-start; gap: 8px; }
  .foot.bare { border-top: none; padding-top: 0; margin-top: 4px; justify-content: flex-end; }
  .foot .lines { display: grid; gap: 4px; min-width: 0; }
  .foot .end { display: flex; align-items: center; gap: 2px; flex: none; }
  .ver { font-size: 11px; color: var(--bl-muted); }
  [data-entity] { cursor: pointer; }
  .msg { color: var(--bl-muted); padding: 8px 0; }
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center;
             justify-content: center; z-index: 9; }
  .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 12px;
            padding: 20px; width: min(360px, calc(100vw - 32px)); box-shadow: var(--ha-card-box-shadow, 0 4px 16px rgba(0,0,0,.3)); }
  .dialog h3 { margin: 0 0 16px; font-size: 18px; font-weight: 500; }
  .dialog label { display: block; font-size: 13px; color: var(--bl-muted); margin: 12px 0 6px; }
  .dialog select { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid var(--divider-color);
                   background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
  .dialog .check { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--primary-text-color); margin: 6px 0; }
  .dialog .buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
  .dialog button { font: inherit; padding: 8px 16px; border-radius: 8px; cursor: pointer;
                   border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); }
  .dialog button.primary { background: var(--primary-color); border-color: var(--primary-color);
                           color: var(--text-primary-color, #fff); }
  .dialog .err { color: var(--bl-bad); font-size: 13px; margin-top: 10px; }
  input.esl { width: 3.2em; padding: 2px 4px; -moz-appearance: textfield; appearance: textfield; border-radius: 6px; border: 1px solid var(--divider-color, #555);
              background: var(--card-background-color); color: var(--primary-text-color); font: inherit; text-align: right; }
  input.esl::-webkit-outer-spin-button, input.esl::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  select.basis { width: 100%; box-sizing: border-box; padding: 4px 6px; border-radius: 6px; border: 1px solid var(--divider-color, #555);
                 background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 13px; }
  section.switcher { padding-top: 0; }
  .group-head { font-size: 13px; font-weight: 500; margin: 10px 0 6px; }
  .gchips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .gchips .lbl { margin-right: 4px; }
  .gchip { font: inherit; font-size: 13px; min-width: 28px; height: 28px; padding: 0 8px; border-radius: 14px; cursor: pointer;
           border: 1px solid var(--divider-color, #555); background: none; color: var(--primary-text-color); }
  /* Light grey: clear of the card's blue (by age), green (by usage), orange (curve) and red (warranty end) */
  .gchip[aria-pressed="true"] { background: #bdbdbd; border-color: #bdbdbd; color: #1c1c1c; font-weight: 500; }
  .group-grid { display: grid; gap: 6px; }
  .basis-row { margin-top: 8px; display: grid; gap: 4px; min-width: 0; }
  .tile { min-width: 0; }
`;

class BatteryLedgerCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("battery-ledger-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._setups = null;
    this._error = false;
    this._lastKey = "";
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div id="body"></div></ha-card><div id="modal"></div>`;
    this.shadowRoot.getElementById("body").addEventListener("click", (ev) => this._onClick(ev));
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._lastKey = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._setups === null && !this._loading) this._load();
    this._render();
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 6 };
  }

  async _load() {
    this._loading = true;
    try {
      const res = await this._hass.callWS({ type: WS_SETUPS });
      this._setups = res.setups || [];
      this._error = false;
    } catch (err) {
      this._setups = [];
      this._error = true;
    }
    this._loading = false;
    this._lastKey = "";
    this._render();
  }

  get _setup() {
    if (!this._setups || !this._setups.length) return null;
    return this._setups.find((s) => s.entry_id === this._config.entry_id) || this._setups[0];
  }

  // --- state helpers ---------------------------------------------------------------------------
  _state(key) {
    const id = this._setup?.entities?.[key];
    return id ? this._hass.states[id] : undefined;
  }

  _num(key) {
    const st = this._state(key);
    const v = st ? parseFloat(st.state) : NaN;
    return Number.isFinite(v) ? v : null;
  }

  _attr(key, name) {
    return this._state(key)?.attributes?.[name];
  }

  // A YYYY-MM-DD date in the user's Home Assistant format (Profile → Date format), as the rest of
  // the frontend shows dates: the language's own order, or day-month-year / month-day-year / year-month-day.
  _date(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return iso || "—";
    const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    const locale = this._hass?.locale || {};
    if (this._setup?.settings?.date_style === "day_month_year") {
      // 18 Jul 2035: the month's short name in the user's language, always day first.
      const named = new Intl.DateTimeFormat(locale.language || this._hass?.language || "en",
        { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).formatToParts(date);
      const part = (type) => named.find((p) => p.type === type)?.value ?? "";
      return `${part("day").padStart(2, "0")} ${part("month").replace(/\.$/, "")} ${part("year")}`;
    }
    const lang = locale.date_format === "system" ? undefined : (locale.language || this._hass?.language || "en");
    const fmt = new Intl.DateTimeFormat(lang, { year: "numeric", month: "numeric", day: "numeric", timeZone: "UTC" });
    const order = { DMY: ["day", "month", "year"], MDY: ["month", "day", "year"], YMD: ["year", "month", "day"] }[locale.date_format];
    if (!order) return fmt.format(date);
    const parts = fmt.formatToParts(date);
    const value = Object.fromEntries(parts.filter((p) => p.type !== "literal").map((p) => [p.type, p.value]));
    const sep = parts.find((p) => p.type === "literal")?.value ?? "/";
    const last = parts[parts.length - 1];
    return order.map((k) => value[k]).join(sep) + (last?.type === "literal" ? last.value : "");
  }

  _fmt(v, digits) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
    const lang = this._hass?.locale?.language || this._hass?.language || "en";
    return new Intl.NumberFormat(lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(v));
  }

  _money(v, digits) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
    const s = this._setup;
    const label = s.currency_label || s.currency || "";
    if (label && label === s.currency) return `${label} ${this._fmt(v, digits)}`;  // code style, e.g. AUD 2,665.43
    return `${label}${this._fmt(v, digits)}`;  // symbol style, e.g. $2,665.43
  }

  _ent(key) {
    const id = this._setup?.entities?.[key];
    return id ? ` data-entity="${esc(id)}"` : "";
  }

  // --- rendering ---------------------------------------------------------------------------------
  _render() {
    if (!this._hass) return;
    const body = this.shadowRoot.getElementById("body");
    const t = strings(this._hass);
    if (this._setups === null) {
      if (this._lastKey !== "loading") body.innerHTML = `<div class="msg">${esc(t.loading)}</div>`;
      this._lastKey = "loading";
      return;
    }
    const setup = this._setup;
    if (!setup) {
      body.innerHTML = `<div class="msg">${esc(this._error ? t.load_failed : t.no_setup)}</div>`;
      this._lastKey = "none";
      return;
    }
    // Re-render only when one of this setup's sensors (or the settings) changed.
    const key = JSON.stringify([setup.entry_id, setup.settings, this._hass.user?.is_admin,
      Object.values(setup.entities).map((id) => this._hass.states[id]?.last_updated)]);
    if (key === this._lastKey) return;
    this._lastKey = key;

    const sec = setup.settings.sections;
    body.innerHTML = [
      this._header(t, setup),
      this._switcher(t),
      sec.warranty ? this._warranty(t) : "",
      sec.usage ? this._usage(t) : "",
      sec.financials ? this._financials(t, setup) : "",
      sec.health ? this._health(t, setup) : "",
      this._footer(t, sec.health),
    ].join("");
    const cog = body.querySelector(".cog");
    if (cog) cog.addEventListener("click", (ev) => { ev.stopPropagation(); this._openSettings(); });
    const esl = body.querySelector("input.esl");
    if (esl) {
      for (const evt of ["click", "keydown"]) esl.addEventListener(evt, (ev) => ev.stopPropagation());
      esl.addEventListener("change", () => {
        const v = parseFloat(esl.value);
        if (Number.isFinite(v)) {
          this._hass.callService("number", "set_value", { entity_id: setup.entities.estimated_service_life, value: v });
        }
      });
    }
    for (const chip of body.querySelectorAll(".gchip")) {
      chip.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._group = chip.dataset.group === "all" ? null : Number(chip.dataset.group);
        this._lastKey = "";
        this._render();
      });
    }
    const basis = body.querySelector("select.basis");
    if (basis) {
      basis.addEventListener("click", (ev) => ev.stopPropagation());
      basis.addEventListener("change", () => this._hass.callService("select", "select_option",
        { entity_id: setup.entities.export_cost_basis, option: basis.value }));
    }
  }

  _header(t, setup) {
    const models = setup.groups.map((g) => `${esc(g.model)}${g.units > 1 ? ` × ${g.units}` : ""}`).join(" + ");
    const usable = this._num("initial_usable_capacity");
    const sub = [models, usable !== null ? esc(fill(t.usable, { kwh: this._fmt(usable, 2) })) : ""].filter(Boolean).join(" · ");
    // Status of the whole setup, or of the group chosen with the switcher
    const g = this._picked();
    const code = g ? g.status : STATUS_CODES[this._attr("estimated_usable_capacity", "warranty_status")];
    const text = code ? t[`status_${code}`] : this._attr("estimated_usable_capacity", "warranty_status");
    const cls = code === "on_track" ? "ok" : code === "ahead_of_time" ? "warn" : "muted";
    const chip = text ? `<span class="chip ${cls}"${this._ent("estimated_usable_capacity")}>${esc(text)}</span>` : "";
    return `<div class="head">
      <img class="logo" src="${LOGO_URL}" alt="">
      <div class="grow"><div class="title">${esc(setup.title)}</div><div class="sub">${sub}</div></div>
      ${chip}</div>`;
  }

  _ring(timePct, tpPct) {
    const arc = (r, pct) => {
      const c = 2 * Math.PI * r;
      const len = Math.max(0, Math.min(100, pct ?? 0)) / 100 * c;
      return `stroke-dasharray="${len.toFixed(1)} ${c.toFixed(1)}"`;
    };
    const used = Math.max(timePct ?? 0, tpPct ?? 0);
    return `<svg width="112" height="112" viewBox="0 0 120 120" aria-hidden="true">
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--bl-tile)" stroke-width="10"/>
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--bl-time)" stroke-width="10" stroke-linecap="round"
        transform="rotate(-90 60 60)" ${arc(50, timePct)}/>
      <circle cx="60" cy="60" r="36" fill="none" stroke="var(--bl-tile)" stroke-width="8"/>
      <circle cx="60" cy="60" r="36" fill="none" stroke="var(--bl-tp)" stroke-width="8" stroke-linecap="round"
        transform="rotate(-90 60 60)" ${arc(36, tpPct)}/>
      <text x="60" y="60" text-anchor="middle" style="font-size:18px;font-weight:500;fill:var(--primary-text-color)">${this._fmt(used, 1)}%</text>
      <text x="60" y="76" text-anchor="middle" style="font-size:11px;fill:var(--bl-muted)">${esc(strings(this._hass).warranty_used)}</text>
    </svg>`;
  }

  _throughputPct() {
    const used = this._num("rated_throughput_used");
    const total = this._num("total_rated_throughput");
    if (used !== null && total) return used / total * 100;
    const attr = parseFloat(this._attr("cost_consumed_to_date", "percent_of_rated_life_used"));
    return Number.isFinite(attr) ? attr : null;
  }

  // Latest end across battery groups: by date (install + warranty years) or by usage (when the
  // throughput limit is reached at the average rate so far).
  _warrantyEnd(key = "warranty_end_date") {
    const groups = (this._attr("rated_throughput_used", "groups") || []).filter((g) => g[key]);
    if (!groups.length) return null;
    const last = groups.reduce((a, b) => (b[key] > a[key] ? b : a));
    return { date: last[key], years: last.warranty_years };
  }

  _warranty(t) {
    const timePct = this._num("warranty_time_elapsed");
    const tpPct = this._throughputPct();
    const driver = this._attr("estimated_usable_capacity", "degradation_driver");
    const end = this._warrantyEnd();
    const usageEnd = this._warrantyEnd("throughput_end_date");
    // The end date that comes first is the one the warranty runs out on (the same as the warranty driver:
    // usage ends first exactly when throughput is ahead of time), so it's shown in red.
    // On a tie the driver is age, so the date end wins.
    const endValue = (e, other, tieWins = false) => {
      const first = !other || e.date < other.date || (tieWins && e.date === other.date);
      return `<span${first ? ' class="driver-end"' : ""}>${esc(this._date(e.date))}</span>`;
    };
    const row = (label, value, ent, dot, spaced) => `<div class="stat${spaced ? " spaced" : ""}"${ent || ""}><span class="lbl">${dot ? `<span class="dot" style="background:${dot}"></span>` : ""}${esc(label)}</span><span class="v">${value}</span></div>`;
    const groups = this._groups();
    const g = this._picked();
    if (g) {
      // One battery group of several: its own figures
      const gEnd = g.warranty_end_date ? { date: g.warranty_end_date, years: g.warranty_years } : null;
      const gUsage = g.throughput_end_date ? { date: g.throughput_end_date } : null;
      const ent = this._ent("rated_throughput_used");
      return `<section class="warranty"><div class="ring-row">${this._ring(g.time_elapsed_pct, g.throughput_used_pct)}<div class="stats">
        ${row(t.driver, esc(t[`driver_${g.driver}`] || g.driver || "—"), ent)}
        ${gEnd ? row(fill(t.warranty_ends, { years: this._fmt(gEnd.years, gEnd.years % 1 ? 1 : 0) }), endValue(gEnd, gUsage, true), "", null, true) : ""}
        ${row(t.by_time, `${this._fmt(g.time_elapsed_pct, 2)}%`, ent, "var(--bl-time)")}
        ${gUsage ? row(t.warranty_ends_usage, endValue(gUsage, gEnd), ent, null, true) : ""}
        ${g.throughput_used_pct != null ? row(t.by_throughput, `${this._fmt(g.throughput_used_pct, 2)}%`, ent, "var(--bl-tp)") : ""}
        ${this._serviceLife(t, row, false)}
        ${g.end_of_service_life ? row(t.eosl, esc(this._date(g.end_of_service_life)), this._ent("end_of_service_life")) : ""}
        ${this._eslUsage(t, row, g.projected_esl_throughput_kwh, g.throughput_limit_kwh)}
      </div></div></section>`;
    }
    if (groups.length > 1) {
      // All: the whole setup (end dates differ by group: choose one with the switcher)
      return `<section class="warranty"><div class="ring-row">${this._ring(timePct, tpPct)}<div class="stats">
        ${row(t.driver, esc(driver ?? "—"), this._ent("estimated_usable_capacity"))}
        ${row(t.cycles, this._fmt(this._num("cycles_per_day"), 4), this._ent("cycles_per_day"))}
        ${row(t.by_time, `${this._fmt(timePct, 2)}%`, this._ent("warranty_time_elapsed"), "var(--bl-time)", true)}
        ${row(t.by_throughput, `${this._fmt(tpPct, 2)}%`, this._ent("rated_throughput_used"), "var(--bl-tp)")}
        ${this._serviceLife(t, row)}
      </div></div></section>`;
    }
    return `<section class="warranty"><div class="ring-row">${this._ring(timePct, tpPct)}<div class="stats">
      ${row(t.driver, esc(driver ?? "—"), this._ent("estimated_usable_capacity"))}
      ${row(t.cycles, this._fmt(this._num("cycles_per_day"), 4), this._ent("cycles_per_day"))}
      ${end ? row(fill(t.warranty_ends, { years: this._fmt(end.years, end.years % 1 ? 1 : 0) }), endValue(end, usageEnd, true), "", null, true) : ""}
      ${row(t.by_time, `${this._fmt(timePct, 2)}%`, this._ent("warranty_time_elapsed"), "var(--bl-time)")}
      ${usageEnd ? row(t.warranty_ends_usage, endValue(usageEnd, end), this._ent("projected_warranted_throughput"), null, true) : ""}
      ${row(t.by_throughput, `${this._fmt(tpPct, 2)}%`, this._ent("rated_throughput_used"), "var(--bl-tp)")}
      ${this._serviceLife(t, row)}
    </div></div></section>`;
  }

  _groups() {
    return this._attr("rated_throughput_used", "groups") || [];
  }

  // The battery group chosen with the switcher, or null for All (the whole setup)
  _picked() {
    const groups = this._groups();
    return groups.length > 1 && this._group != null && this._group < groups.length ? groups[this._group] : null;
  }

  // Several battery groups: All and a chip per group (1, 2, 3 …). A group shows its own warranty, throughput
  // and warranty-curve figures; cost stays for the whole setup.
  _switcher(t) {
    const groups = this._groups();
    if (groups.length < 2) return "";
    const pick = this._picked() ? this._group : null;
    const chip = (value, text, title) => `<button class="gchip" data-group="${value}" aria-pressed="${value === (pick ?? "all")}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</button>`;
    const chips = [chip("all", t.all_groups),
      ...groups.map((g, i) => chip(i, String(i + 1), `${g.units} × ${g.label} · ${this._date(g.install_date)}`))].join("");
    const g = this._picked();
    const head = g ? `<div class="group-head">${esc(`${g.units} × ${g.label} · ${this._date(g.install_date)}`)}</div>` : "";
    return `<section class="switcher"><div class="gchips" role="group" aria-label="${esc(t.battery_groups)}">
      <span class="lbl">${esc(t.battery_groups)}</span>${chips}</div>${head}</section>`;
  }

  // Estimated usage at EoSL: throughput at the average rate so far until End of Service Life, and its share
  // of the warranted throughput (over 100% once it runs past the warranty's limit)
  _eslUsage(t, row, kwh, limit) {
    if (kwh == null) return "";
    const pct = limit ? `<br><span class="lbl">${esc(fill(t.of_warranted, { pct: this._fmt(kwh / limit * 100, 0) }))}</span>` : "";
    return row(t.esl_usage, `${this._fmt(kwh, 0)} kWh${pct}`, this._ent("estimated_usage_at_eosl"));
  }

  // Estimated Service Life (a box admins can change) and each battery group's End of Service Life.
  _serviceLife(t, row, withEosl = true) {
    const eslId = this._setup.entities.estimated_service_life;
    const esl = eslId ? this._hass.states[eslId] : null;
    if (!esl) return "";
    const years = parseFloat(esl.state);
    const value = this._hass.user?.is_admin
      ? `<input class="esl" type="number" min="${esl.attributes.min ?? 1}" max="${esl.attributes.max ?? 30}" step="${esl.attributes.step ?? 0.5}" value="${Number.isFinite(years) ? years : ""}"> <span class="lbl">${esc(t.esl_years)}</span>`
      : `${esc(this._fmt(years, years % 1 ? 1 : 0))} <span class="lbl">${esc(t.esl_years)}</span>`;
    const groups = this._attr("end_of_service_life", "groups") || [];
    const dates = groups.length > 1
      ? groups.map((g) => esc(this._date(g.end_of_service_life))).join("<br>")
      : esc(this._date(this._state("end_of_service_life")?.state));
    return row(t.esl, value, "", null, true) + (withEosl ? row(t.eosl, dates, this._ent("end_of_service_life")) : "")
      + (withEosl ? this._eslUsage(t, row, this._num("estimated_usage_at_eosl"), this._num("total_rated_throughput")) : "");
  }

  _usage(t) {
    const g = this._picked();
    const total = g ? g.throughput_limit_kwh : this._num("total_rated_throughput");
    const used = g ? g.throughput_used_kwh : this._num("rated_throughput_used");
    const remaining = g ? (total != null && used != null ? Math.max(0, total - used) : null)
      : this._num("remaining_rated_throughput");
    if (!total || remaining === null) {
      return this._state("total_rated_throughput") ? `<section class="usage"><div class="lbl">${esc(t.no_throughput_limit)}</div></section>` : "";
    }
    const projected = g ? g.projected_throughput_kwh ?? null : this._num("projected_warranted_throughput");
    const leftAtEnd = projected !== null ? Math.max(0, total - projected) : null;
    const pct = (v) => Math.max(0, Math.min(100, v / total * 100)).toFixed(2);
    return `<section class="usage">
      <div class="stat"${this._ent("remaining_rated_throughput")}><span class="lbl">${esc(t.remaining_throughput)}</span>
        <span class="mid">${this._fmt(remaining, 0)} <span class="lbl">${esc(fill(t.of_total, { total: this._fmt(total, 0) }))}</span></span></div>
      <div class="bar"${this._ent("remaining_rated_throughput")}><div class="fill" style="width:${pct(remaining)}%;background:var(--bl-tp)"></div>
        ${leftAtEnd !== null ? `<div class="mark" style="left:${pct(leftAtEnd)}%;background:var(--bl-muted)"></div>` : ""}</div>
      <div class="spread">
        <span class="lbl"${this._ent("projected_warranted_throughput")}>${leftAtEnd !== null ? esc(fill(t.left_at_end, { kwh: this._fmt(leftAtEnd, 0) })) : ""}</span>
        <span class="lbl"${this._ent("rated_throughput_used")}>${used !== null ? esc(fill(t.used, { kwh: this._fmt(used, 0) })) : ""}</span>
      </div></section>`;
  }

  _financials(t, setup) {
    const d = setup.settings.cost_decimals;
    // When both cost per kWh figures read the same (e.g. the throughput allowance will all be used before the
    // date end), show the one figure at the size of the others; otherwise both, labelled.
    const byUsage = this._money(this._num("cost_per_kwh_rated"), d);
    const byAge = this._money(this._num("cost_per_kwh_projected"), d);
    const costTile = byUsage === byAge
      ? `<div class="tile value"${this._ent("cost_per_kwh_rated")}><div class="lbl">${esc(t.cost_per_kwh)}</div>
        <div class="big">${esc(byUsage)}</div></div>`
      : `<div class="tile value"><div class="lbl">${esc(t.cost_per_kwh)}</div>
        <div class="pair">
        <div class="mid"${this._ent("cost_per_kwh_rated")}>${esc(byUsage)} <span class="lbl">${esc(t.rated)}</span></div>
        <div class="mid"${this._ent("cost_per_kwh_projected")}>${esc(byAge)} <span class="lbl">${esc(t.projected)}</span></div></div></div>`;
    return `<section class="financials"><div class="tiles">
      <div class="tile value"${this._ent("cost_consumed_to_date")}><div class="lbl">${esc(t.cost_consumed)}</div>
        <div class="big">${esc(this._money(this._num("cost_consumed_to_date"), 2))}</div></div>
      <div class="tile value"${this._ent("cost_consumed_to_date")}><div class="lbl">${esc(t.remaining_value)}</div>
        <div class="big">${esc(this._money(parseFloat(this._attr("cost_consumed_to_date", "estimated_remaining_value")), 2))}</div></div>
      ${costTile}
      ${this._export(t, d)}
    </div></section>`;
  }

  // Export Cost (what a home energy manager is given) and its basis, which admins can change.
  _export(t, d) {
    const cost = this._num("cost_per_kwh_export");
    const selId = this._setup.entities.export_cost_basis;
    const sel = selId ? this._hass.states[selId] : null;
    if (cost === null && !sel) return "";
    const basis = this._attr("cost_per_kwh_export", "basis");
    const label = basis ? t[`basis_${basis}`] || basis : "";
    const options = sel?.attributes.options || [];
    const control = !sel ? "" : this._hass.user?.is_admin
      ? `<select class="basis" aria-label="${esc(t.export_basis)}">${options.map((o) => `<option value="${esc(o)}"${o === sel.state ? " selected" : ""}>${esc(t[`option_${o}`] || o)}</option>`).join("")}</select>`
      : `<span class="lbl">${esc(t[`option_${sel.state}`] || sel.state)}</span>`;
    return `<div class="tile value"><div class="lbl"${this._ent("cost_per_kwh_export")}>${esc(t.export_cost)}</div>
      <div class="mid"${this._ent("cost_per_kwh_export")}>${esc(this._money(cost, d))} <span class="lbl">${esc(label)}</span></div>
      ${sel ? `<div class="basis-row"><div class="lbl">${esc(t.export_basis)}</div>${control}</div>` : ""}
    </div>`;
  }

  // "Not Configured" with a cog: for admins, a link to this setup on BatteryLedger's integration page,
  // where Configure → Sensors and currency chooses the SoH sensor.
  _noSohHtml(t, src, setup) {
    const text = esc(this._noSohText(t, src, setup));
    if (!(!src.configured && src.available === true)) return text;
    if (!this._hass?.user?.is_admin) return text;
    const href = `/config/integrations/integration/battery_ledger#config_entry=${encodeURIComponent(setup.entry_id)}`;
    return `<a class="setup-link" href="${href}">${text} <ha-icon icon="mdi:cog"></ha-icon></a>`;
  }

  _noSohText(t, src, setup) {
    const brand = [...new Set((setup.groups || []).map((g) => g.brand).filter(Boolean))].join(" / ");
    // The battery doesn't provide SoH through this integration (from its Store profile, e.g. Huawei on Huawei
    // Solar or Energy Manager): say so for the brand. A chosen sensor that's empty for a battery that does
    // provide it is a setup problem with that integration: "No SoH reading from <integration>".
    if (src.available === false && brand) return fill(t.soh_unavailable, { brand });
    if (src.configured) return src.source ? fill(t.soh_no_reading, { source: src.source }) : t.soh_no_reading_unknown;
    if (src.available === true) return t.soh_not_set_up;
    return t.soh_not_configured;
  }

  _health(t, setup) {
    const initial = this._num("initial_usable_capacity");
    const g = this._picked();  // a chosen group: its warranty curve against the battery's reported SoH
    const curve = g ? g.warranty_floor_pct : this._num("estimated_usable_capacity");  // warranty-allowed SoH today
    const curveKwh = g ? g.warranty_floor_kwh : parseFloat(this._attr("estimated_usable_capacity", "remaining_usable_kwh"));
    const bms = parseFloat(this._attr("soh_above_warranty_floor", "reported_soh_pct"));
    // Measured SoH: with towers, a chosen group's own (from its towers); otherwise the whole battery's
    const towers = this._attr("measured_usable_capacity", "towers");
    const groupMeasured = g && Array.isArray(towers) && towers.length ? g.measured_soh_pct : undefined;
    const measured = groupMeasured !== undefined ? (Number.isFinite(groupMeasured) ? groupMeasured : null)
      : this._num("measured_soh");
    // A group's own measured SoH is against that group's usable capacity when new (floor kWh ÷ floor %)
    const capacityNew = Number.isFinite(groupMeasured) && g.warranty_floor_pct
      ? g.warranty_floor_kwh / g.warranty_floor_pct * 100 : initial;
    // The battery's own SoH first; without one, the SoH measured from charge and discharge runs
    const fromMeasured = !Number.isFinite(bms) && measured !== null;
    const soh = fromMeasured ? measured : bms;
    const hasSoh = Number.isFinite(soh);
    const margin = g || fromMeasured ? (hasSoh && curve != null ? soh - curve : null) : this._num("soh_above_warranty_floor");
    const sohEnt = fromMeasured ? "measured_soh" : "soh_above_warranty_floor";
    const eols = g ? [g.end_of_warranty_capacity_pct] : setup.groups.map((x) => x.eol_capacity_pct);
    const eolList = eols.filter((v) => Number.isFinite(v));
    const eol = eolList.length ? Math.max(...eolList) : 60;
    const span = Math.max(1, 100 - eol);
    const pos = (v) => Math.max(0, Math.min(100, (v - eol) / span * 100)).toFixed(2);
    const driver = g ? t[`driver_${g.driver}`] || g.driver : this._attr("estimated_usable_capacity", "degradation_driver");

    let chip = "";
    if (margin !== null) {
      const cls = margin >= 0 ? "ok" : "bad";
      chip = `<span class="chip ${cls}"${this._ent(sohEnt)}>${esc(fill(margin >= 0 ? t.above : t.below, { pct: this._fmt(Math.abs(margin), 1) }))}</span>`;
    }
    // A cross-check under the battery's own SoH, or how far the measuring has got
    let measuredLine = "";
    const measuring = !hasSoh && this._attr("measured_usable_capacity", "status") === "insufficient";
    if (!fromMeasured && measured !== null) {
      measuredLine = `<div class="lbl"${this._ent("measured_soh")}>${esc(fill(t.measured_line, { pct: this._fmt(measured, 1) }))}</div>`;
    } else if (measuring) {
      // One line per direction still short of its runs; a direction without an energy counter isn't measured (null)
      const need = 3;
      const items = [["charge_runs", t.measuring_charges], ["discharge_runs", t.measuring_discharges]]
        .map(([key, text]) => [this._attr("measured_usable_capacity", key), text])
        .filter(([runs]) => Number.isFinite(runs) && runs < need)
        .map(([runs, text]) => `<li>${esc(fill(text, { runs, need }))}</li>`).join("");
      measuredLine = `<div class="lbl" style="margin-top:6px"${this._ent("measured_usable_capacity")}>${esc(t.measuring)}
        <ul style="margin:2px 0 0;padding-left:18px">${items}</ul></div>`;
    }
    const actualTile = hasSoh
      ? `<div class="tile"${this._ent(sohEnt)}><div class="lbl">${esc(fromMeasured ? t.actual_soh_measured : t.actual_soh)}</div>
          <div class="big">${this._fmt(soh, 1)}%</div>
          <div class="lbl">${capacityNew !== null ? esc(fill(t.usable, { kwh: this._fmt(capacityNew * soh / 100, 1) })) : ""}</div>${measuredLine}</div>`
      : `<div class="tile"><div class="lbl">${esc(t.actual_soh)}</div>${measuring ? measuredLine
          : `<div class="lbl" style="margin-top:6px">${this._noSohHtml(t, setup.soh || {}, setup)}</div>`}</div>`;
    const curveTile = `<div class="tile"${this._ent("estimated_usable_capacity")}><div class="lbl">${esc(t.warranty_allows)}</div>
          <div class="big">${this._fmt(curve, 1)}%</div>
          <div class="lbl">${Number.isFinite(curveKwh) ? `${this._fmt(curveKwh, 1)} kWh` : ""}${driver ? ` · ${esc(driver)}` : ""}</div></div>`;
    const sohColor = !hasSoh ? "var(--bl-tile)" : margin !== null && margin < 0 ? "var(--bl-bad)" : "var(--bl-time)";

    return `<section class="health">
      <div class="section-head"><span class="t">${esc(t.health)}</span>${chip}</div>
      <div class="tiles">${actualTile}${curveTile}</div>
      <div class="bar" style="margin-top:14px"><div class="fill" style="width:${hasSoh ? pos(soh) : 0}%;background:${sohColor}"></div>
        ${curve !== null ? `<div class="mark" style="left:${pos(curve)}%;background:var(--bl-warn)"></div>` : ""}</div>
      <div class="spread"><span class="lbl">${esc(fill(t.eol, { pct: this._fmt(eol, 0) }))}</span>
        <span class="lbl" style="color:var(--bl-warn)">${curve !== null ? esc(fill(t.curve, { pct: this._fmt(curve, 1) })) : ""}</span>
        <span class="lbl">100%</span></div>
    </section>`;
  }

  // Bottom row: the hardware check and module figures (with the Health section) and the settings cog.
  _footer(t, withHealth) {
    const extra = [];
    if (withHealth) {
      const hw = this._state("hardware_capacity_validation");
      const hwOk = hw?.state === "Match Verified";
      if (hw) {
        const conf = hw.attributes.configured_rated_kwh, rep = hw.attributes.reported_hardware_kwh;
        extra.push(`<div class="lbl"${this._ent("hardware_capacity_validation")}><ha-icon icon="${hwOk ? "mdi:shield-check-outline" : "mdi:shield-alert-outline"}" style="--mdc-icon-size:16px;color:${hwOk ? "var(--bl-ok)" : "var(--bl-bad)"}"></ha-icon>
          ${esc(t.hardware)} ${esc(hw.state)}${conf != null && rep != null ? ` (${esc(conf)} / ${esc(rep)} kWh)` : ""}</div>`);
      }
      const mu = this._num("most_used_module_throughput");
      if (mu !== null) extra.push(`<div class="lbl"${this._ent("most_used_module_throughput")}>${esc(t.most_used_module)} ${this._fmt(mu, 1)}%</div>`);
      const spread = this._num("module_soc_spread");
      if (spread !== null) extra.push(`<div class="lbl"${this._ent("module_soc_spread")}>${esc(t.soc_spread)} ${this._fmt(spread, 1)}%</div>`);
    }
    const cog = this._hass.user?.is_admin
      ? `<ha-icon-button class="cog" label="${esc(t.settings_button)}" title="${esc(t.settings_button)}"><ha-icon icon="mdi:cog"></ha-icon></ha-icon-button>`
      : "";
    // Bottom right: the cog (admins), then the integration version, e.g. v0.1.10.
    const version = CARD_VERSION !== "dev" ? `<span class="ver">v${esc(CARD_VERSION)}</span>` : "";
    if (!extra.length && !cog && !version) return "";
    return `<div class="foot${extra.length ? "" : " bare"}">${extra.length ? `<div class="lines">${extra.join("")}</div>` : ""}<div class="end">${cog}${version}</div></div>`;
  }

  _onClick(ev) {
    const link = ev.composedPath().find((n) => n.classList && n.classList.contains("setup-link"));
    if (link) {
      // Navigate inside Home Assistant (no page reload), as the frontend's own links do
      ev.preventDefault();
      history.pushState(null, "", link.getAttribute("href"));
      window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      return;
    }
    const el = ev.composedPath().find((n) => n.dataset && n.dataset.entity);
    if (!el) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: el.dataset.entity }, bubbles: true, composed: true }));
  }

  // --- settings window -----------------------------------------------------------------------------
  _openSettings() {
    const setup = this._setup;
    if (!setup) return;
    const t = strings(this._hass);
    const s = setup.settings;
    const modal = this.shadowRoot.getElementById("modal");
    const decimals = DECIMAL_CHOICES.includes(s.cost_decimals) ? DECIMAL_CHOICES : [...DECIMAL_CHOICES, s.cost_decimals].sort();
    modal.innerHTML = `<div class="overlay"><div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(t.settings)}">
      <h3>${esc(t.settings)}</h3>
      <div class="pane" id="pane-display">
        <label for="dec">${esc(t.cost_decimals)}</label>
        <select id="dec">${decimals.map((d) => `<option value="${d}"${d === s.cost_decimals ? " selected" : ""}>${d}</option>`).join("")}</select>
        <label for="datefmt">${esc(t.date_style)}</label>
        <select id="datefmt">${DATE_STYLES.map((k) => `<option value="${k}"${k === (s.date_style || "ha") ? " selected" : ""}>${esc(t[`date_style_${k}`])}</option>`).join("")}</select>
        <label>${esc(t.sections)}</label>
        ${SECTIONS.map((k) => `<div class="check"><input type="checkbox" id="sec-${k}"${s.sections[k] ? " checked" : ""}><span>${esc(t[`section_${k}`])}</span></div>`).join("")}
        <div class="err" id="err" hidden>${esc(t.save_failed)}</div>
        <div class="buttons"><button id="cancel">${esc(t.cancel)}</button><button class="primary" id="save">${esc(t.save)}</button></div>
      </div>
    </div></div>`;
    const close = () => { modal.innerHTML = ""; };
    modal.querySelector(".overlay").addEventListener("click", (ev) => { if (ev.target === ev.currentTarget) close(); });
    modal.querySelector("#cancel").addEventListener("click", close);
    modal.querySelector(".dialog").addEventListener("keydown", (ev) => { if (ev.key === "Escape") close(); });
    modal.querySelector("#save").addEventListener("click", async () => {
      const settings = {
        cost_decimals: Number(modal.querySelector("#dec").value),
        date_style: modal.querySelector("#datefmt").value,
        sections: Object.fromEntries(SECTIONS.map((k) => [k, modal.querySelector(`#sec-${k}`).checked])),
      };
      try {
        const res = await this._hass.callWS({ type: WS_SAVE, entry_id: setup.entry_id, settings });
        setup.settings = res.settings;
        close();
        this._lastKey = "";
        this._render();
      } catch (err) {
        modal.querySelector("#err").hidden = false;
      }
    });
    modal.querySelector("#dec").focus();
  }
}

class BatteryLedgerCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._setups && !this._loading) {
      this._loading = true;
      hass.callWS({ type: WS_SETUPS }).then((r) => { this._setups = r.setups || []; this._render(); })
        .catch(() => { this._setups = []; this._render(); });
    }
  }

  _render() {
    if (!this._hass || !this._setups) return;
    const t = strings(this._hass);
    const current = this._config.entry_id || this._setups[0]?.entry_id || "";
    this.innerHTML = `<div style="display:grid;gap:8px;padding:8px 0">
      <label style="font-size:13px;color:var(--secondary-text-color)">${esc(t.editor_setup)}</label>
      <select style="padding:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);font:inherit">
        ${this._setups.map((s) => `<option value="${esc(s.entry_id)}"${s.entry_id === current ? " selected" : ""}>${esc(s.title)}</option>`).join("")}
      </select>
      <div style="font-size:12px;color:var(--secondary-text-color)">${esc(t.editor_hint)}</div></div>`;
    this.querySelector("select").addEventListener("change", (ev) => {
      this._config = { ...this._config, entry_id: ev.target.value };
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    });
  }
}

if (!customElements.get("battery-ledger-card")) customElements.define("battery-ledger-card", BatteryLedgerCard);
if (!customElements.get("battery-ledger-card-editor")) customElements.define("battery-ledger-card-editor", BatteryLedgerCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "battery-ledger-card")) {
  window.customCards.push({
    type: "battery-ledger-card",
    name: STRINGS.en.card_name,
    description: STRINGS.en.card_description,
    preview: true,
    documentationURL: "https://github.com/Roving-Ronin/BatteryLedger",
  });
}
console.info(`%c BATTERYLEDGER-CARD %c ${CARD_VERSION} `, "color:#fff;background:#185fa5;font-weight:500", "color:#185fa5");
