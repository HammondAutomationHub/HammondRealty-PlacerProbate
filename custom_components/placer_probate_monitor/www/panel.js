const PPM_CSS = `
  .ppm-wrap { font: 15px/1.45 "Segoe UI", system-ui, sans-serif; color: #1c1915; background: #f7f3ec; min-height: 100%; }
  .ppm-wrap header { background: #1b2a4a; color: #f7f3ec; padding: 20px 24px; }
  .ppm-wrap header p { margin: 4px 0 0; color: #c9c3b8; font-size: 13px; }
  .ppm-wrap h1 { margin: 0; font-size: 22px; }
  .ppm-wrap h2 { margin: 0 0 12px; font-size: 15px; text-transform: uppercase; color: #1b2a4a; }
  .ppm-wrap main { padding: 20px; display: grid; gap: 16px; max-width: 1180px; }
  .ppm-card { background: #fffdf8; border: 1px solid #ddd6cc; border-radius: 10px; padding: 16px 18px; }
  .ppm-wrap label { display: block; font-size: 12px; font-weight: 600; color: #6b645b; margin: 10px 0 4px; }
  .ppm-wrap input, .ppm-wrap textarea, .ppm-wrap select {
    width: 100%; border: 1px solid #ddd6cc; border-radius: 6px; padding: 8px 10px; font: inherit; box-sizing: border-box; background: #fff;
  }
  .ppm-wrap textarea { min-height: 64px; }
  .ppm-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .ppm-layout { display: grid; grid-template-columns: 220px 1fr; gap: 16px; align-items: start; }
  @media (max-width: 800px) { .ppm-layout, .ppm-row { grid-template-columns: 1fr; } }
  .ppm-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
  .ppm-wrap button { border: 0; border-radius: 6px; padding: 8px 12px; font: inherit; cursor: pointer; background: #1b2a4a; color: #fff; }
  .ppm-wrap button.secondary { background: #ece7de; color: #1c1915; }
  .ppm-wrap button.ghost { background: transparent; color: #f7f3ec; border: 1px solid #8a93a8; }
  .ppm-wrap button.ghost.active, .ppm-tabs button.active { background: #b0893e; border-color: #b0893e; color: #fff; }
  .ppm-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .ppm-note { color: #6b645b; font-size: 12px; margin-top: 8px; }
  .ppm-banner { padding: 8px 10px; border-radius: 6px; margin-bottom: 10px; display: none; }
  .ppm-banner.show { display: block; }
  .ppm-banner.ok { background: #e7f4ec; color: #2d6a4f; }
  .ppm-banner.err { background: #f8e8e8; color: #8b2e2e; }
  .ppm-wrap table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .ppm-wrap th, .ppm-wrap td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #ddd6cc; vertical-align: top; }
  .ppm-toggle { display: flex; gap: 8px; margin: 8px 0; align-items: flex-start; }
  .ppm-toggle input { width: auto; margin-top: 3px; }
  .ppm-pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #ece7de; font-size: 11px; }
  .ppm-pill.live { background: #e7f4ec; color: #2d6a4f; }
  .ppm-pill.wait { background: #f3e3c3; }
  .ppm-pill.off { background: #f8e8e8; color: #8b2e2e; }
  .ppm-sourcelist button { display: block; width: 100%; text-align: left; margin: 0 0 8px; background: #ece7de; color: #1c1915; }
  .ppm-sourcelist button.active { background: #1b2a4a; color: #fff; }
  .ppm-hide { display: none !important; }
`;

function ppmSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ppmRunJob(hass, action) {
  const before = await hass.callApi("GET", "placer_probate_monitor/job");
  const beforeRun = before.last_run;
  await hass.callApi("POST", "placer_probate_monitor/job", { action });
  for (let i = 0; i < 120; i += 1) {
    await ppmSleep(3000);
    const st = await hass.callApi("GET", "placer_probate_monitor/job");
    if (st.running) continue;
    if (st.last_run && st.last_run !== beforeRun) {
      return st;
    }
    if (i >= 1 && !st.running && st.last_error && st.last_run === beforeRun) {
      return st;
    }
  }
  return { last_result: "running", last_error: "Still running. Check the Status sensor." };
}

