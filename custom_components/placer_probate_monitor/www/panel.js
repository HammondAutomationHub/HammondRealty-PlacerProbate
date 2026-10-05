class PlacerProbateFubPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._root = null;
    this._catalog = { probate_fields: [], send_toggles: [], go_no_go: [], default_custom_fields: {} };
    this._fubFields = [];
    this._ready = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ready) {
      this._ready = true;
      this._renderShell();
      this._load(false);
    }
  }

  get hass() {
    return this._hass;
  }

  _esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  _qs(sel) {
    return this._root.querySelector(sel);
  }

  _renderShell() {
    this.innerHTML = `
      <style>
        .ppm-wrap { font: 15px/1.45 "Segoe UI", system-ui, sans-serif; color: #1c1915; background: #f7f3ec; min-height: 100%; }
        .ppm-wrap header { background: #1b2a4a; color: #f7f3ec; padding: 20px 24px; }
        .ppm-wrap header p { margin: 4px 0 0; color: #c9c3b8; font-size: 13px; }
        .ppm-wrap h1 { margin: 0; font-size: 22px; }
        .ppm-wrap h2 { margin: 0 0 12px; font-size: 15px; text-transform: uppercase; color: #1b2a4a; }
        .ppm-wrap main { padding: 20px; display: grid; gap: 16px; max-width: 1100px; }
        .ppm-card { background: #fffdf8; border: 1px solid #ddd6cc; border-radius: 10px; padding: 16px 18px; }
        .ppm-wrap label { display: block; font-size: 12px; font-weight: 600; color: #6b645b; margin: 10px 0 4px; }
        .ppm-wrap input, .ppm-wrap textarea {
          width: 100%; border: 1px solid #ddd6cc; border-radius: 6px; padding: 8px 10px; font: inherit; box-sizing: border-box;
        }
        .ppm-wrap textarea { min-height: 64px; }
        .ppm-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .ppm-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
        .ppm-wrap button { border: 0; border-radius: 6px; padding: 8px 12px; font: inherit; cursor: pointer; background: #1b2a4a; color: #fff; }
        .ppm-wrap button.secondary { background: #ece7de; color: #1c1915; }
        .ppm-note { color: #6b645b; font-size: 12px; margin-top: 8px; }
        .ppm-banner { padding: 8px 10px; border-radius: 6px; margin-bottom: 10px; display: none; }
        .ppm-banner.show { display: block; }
        .ppm-banner.ok { background: #e7f4ec; color: #2d6a4f; }
        .ppm-banner.err { background: #f8e8e8; color: #8b2e2e; }
        .ppm-wrap table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .ppm-wrap th, .ppm-wrap td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #ddd6cc; vertical-align: top; }
        .ppm-toggle { display: flex; gap: 8px; margin: 8px 0; align-items: flex-start; }
        .ppm-toggle input { width: auto; margin-top: 3px; }
        .ppm-pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #f8e8e8; color: #8b2e2e; font-size: 11px; }
      </style>
      <div class="ppm-wrap">
        <header>
          <h1>Probate → Follow Up Boss mapping</h1>
          <p>Associate extract fields with FUB Person, Event, and custom fields. Saves fub_mapping.yaml under /config/placer_probate_monitor/.</p>
        </header>
        <main>
          <div id="flash" class="ppm-banner"></div>
          <section class="ppm-card">
            <h2>Go / no-go</h2>
            <ul id="rules"></ul>
            <p class="ppm-note" id="path-line"></p>
          </section>
          <section class="ppm-card">
            <h2>Person &amp; event sends</h2>
            <div id="toggles"></div>
            <div class="ppm-row">
              <div><label>Event system name</label><input id="system" /></div>
              <div><label>Subject address type</label><input id="subject_address_type" /></div>
            </div>
            <label>Court search URL</label>
            <input id="court_search_url" />
            <label>Skip petitioner names containing (one phrase per line)</label>
            <textarea id="skip_petitioner_contains"></textarea>
          </section>
          <section class="ppm-card">
            <h2>Custom field associations</h2>
            <p class="ppm-note">Create the custom field in Follow Up Boss first, then paste its API name (customCaseNumber). Blank means do not send.</p>
            <div class="ppm-actions" style="margin-top:0;">
              <button class="secondary" id="load-fub" type="button">Load FUB custom fields</button>
            </div>
            <p class="ppm-note" id="fub-fields-note"></p>
            <table><thead><tr><th>Probate field</th><th>Source</th><th>FUB custom field</th></tr></thead>
            <tbody id="matrix"></tbody></table>
            <div class="ppm-actions"><button id="save" type="button">Save mapping</button></div>
          </section>
        </main>
      </div>
    `;
    this._root = this;
    this._qs("#save").addEventListener("click", () => this._save());
    this._qs("#load-fub").addEventListener("click", () => this._load(true));
  }

  _flash(msg, ok) {
    const el = this._qs("#flash");
    el.textContent = msg;
    el.className = "ppm-banner show " + (ok ? "ok" : "err");
  }

  async _api(method, refresh) {
    const path = refresh
      ? "placer_probate_monitor/fub_mapping?refresh=1"
      : "placer_probate_monitor/fub_mapping";
    if (method === "GET") {
      return this._hass.callApi("GET", path);
    }
    return this._hass.callApi("POST", "placer_probate_monitor/fub_mapping", refresh);
  }

  _apply(data) {
    this._catalog = data.catalog || this._catalog;
    this._fubFields = data.fub_custom_fields || [];
    const mapping = data.mapping || {};
    const send = mapping.send || {};
    this._qs("#rules").innerHTML = (this._catalog.go_no_go || [])
      .map((line) => `<li>${this._esc(line)}</li>`).join("");
    this._qs("#path-line").textContent =
      "Saves to " + (data.path || "fub_mapping.yaml") + (data.exists ? "" : " (bundled defaults until you save)");
    this._qs("#system").value = mapping.system || "PlacerProbateMonitor";
    this._qs("#subject_address_type").value = mapping.subject_address_type || "subject property";
    this._qs("#court_search_url").value = mapping.court_search_url || "";
    this._qs("#skip_petitioner_contains").value = (mapping.skip_petitioner_contains || []).join("\n");
    this._qs("#toggles").innerHTML = (this._catalog.send_toggles || []).map((item) => {
      const on = item.forced === false ? false : send[item.key] !== false;
      const disabled = item.editable === false ? "disabled" : "";
      const reason = item.reason ? `<span class="ppm-note">${this._esc(item.reason)}</span>` : "";
      return `<label class="ppm-toggle"><input type="checkbox" data-send="${this._esc(item.key)}" ${on ? "checked" : ""} ${disabled} /><span>${this._esc(item.label)} ${reason}</span></label>`;
    }).join("");
    const defaults = this._catalog.default_custom_fields || {};
    const custom = mapping.custom_fields || {};
    const options = this._fubFields
      .map((f) => `<option value="${this._esc(f.name)}">${this._esc(f.label)} (${this._esc(f.name)})</option>`)
      .join("");
    this._qs("#matrix").innerHTML = (this._catalog.probate_fields || []).map((field) => {
      if (field.unavailable) {
        return `<tr><td><b>${this._esc(field.label)}</b></td><td>${this._esc(field.source)}</td><td><span class="ppm-pill">Not extracted</span></td></tr>`;
      }
      if (!field.custom) return "";
      const value = custom[field.key] ?? "";
      return `<tr><td><b>${this._esc(field.label)}</b><div class="ppm-note">${this._esc(field.key)}</div></td>
        <td>${this._esc(field.source)}</td>
        <td><input list="fub-custom-names" data-custom="${this._esc(field.key)}" value="${this._esc(value)}" placeholder="${this._esc(defaults[field.key] || "customFieldName")}" /></td></tr>`;
    }).join("") + `<datalist id="fub-custom-names">${options}</datalist>`;
    this._qs("#fub-fields-note").textContent = data.fub_custom_error
      ? data.fub_custom_error
      : (this._fubFields.length
        ? `Loaded ${this._fubFields.length} custom fields from Follow Up Boss.`
        : "Create matching custom fields in FUB, then load them here.");
  }

  _payload() {
    const send = {};
    this.querySelectorAll("[data-send]").forEach((el) => {
      send[el.dataset.send] = !!el.checked;
    });
    send.emails = false;
    send.phones = false;
    send.mailing_address = false;
    const custom_fields = {};
    this.querySelectorAll("[data-custom]").forEach((el) => {
      const value = el.value.trim();
      if (value) custom_fields[el.dataset.custom] = value;
    });
    return {
      system: this._qs("#system").value.trim(),
      subject_address_type: this._qs("#subject_address_type").value.trim(),
      court_search_url: this._qs("#court_search_url").value.trim(),
      skip_petitioner_contains: this._qs("#skip_petitioner_contains").value
        .split(/\n/).map((x) => x.trim()).filter(Boolean),
      send,
      custom_fields,
    };
  }

  async _load(refresh) {
    try {
      const data = await this._api("GET", refresh);
      this._apply(data);
      if (refresh) {
        this._flash(this._fubFields.length ? "Loaded FUB custom fields." : "No FUB fields loaded.", !!this._fubFields.length);
      }
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _save() {
    try {
      const data = await this._hass.callApi(
        "POST",
        "placer_probate_monitor/fub_mapping",
        this._payload(),
      );
      this._apply(data);
      this._flash("Mapping saved.", true);
    } catch (err) {
      this._flash(String(err), false);
    }
  }
}

customElements.define("placer-probate-fub-panel", PlacerProbateFubPanel);