function ppmEsc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

class PlacerProbateSourcesPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._ready = false;
    this._source = "placer";
    this._data = { sources: [], placer: {}, fields: [] };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ready) {
      this._ready = true;
      this._renderShell();
      this._load();
    }
  }

  get hass() {
    return this._hass;
  }

  _qs(sel) {
    return this.querySelector(sel);
  }

  _flash(msg, ok) {
    const el = this._qs("#flash");
    el.textContent = msg;
    el.className = "ppm-banner show " + (ok ? "ok" : "err");
  }

  _renderShell() {
    this.innerHTML = `
      <style>${PPM_CSS}</style>
      <div class="ppm-wrap">
        <header>
          <h1>Probate data sources</h1>
          <p>County import settings and extracted-field catalogs. Follow Up Boss mapping is a separate sidebar item.</p>
        </header>
        <main>
          <div id="flash" class="ppm-banner"></div>
          <div class="ppm-layout">
            <aside class="ppm-card">
              <h2>Counties</h2>
              <div class="ppm-sourcelist" id="source-list"></div>
            </aside>
            <div id="source-body"></div>
          </div>
        </main>
      </div>
    `;
  }

  _renderList() {
    this._qs("#source-list").innerHTML = (this._data.sources || []).map((src) => {
      const pill = src.status === "live" ? "live" : "wait";
      const label = src.status === "live" ? "Live" : "Coming next";
      const active = src.id === this._source ? "active" : "";
      return `<button type="button" data-source="${ppmEsc(src.id)}" class="${active}">${ppmEsc(src.name)} <span class="ppm-pill ${pill}">${label}</span></button>`;
    }).join("");
    this.querySelectorAll("[data-source]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._source = btn.dataset.source;
        this._renderList();
        this._renderBody();
      });
    });
  }

  _renderBody() {
    const src = (this._data.sources || []).find((item) => item.id === this._source)
      || { id: this._source, name: this._source, status: "coming_soon", description: "", extracts: "" };
    const body = this._qs("#source-body");
    if (src.status !== "live") {
      body.innerHTML = `
        <section class="ppm-card">
          <h2>${ppmEsc(src.name)}</h2>
          <p>${ppmEsc(src.description)}</p>
          <p class="ppm-note">This source is not importable yet. Placer County is the live feed. Sacramento is next, then Nevada County.</p>
        </section>`;
      return;
    }
    const p = this._data.placer || {};
    const fields = this._data.fields || [];
    body.innerHTML = `
      <section class="ppm-card">
        <h2>Placer County import</h2>
        <p class="ppm-note">${ppmEsc(src.description)}</p>
        <div class="ppm-row">
          <div><label>Lookback days</label><input id="lookback_days" type="number" min="1" max="120" value="${ppmEsc(p.lookback_days ?? 21)}" /></div>
          <div><label>Lookahead days</label><input id="lookahead_days" type="number" min="0" max="120" value="${ppmEsc(p.lookahead_days ?? 21)}" /></div>
        </div>
        <div class="ppm-row">
          <div><label>County</label><input id="county" value="Placer" disabled /></div>
          <div>
            <label>Skip eCourt lookups</label>
            <select id="skip_portal"><option value="false">No</option><option value="true">Yes</option></select>
          </div>
        </div>
        <label>CNPA keywords</label>
        <input id="keywords" value="${ppmEsc(p.keywords || "")}" />
        <div class="ppm-row">
          <div>
            <label>Generate PDF</label>
            <select id="generate_pdf"><option value="true">Yes</option><option value="false">No</option></select>
          </div>
          <div><label>eCourt pause (seconds)</label><input id="ecourt_pause_seconds" type="number" step="0.1" min="0.5" max="10" value="${ppmEsc(p.ecourt_pause_seconds ?? 1.2)}" /></div>
        </div>
        <label>Max CNPA pages</label>
        <input id="max_search_pages" type="number" min="1" max="20" value="${ppmEsc(p.max_search_pages ?? 10)}" />
        <div class="ppm-actions">
          <button id="save-source" type="button">Save Placer import</button>
          <button class="secondary" id="run-source" type="button">Run Placer job</button>
        </div>
        <p class="ppm-note">Run imports this source only. Follow Up Boss create/verify is on the Follow Up Boss sidebar, not here.</p>
      </section>
      <section class="ppm-card">
        <h2>Extracted fields</h2>
        <p class="ppm-note">These are the Placer fields available to map in Follow Up Boss. Sacramento and Nevada will each have their own catalog.</p>
        <table>
          <thead><tr><th>Field</th><th>From</th><th>Status</th></tr></thead>
          <tbody>
            ${fields.map((field) => `
              <tr>
                <td><b>${ppmEsc(field.label)}</b><div class="ppm-note">${ppmEsc(field.key)}</div></td>
                <td>${ppmEsc(field.source)}</td>
                <td>${field.unavailable ? '<span class="ppm-pill off">Not extracted</span>' : '<span class="ppm-pill live">Available</span>'}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </section>
    `;
    this._qs("#skip_portal").value = String(!!p.skip_portal);
    this._qs("#generate_pdf").value = String(p.generate_pdf !== false);
    this._qs("#save-source").addEventListener("click", () => this._save());
    this._qs("#run-source").addEventListener("click", () => this._run());
  }

  async _load() {
    try {
      this._data = await this._hass.callApi("GET", "placer_probate_monitor/sources");
      this._renderList();
      this._renderBody();
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _save() {
    const body = {
      lookback_days: Number(this._qs("#lookback_days").value),
      lookahead_days: Number(this._qs("#lookahead_days").value),
      keywords: this._qs("#keywords").value,
      skip_portal: this._qs("#skip_portal").value === "true",
      generate_pdf: this._qs("#generate_pdf").value === "true",
      ecourt_pause_seconds: Number(this._qs("#ecourt_pause_seconds").value),
      max_search_pages: Number(this._qs("#max_search_pages").value),
    };
    try {
      this._data = await this._hass.callApi("POST", "placer_probate_monitor/sources", body);
      this._renderList();
      this._renderBody();
      this._flash("Placer import settings saved.", true);
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _run() {
    this._flash("Placer job started. CNPA and eCourt can take several minutes…", true);
    try {
      const st = await ppmRunJob(this._hass, "run");
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      const extra = st.new_count != null ? ` · ${st.new_count} new cases` : "";
      this._flash(
        ok
          ? `Placer job finished (${st.last_result || "ok"})${extra}`
          : (st.last_error || "Placer job failed. Check last_run.log."),
        ok,
      );
    } catch (err) {
      this._flash(String(err), false);
    }
  }
}

class PlacerProbateFubPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._catalog = { probate_fields: [], send_toggles: [], go_no_go: [], default_custom_fields: {} };
    this._fubFields = [];
    this._ready = false;
    this._tab = "connection";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._ready) {
      this._ready = true;
      this._renderShell();
      this._loadAll(false);
    }
  }

  get hass() {
    return this._hass;
  }

  _qs(sel) {
    return this.querySelector(sel);
  }

  _flash(msg, ok) {
    const el = this._qs("#flash");
    el.textContent = msg;
    el.className = "ppm-banner show " + (ok ? "ok" : "err");
  }

  _renderShell() {
    this.innerHTML = `
      <style>${PPM_CSS}</style>
      <div class="ppm-wrap">
        <header>
          <h1>Follow Up Boss</h1>
          <p>CRM connection, one-case verification, and field mapping. County import screens are under Probate sources.</p>
          <div class="ppm-tabs">
            <button class="ghost active" type="button" data-tab="connection">Connection &amp; verify</button>
            <button class="ghost" type="button" data-tab="mapping">Field mapping</button>
          </div>
        </header>
        <main>
          <div id="flash" class="ppm-banner"></div>
          <section class="ppm-card" id="tab-connection">
            <h2>Connection</h2>
            <label class="ppm-toggle"><input id="fub_enabled" type="checkbox" /><span>Enable Follow Up Boss export</span></label>
            <label>API URL</label>
            <input id="fub_api_url" />
            <label>API key (leave blank to keep the saved key)</label>
            <input id="fub_api_key" type="password" placeholder="unchanged if blank" />
            <p class="ppm-note" id="key-note"></p>
            <div class="ppm-row">
              <div><label>Lead source name</label><input id="fub_source" /></div>
              <div><label>Assign to</label><input id="fub_assigned_to" /></div>
            </div>
            <label>Event type</label>
            <select id="fub_event_type"></select>
            <label class="ppm-toggle"><input id="fub_strict_property" type="checkbox" /><span>Require decedent residence before upload</span></label>
            <label class="ppm-toggle"><input id="fub_verify_only" type="checkbox" /><span>Verify only: import one new go-case per run</span></label>
            <div class="ppm-actions">
              <button id="save-fub" type="button">Save FUB connection</button>
              <button class="secondary" id="preview-one" type="button">Preview one record</button>
              <button class="secondary" id="verify-fub" type="button">Verify one FUB import</button>
            </div>
            <p class="ppm-note">Preview one record retrieves a live go-case for display only. It ignores local seen/FUB status and does not post to Follow Up Boss. The record appears below.</p>
          </section>
          <section class="ppm-card" id="verify-record">
            <h2>Last verify record</h2>
            <p class="ppm-note">Run Verify one FUB import to show the go-case that was posted.</p>
          </section>
          <div id="tab-mapping" class="ppm-hide">
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
              <p class="ppm-note">These targets are Follow Up Boss fields. Source columns are from the selected county extract (currently Placer).</p>
              <div class="ppm-actions" style="margin-top:0;">
                <button class="secondary" id="load-fub" type="button">Load FUB custom fields</button>
              </div>
              <p class="ppm-note" id="fub-fields-note"></p>
              <table><thead><tr><th>Probate field</th><th>Source</th><th>FUB custom field</th></tr></thead>
              <tbody id="matrix"></tbody></table>
              <div class="ppm-actions"><button id="save" type="button">Save mapping</button></div>
            </section>
          </div>
        </main>
      </div>
    `;
    this.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => this._setTab(btn.dataset.tab));
    });
    this._qs("#save").addEventListener("click", () => this._saveMapping());
    this._qs("#load-fub").addEventListener("click", () => this._loadMapping(true));
    this._qs("#save-fub").addEventListener("click", () => this._saveSettings());
    this._qs("#verify-fub").addEventListener("click", () => this._verify());
    this._qs("#preview-one").addEventListener("click", () => this._preview());
  }

  _setTab(tab) {
    this._tab = tab;
    this.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    this._qs("#tab-connection").classList.toggle("ppm-hide", tab !== "connection");
    this._qs("#verify-record").classList.toggle("ppm-hide", tab !== "connection");
    this._qs("#tab-mapping").classList.toggle("ppm-hide", tab !== "mapping");
  }

  _applySettings(data) {
    this._qs("#fub_enabled").checked = !!data.fub_enabled;
    this._qs("#fub_api_url").value = data.fub_api_url || "https://api.followupboss.com/v1";
    this._qs("#fub_api_key").value = "";
    this._qs("#key-note").textContent = data.fub_api_key_set
      ? "An API key is already saved."
      : "No API key saved yet.";
    this._qs("#fub_source").value = data.fub_source || "probate";
    this._qs("#fub_assigned_to").value = data.fub_assigned_to || "";
    const types = data.event_types || ["Seller Inquiry"];
    this._qs("#fub_event_type").innerHTML = types
      .map((item) => `<option value="${ppmEsc(item)}">${ppmEsc(item)}</option>`)
      .join("");
    this._qs("#fub_event_type").value = data.fub_event_type || "Seller Inquiry";
    this._qs("#fub_strict_property").checked = !!data.fub_strict_property;
    this._qs("#fub_verify_only").checked = data.fub_verify_only !== false;
  }

  _renderVerify(st) {
    const el = this._qs("#verify-record");
    if (!el) return;
    const rec = st && st.fub_verify && !st.fub_verify.note ? st.fub_verify : null;
    const note = (st && (st.fub_verify_note || (st.fub_verify && st.fub_verify.note))) || "";
    if (!rec) {
      el.innerHTML = `<h2>Last preview / verify record</h2><p class="ppm-note">${ppmEsc(note || "Run Preview one record (view only) or Verify one FUB import.")}</p>`;
      return;
    }
    const addr = rec.address || {};
    const addrLine = [addr.street, addr.city, addr.state, addr.code].filter(Boolean).join(", ");
    const rows = [
      ["Gate", rec.gate || "go"],
      ["Data source", rec.data_source_name || rec.data_source || "Placer County"],
      ["Case number", rec.case_number],
      ["FUB person id", rec.fub_person_id],
      ["Petitioner", rec.petitioner],
      ["FUB firstName", rec.firstName],
      ["FUB lastName", rec.lastName],
      ["Assigned to", rec.assignedTo],
      ["Lead source", rec.lead_source],
      ["Event type", rec.event_type],
      ["Decedent", rec.decedent],
      ["Last residence", rec.decedent_residence],
      ["Address sent", addrLine],
      ["Hearing", rec.hearing],
      ["Notice URL", rec.notice_url],
      ["Court search", rec.court_search],
    ];
    const custom = (rec.custom_fields || []).map((item) =>
      `<tr><td>${ppmEsc(item.probate_field)}</td><td>${ppmEsc(item.fub_field)}</td><td>${ppmEsc(item.value)}</td></tr>`
    ).join("");
    el.innerHTML = `
      <h2>${rec.view_only ? "Last preview record" : "Last verify record"}</h2>
      <p class="ppm-note">${rec.view_only
        ? "View only. This case was not posted to Follow Up Boss and local seen status was not changed."
        : "This is the single go-case posted to Follow Up Boss. Confirm it in FUB, then turn off Verify only."}</p>
      <span class="ppm-pill ${rec.view_only ? "wait" : "live"}">${rec.view_only ? "VIEW ONLY" : "GO · POSTED"}</span>
      <table>
        <tbody>
          ${rows.map((item) => `<tr><th>${ppmEsc(item[0])}</th><td>${item[1] ? ppmEsc(item[1]) : "—"}</td></tr>`).join("")}
        </tbody>
      </table>
      ${custom ? `<h2 style="margin-top:16px;">Custom fields sent</h2><table><thead><tr><th>Probate</th><th>FUB</th><th>Value</th></tr></thead><tbody>${custom}</tbody></table>` : ""}
    `;
  }

  _applyMapping(data) {
    this._catalog = data.catalog || this._catalog;
    this._fubFields = data.fub_custom_fields || [];
    const mapping = data.mapping || {};
    const send = mapping.send || {};
    this._qs("#rules").innerHTML = (this._catalog.go_no_go || [])
      .map((line) => `<li>${ppmEsc(line)}</li>`).join("");
    const sourceName = this._catalog.data_source_name || "Placer County";
    this._qs("#path-line").textContent =
      "Mapping file: " + (data.path || "fub_mapping.yaml")
      + " · Source fields: " + sourceName
      + (data.exists ? "" : " (bundled defaults until you save)");
    this._qs("#system").value = mapping.system || "PlacerProbateMonitor";
    this._qs("#subject_address_type").value = mapping.subject_address_type || "subject property";
    this._qs("#court_search_url").value = mapping.court_search_url || "";
    this._qs("#skip_petitioner_contains").value = (mapping.skip_petitioner_contains || []).join("\n");
    this._qs("#toggles").innerHTML = (this._catalog.send_toggles || []).map((item) => {
      const on = item.forced === false ? false : send[item.key] !== false;
      const disabled = item.editable === false ? "disabled" : "";
      const reason = item.reason ? `<span class="ppm-note">${ppmEsc(item.reason)}</span>` : "";
      return `<label class="ppm-toggle"><input type="checkbox" data-send="${ppmEsc(item.key)}" ${on ? "checked" : ""} ${disabled} /><span>${ppmEsc(item.label)} ${reason}</span></label>`;
    }).join("");
    const defaults = this._catalog.default_custom_fields || {};
    const custom = mapping.custom_fields || {};
    const options = this._fubFields
      .map((f) => `<option value="${ppmEsc(f.name)}">${ppmEsc(f.label)} (${ppmEsc(f.name)})</option>`)
      .join("");
    this._qs("#matrix").innerHTML = (this._catalog.probate_fields || []).map((field) => {
      if (field.unavailable) {
        return `<tr><td><b>${ppmEsc(field.label)}</b></td><td>${ppmEsc(field.source)}</td><td><span class="ppm-pill off">Not extracted</span></td></tr>`;
      }
      if (!field.custom) return "";
      const value = custom[field.key] ?? "";
      return `<tr><td><b>${ppmEsc(field.label)}</b><div class="ppm-note">${ppmEsc(field.key)}</div></td>
        <td>${ppmEsc(field.source)}</td>
        <td><input list="fub-custom-names" data-custom="${ppmEsc(field.key)}" value="${ppmEsc(value)}" placeholder="${ppmEsc(defaults[field.key] || "customFieldName")}" /></td></tr>`;
    }).join("") + `<datalist id="fub-custom-names">${options}</datalist>`;
    this._qs("#fub-fields-note").textContent = data.fub_custom_error
      ? data.fub_custom_error
      : (this._fubFields.length
        ? `Loaded ${this._fubFields.length} custom fields from Follow Up Boss.`
        : "Create matching custom fields in FUB, then load them here.");
  }

  _mappingPayload() {
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

  async _loadAll(refreshMapping) {
    try {
      const [settings, mapping, job] = await Promise.all([
        this._hass.callApi("GET", "placer_probate_monitor/fub_settings"),
        this._hass.callApi("GET", refreshMapping
          ? "placer_probate_monitor/fub_mapping?refresh=1"
          : "placer_probate_monitor/fub_mapping"),
        this._hass.callApi("GET", "placer_probate_monitor/job").catch(() => ({})),
      ]);
      this._applySettings(settings);
      this._applyMapping(mapping);
      this._renderVerify(job);
      if (refreshMapping) {
        this._flash(this._fubFields.length ? "Loaded FUB custom fields." : "No FUB fields loaded.", !!this._fubFields.length);
      }
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _loadMapping(refresh) {
    await this._loadAll(refresh);
  }

  async _saveSettings() {
    const body = {
      fub_enabled: this._qs("#fub_enabled").checked,
      fub_api_url: this._qs("#fub_api_url").value.trim(),
      fub_api_key: this._qs("#fub_api_key").value,
      fub_source: this._qs("#fub_source").value.trim(),
      fub_assigned_to: this._qs("#fub_assigned_to").value.trim(),
      fub_event_type: this._qs("#fub_event_type").value,
      fub_strict_property: this._qs("#fub_strict_property").checked,
      fub_verify_only: this._qs("#fub_verify_only").checked,
    };
    try {
      const data = await this._hass.callApi("POST", "placer_probate_monitor/fub_settings", body);
      this._applySettings(data);
      this._flash("Follow Up Boss connection saved.", true);
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _saveMapping() {
    try {
      const data = await this._hass.callApi(
        "POST",
        "placer_probate_monitor/fub_mapping",
        this._mappingPayload(),
      );
      this._applyMapping(data);
      this._flash("FUB field mapping saved.", true);
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _verify() {
    this._flash("Verify started… scraping Placer, then importing one go-case.", true);
    try {
      const st = await ppmRunJob(this._hass, "verify");
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      this._renderVerify(st);
      const rec = st.fub_verify && !st.fub_verify.note ? st.fub_verify : null;
      this._flash(
        ok
          ? (rec
            ? `Verify posted ${rec.case_number} as FUB person ${rec.fub_person_id}.`
            : (st.fub_verify_note || "Verify finished. No new go-case was posted."))
          : (st.last_error || "Verify failed."),
        ok,
      );
    } catch (err) {
      this._flash(String(err), false);
    }
  }

  async _preview() {
    this._flash("Preview started… retrieving one live go-case (view only).", true);
    try {
      const st = await ppmRunJob(this._hass, "preview");
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      this._renderVerify(st);
      const rec = st.fub_verify && !st.fub_verify.note ? st.fub_verify : null;
      this._flash(
        ok
          ? (rec
            ? `Preview loaded ${rec.case_number} (not posted).`
            : (st.fub_verify_note || "Preview finished. No go-case in this window."))
          : (st.last_error || "Preview failed."),
        ok,
      );
    } catch (err) {
      this._flash(String(err), false);
    }
  }
}

customElements.define("placer-probate-sources-panel", PlacerProbateSourcesPanel);
customElements.define("placer-probate-fub-panel", PlacerProbateFubPanel);
