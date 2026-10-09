const PPM_CSS = `
  .ppm-wrap { font: 15px/1.45 "Segoe UI", system-ui, sans-serif; color: #1c1915; background: #f7f3ec; min-height: 100%; }
  .ppm-wrap header { background: #1b2a4a; color: #f7f3ec; padding: 20px 24px; }
  .ppm-wrap header p { margin: 4px 0 0; color: #c9c3b8; font-size: 13px; }
  .ppm-wrap h1 { margin: 0; font-size: 22px; }
  .ppm-wrap h2 { margin: 0 0 12px; font-size: 15px; text-transform: uppercase; color: #1b2a4a; }
  .ppm-wrap main { padding: 20px; display: grid; gap: 16px; max-width: 1180px; }
  .ppm-wrap main.ppm-wide { max-width: 1440px; }
  .ppm-fub-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; align-items: start; }
  .ppm-fub-side { position: sticky; top: 12px; max-height: calc(100vh - 28px); overflow: auto; }
  .ppm-assoc { font-size: 11px; color: #6b645b; }
  @media (max-width: 1100px) {
    .ppm-fub-layout { grid-template-columns: 1fr; }
    .ppm-fub-side { position: static; max-height: none; }
  }
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
  .ppm-banner { padding: 8px 10px; border-radius: 6px; margin-bottom: 10px; display: none; white-space: pre-wrap; }
  .ppm-banner.show { display: block; }
  .ppm-banner.ok { background: #e7f4ec; color: #2d6a4f; }
  .ppm-banner.err { background: #f8e8e8; color: #8b2e2e; }
  .ppm-banner.wait { background: #f3e3c3; color: #6b4f1a; }
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
  .ppm-wrap .ppm-tabs button.secondary.active { background: #1b2a4a; color: #fff; }
  .ppm-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 12px; }
  @media (max-width: 900px) { .ppm-compare { grid-template-columns: 1fr; } }
  .ppm-wrap td a { color: #1b2a4a; word-break: break-all; }
  .ppm-pre { white-space: pre-wrap; font: 12px/1.4 ui-monospace, Consolas, monospace; margin: 0; }
  .ppm-table-wrap { overflow-x: auto; }
  .ppm-wrap main.ppm-listings { max-width: 1440px; }
`;

function ppmSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function ppmText(value) {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value instanceof Error) return value.message || "Error";
  if (typeof value === "object") {
    if (typeof value.message === "string" && value.message) return value.message;
    if (typeof value.error === "string" && value.error) return value.error;
    if (value.error && typeof value.error === "object") return ppmText(value.error);
    if (typeof value.body === "string" && value.body) return value.body;
    try {
      const dumped = JSON.stringify(value);
      return dumped && dumped !== "{}" ? dumped : "Request failed";
    } catch (_exc) {
      return "Request failed";
    }
  }
  return String(value);
}

async function ppmRunJob(hass, action, extra, onTick) {
  const before = await hass.callApi("GET", "placer_probate_monitor/job");
  const beforeRun = before.last_run;
  try {
    await hass.callApi("POST", "placer_probate_monitor/job", { action, ...(extra || {}) });
  } catch (err) {
    const text = ppmText(err);
    if (!before.running && !/already in progress|409/i.test(text)) {
      throw new Error(text || "Could not start the job.");
    }
  }
  for (let i = 0; i < 1200; i += 1) {
    await ppmSleep(3000);
    const st = await hass.callApi("GET", "placer_probate_monitor/job");
    if (typeof onTick === "function") onTick(st);
    if (st.running) continue;
    if (st.last_run && st.last_run !== beforeRun) {
      return st;
    }
    if (i >= 1 && !st.running && st.last_error && st.last_run === beforeRun) {
      return st;
    }
  }
  const last = await hass.callApi("GET", "placer_probate_monitor/job").catch(() => ({}));
  const live = ppmJobLiveMessage(last);
  return {
    ...last,
    last_result: "running",
    last_error: live
      ? `Still running: ${live}`
      : "Still running after 60 minutes. The job keeps going in Home Assistant. Check Status or last_run.log.",
  };
}

function ppmBannerKind(ok) {
  if (ok === "wait" || ok === "running") return "wait";
  return ok ? "ok" : "err";
}

function ppmJobLiveMessage(st) {
  const p = (st && st.progress) || {};
  if (p.message) return p.message;
  if (st && st.running) return "Placer job is running…";
  return "";
}

function ppmJobDoneMessage(st) {
  if (!st) return "Job finished.";
  if (st.last_result === "running") {
    return ppmText(st.last_error) || "Still running. Check Status or last_run.log.";
  }
  const bits = [`Finished (${st.last_result || "ok"})`];
  const notices = st.notice_count != null ? st.notice_count : (st.progress && st.progress.notice_count);
  const neu = st.new_count != null ? st.new_count : (st.progress && st.progress.new_count);
  if (notices != null) bits.push(`${notices} unique CNPA notices`);
  if (neu != null) bits.push(`${neu} new`);
  if (st.fub_posted != null || st.fub_updated != null) {
    bits.push(
      `FUB posted ${st.fub_posted ?? 0}, updated ${st.fub_updated ?? 0}, skipped ${st.fub_skipped ?? 0}`,
    );
  }
  if (st.fub_error) bits.push(`FUB: ${ppmText(st.fub_error)}`);
  return bits.join(" · ");
}

function ppmEsc(value) {
  return ppmText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function ppmFubFieldSelect(key, selected, fubFields, builtins) {
  const known = new Set([
    ...((builtins || []).map((item) => item.name)),
    ...((fubFields || []).map((item) => item.name)),
  ]);
  const extra = (selected && !known.has(selected))
    ? `<option value="${ppmEsc(selected)}" selected>${ppmEsc(selected)} (saved)</option>`
    : "";
  const builtinOpts = (builtins || []).map((item) => {
    const sel = item.name === selected ? "selected" : "";
    const disabled = item.disabled ? "disabled" : "";
    return `<option value="${ppmEsc(item.name)}" ${sel} ${disabled}>${ppmEsc(item.label)} — ${ppmEsc(item.name)}</option>`;
  }).join("");
  const customOpts = (fubFields || []).map((item) => {
    const sel = item.name === selected ? "selected" : "";
    const type = item.type ? ` · ${item.type}` : "";
    return `<option value="${ppmEsc(item.name)}" ${sel}>${ppmEsc(item.label)} — ${ppmEsc(item.name)}${ppmEsc(type)}</option>`;
  }).join("");
  return `<select data-custom="${ppmEsc(key)}">
    <option value="">Do not map</option>
    ${extra}
    <optgroup label="Built-in Follow Up Boss fields">${builtinOpts || "<option disabled>None</option>"}</optgroup>
    <optgroup label="Custom fields">${customOpts || "<option disabled>None loaded</option>"}</optgroup>
  </select>`;
}

function ppmSourceGoNoGo(data, mapData, sourceId) {
  return (data && data.source_go_no_go && data.source_go_no_go[sourceId])
    || (mapData && mapData.source_go_no_go && mapData.source_go_no_go[sourceId])
    || (mapData && mapData.catalog && mapData.catalog.source_go_no_go && mapData.catalog.source_go_no_go[sourceId])
    || {};
}

function ppmGoNoGoInner(spec, sourceName) {
  const data = spec || {};
  const required = data.required || [];
  const optional = data.optional || [];
  const rules = data.rules || [];
  const reqRows = required.map((item) => `
    <tr>
      <td><span class="ppm-pill off">Required</span></td>
      <td><b>${ppmEsc(item.label)}</b><div class="ppm-note">${ppmEsc(item.key || "")}</div></td>
      <td>${ppmEsc(item.from || "")}</td>
    </tr>`).join("");
  const optRows = optional.map((item) => `
    <tr>
      <td><span class="ppm-pill wait">Optional</span></td>
      <td><b>${ppmEsc(item.label)}</b><div class="ppm-note">${ppmEsc(item.key || "")}</div></td>
      <td>${ppmEsc(item.from || "")}${item.when ? `<div class="ppm-note">${ppmEsc(item.when)}</div>` : ""}</td>
    </tr>`).join("");
  const rows = (reqRows + optRows)
    || `<tr><td colspan="3">No field checklist yet for ${ppmEsc(sourceName || "this source")}.</td></tr>`;
  const ruleList = rules.length
    ? `<ul>${rules.map((line) => `<li>${ppmEsc(line)}</li>`).join("")}</ul>`
    : "";
  return `
    <p class="ppm-note">${ppmEsc(sourceName || "This source")} only becomes a go-case when every required field is present. Missing required data is skipped, not sent as a partial Follow Up Boss person.</p>
    <table>
      <thead><tr><th></th><th>Field</th><th>From</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${ruleList}`;
}

function ppmGoNoGoCard(spec, sourceName) {
  return `
    <section class="ppm-card">
      <h2>Go / no-go data requirements</h2>
      ${ppmGoNoGoInner(spec, sourceName)}
    </section>`;
}

function ppmMappingRows(fields, custom, fubFields, person, builtins, defaults) {
  const titles = { petitioner: "Petitioner", decedent: "Decedent", other: "Case and other fields" };
  let lastGroup = "";
  return (fields || []).map((field) => {
    let header = "";
    const group = field.group || "";
    if (group && group !== lastGroup) {
      lastGroup = group;
      header = `<tr><td colspan="4"><b>${ppmEsc(titles[group] || group)}</b></td></tr>`;
    }
    if (!field.custom && field.unavailable) {
      return `${header}<tr><td><b>${ppmEsc(field.label)}</b></td><td>${ppmEsc(field.source)}</td><td colspan="2"><span class="ppm-pill off">Not extracted</span></td></tr>`;
    }
    if (!field.custom) return header;
    const value = (custom && custom[field.key]) || (defaults && defaults[field.key]) || "";
    const status = field.unavailable
      ? '<span class="ppm-pill wait">Extract later</span>'
      : '<span class="ppm-pill live">Available</span>';
    return `${header}<tr>
      <td><b>${ppmEsc(field.label)}</b><div class="ppm-note">${ppmEsc(field.key)}</div></td>
      <td>${ppmEsc(field.source)} ${status}</td>
      <td>${ppmFubFieldSelect(field.key, value, fubFields, builtins)}</td>
      <td data-fub-example>${ppmFubExampleCell(person, value)}</td>
    </tr>`;
  }).join("");
}

function ppmFubPersonLookup(person, name) {
  if (!person || !name) return "";
  const custom = (person.custom_fields || []).find((item) => item.name === name);
  if (custom && custom.value) return custom.value;
  const core = (person.core || []).find((item) => item.name === name);
  return (core && core.value) || "";
}

function ppmFubExampleCell(person, apiName) {
  if (!person) return '<span class="ppm-note">Pull an example person</span>';
  if (!apiName) return '<span class="ppm-note">Pick a FUB field</span>';
  const value = ppmFubPersonLookup(person, apiName);
  return value
    ? ppmCell(value)
    : '<span class="ppm-pill wait">Empty on this person</span>';
}

function ppmBindMappingExamples(root, person) {
  if (!root) return;
  root.querySelectorAll("select[data-custom]").forEach((el) => {
    el.addEventListener("change", () => {
      const cell = el.closest("tr") && el.closest("tr").querySelector("[data-fub-example]");
      if (cell) cell.innerHTML = ppmFubExampleCell(person, el.value.trim());
    });
  });
}

function ppmFieldAssociations(mapping, sourceId, catalogFields) {
  const source = sourceId || "placer";
  const custom = ((mapping && mapping.source_mappings && mapping.source_mappings[source]
    && mapping.source_mappings[source].custom_fields)
    || (source === "placer" && mapping && mapping.custom_fields)
    || {});
  const labels = {};
  (catalogFields || []).forEach((field) => {
    labels[field.key] = field.label || field.key;
  });
  const byFub = {};
  const add = (fubName, key) => {
    if (!fubName) return;
    byFub[fubName] = byFub[fubName] || [];
    if (!byFub[fubName].some((item) => item.key === key)) {
      byFub[fubName].push({ key, label: labels[key] || key });
    }
  };
  Object.keys(custom || {}).forEach((key) => add(custom[key], key));
  add("firstName", "petitioner_first");
  add("lastName", "petitioner_last");
  add("emails", "petitioner_email");
  add("phones", "petitioner_phone");
  add("assignedTo", "assignedTo");
  add("source", "lead_source");
  return byFub;
}

function ppmLiveClientHtml(person, associations) {
  if (!person || !person.person_id) {
    return `<p class="ppm-note">Pull a live Follow Up Boss contact to see its data and which probate fields map to it. This does not change FUB.</p>`;
  }
  const name = ppmFubPersonLookup(person, "name")
    || [ppmFubPersonLookup(person, "firstName"), ppmFubPersonLookup(person, "lastName")].filter(Boolean).join(" ");
  const assocOf = (fubName) => {
    const items = (associations && associations[fubName]) || [];
    if (!items.length) return '<div class="ppm-assoc">Not mapped from probate</div>';
    return `<div class="ppm-assoc">Mapped from ${items.map((item) => ppmEsc(item.label)).join(", ")}</div>`;
  };
  const core = (person.core || []).map((item) =>
    `<tr>
      <td><b>${ppmEsc(item.name)}</b>${assocOf(item.name)}</td>
      <td>${item.populated ? ppmCell(item.value) : "—"}</td>
      <td>${item.populated ? '<span class="ppm-pill live">Set</span>' : '<span class="ppm-pill wait">Empty</span>'}</td>
    </tr>`
  ).join("");
  const custom = (person.custom_fields || []).map((item) =>
    `<tr>
      <td><b>${ppmEsc(item.label)}</b><div class="ppm-note">${ppmEsc(item.name)}</div>${assocOf(item.name)}</td>
      <td>${item.populated ? ppmCell(item.value) : "—"}</td>
      <td>${item.populated ? '<span class="ppm-pill live">Set</span>' : '<span class="ppm-pill wait">Empty</span>'}</td>
    </tr>`
  ).join("");
  return `
    <p class="ppm-note"><b>${ppmEsc(name || person.person_id)}</b> · id ${ppmEsc(person.person_id)} · ${ppmEsc(person.custom_populated)}/${ppmEsc(person.custom_total)} custom fields set</p>
    <h2>Built-in fields</h2>
    <table><thead><tr><th>FUB field</th><th>Value</th><th></th></tr></thead><tbody>${core}</tbody></table>
    <h2 style="margin-top:16px;">Custom fields</h2>
    <table><thead><tr><th>FUB field</th><th>Value</th><th></th></tr></thead><tbody>${custom || "<tr><td colspan='3'>None</td></tr>"}</tbody></table>
  `;
}

function ppmPersonSnapshot(person) {
  if (!person || !person.person_id) {
    return `<p class="ppm-note">No Follow Up Boss person loaded yet.</p>`;
  }
  const name = ppmFubPersonLookup(person, "name")
    || [ppmFubPersonLookup(person, "firstName"), ppmFubPersonLookup(person, "lastName")].filter(Boolean).join(" ");
  const core = (person.core || []).filter((item) => item.populated).map((item) =>
    `<tr><th>${ppmEsc(item.name)}</th><td>${ppmCell(item.value)}</td></tr>`
  ).join("");
  const custom = (person.custom_fields || []).filter((item) => item.populated).map((item) =>
    `<tr><td><b>${ppmEsc(item.label)}</b><div class="ppm-note">${ppmEsc(item.name)}</div></td><td>${ppmCell(item.value)}</td></tr>`
  ).join("");
  return `
    <p class="ppm-note">Example person <b>${ppmEsc(name || person.person_id)}</b> · id ${ppmEsc(person.person_id)} · ${ppmEsc(person.custom_populated)} of ${ppmEsc(person.custom_total)} custom fields have values. This is a read-only FUB contact.</p>
    <table><thead><tr><th>Built-in field</th><th>Value</th></tr></thead><tbody>${core || "<tr><td colspan='2'>—</td></tr>"}</tbody></table>
    ${custom ? `<h2 style="margin-top:16px;">Populated custom fields</h2><table><thead><tr><th>FUB field</th><th>Value</th></tr></thead><tbody>${custom}</tbody></table>` : "<p class='ppm-note'>No custom fields are populated on this person.</p>"}
  `;
}

function ppmCompareExtractToFub(rec, person) {
  if (!rec || !person) return "";
  const rows = [
    ["firstName", rec.firstName, ppmFubPersonLookup(person, "firstName")],
    ["lastName", rec.lastName, ppmFubPersonLookup(person, "lastName")],
    ["assignedTo", rec.assignedTo, ppmFubPersonLookup(person, "assignedTo")],
    ["source", rec.lead_source, ppmFubPersonLookup(person, "source")],
  ];
  (rec.custom_fields || []).forEach((item) => {
    rows.push([item.fub_field, item.value, ppmFubPersonLookup(person, item.fub_field)]);
  });
  return `<h2 style="margin-top:16px;">Probate mapped value vs this FUB person</h2>
    <table><thead><tr><th>FUB field</th><th>This probate record</th><th>Example person</th></tr></thead>
    <tbody>${rows.map((item) => `<tr><th>${ppmEsc(item[0])}</th><td>${ppmCell(item[1])}</td><td>${item[2] ? ppmCell(item[2]) : "—"}</td></tr>`).join("")}</tbody></table>`;
}

async function ppmFetchFubPerson(hass, query) {
  return hass.callApi(
    "GET",
    "placer_probate_monitor/fub_person?q=" + encodeURIComponent(query),
  );
}

function ppmExamplePersonBar(query) {
  return `
    <div class="ppm-row">
      <div>
        <label>Example FUB person (id or name)</label>
        <input class="fub-person-q" placeholder="e.g. 12345 or Jane Doe" value="${ppmEsc(query || "")}" />
      </div>
    </div>
    <div class="ppm-actions" style="margin-top:8px;">
      <button class="secondary fub-person-load" type="button">Pull example person</button>
    </div>
    <div class="fub-person-shot"></div>
  `;
}

function ppmCell(value) {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (/^https?:\/\//i.test(text)) {
    return `<a href="${ppmEsc(text)}" target="_blank" rel="noopener">${ppmEsc(text)}</a>`;
  }
  return ppmEsc(text);
}

function ppmSkipTable(skips) {
  if (!skips || !skips.length) return "";
  const rows = skips.slice(0, 12).map((item) =>
    `<tr><td>${ppmEsc(item.case || "?")}</td><td>${ppmEsc(item.reason || "")}</td></tr>`
  ).join("");
  return `<h2 style="margin-top:16px;">Other cases in this window</h2>
    <p class="ppm-note">Quality gates still apply. Local seen/FUB status is ignored on preview.</p>
    <table><thead><tr><th>Case</th><th>Why not shown</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function ppmPreviewRecord(st) {
  const rec = st && st.fub_verify;
  if (!rec || (rec.note && !rec.case_number)) return null;
  return rec;
}

function ppmRenderPreview(el, st) {
  if (!el) return;
  const rec = ppmPreviewRecord(st);
  const note = (st && (st.fub_verify_note || (st.fub_verify && st.fub_verify.note))) || "";
  const skips = (st && st.fub_skips) || (rec && rec.skips) || [];
  if (!rec) {
    el.innerHTML = `<h2>Last live extract</h2>
      <p class="ppm-note">${ppmEsc(note || "Run Preview one extract or Verify one FUB import to show a go-case here.")}</p>
      ${ppmSkipTable(skips)}`;
    return;
  }
  const viewOnly = !!rec.view_only;
  const posted = !!rec.posted && !viewOnly;
  const updated = !!rec.updated && posted;
  const fubError = rec.fub_error || (st && st.fub_error) || "";
  let extract = rec.source_extract || [];
  if (!extract.length) {
    extract = [
      { label: "Case number", source: "CNPA / eCourt", value: rec.case_number, empty: !rec.case_number },
      { label: "Petitioner first name", source: "Split from petitioner", value: rec.firstName || rec.petitioner_first, empty: !(rec.firstName || rec.petitioner_first) },
      { label: "Petitioner last name", source: "Split from petitioner", value: rec.lastName || rec.petitioner_last, empty: !(rec.lastName || rec.petitioner_last) },
      { label: "Petitioner full name", source: "eCourt parties", value: rec.petitioner, empty: !rec.petitioner },
      { label: "Decedent", source: "CNPA / eCourt", value: rec.decedent, empty: !rec.decedent },
      { label: "Estate location", source: "DE-111 item 3.a.(2)", value: rec.decedent_residence, empty: !rec.decedent_residence },
      { label: "Petitioner address", source: "DE-111 item 8 / 3h + DE-147", value: rec.mailing_address, empty: !rec.mailing_address },
      { label: "Petitioner email", source: "DE-111 + DE-147", value: rec.petitioner_email, empty: !rec.petitioner_email },
      { label: "Petitioner phone", source: "DE-111 + DE-147", value: rec.petitioner_phone, empty: !rec.petitioner_phone },
      { label: "Hearing", source: "eCourt", value: rec.hearing, empty: !rec.hearing },
      { label: "Notice URL", source: "CNPA", value: rec.notice_url, empty: !rec.notice_url },
      { label: "Court case URL", source: "eCourt Public node/45", value: rec.court_url || rec.court_search, empty: !(rec.court_url || rec.court_search) },
    ];
  }
  const mapped = rec.mapped || {};
  const pulledRows = extract.map((item) => {
    const status = item.unavailable
      ? '<span class="ppm-pill off">Not extracted</span>'
      : (item.empty ? '<span class="ppm-pill wait">Empty</span>' : '<span class="ppm-pill live">Pulled</span>');
    return `<tr>
      <td><b>${ppmEsc(item.label)}</b><div class="ppm-note">${ppmEsc(item.source || item.key || "")}</div></td>
      <td>${item.unavailable ? "—" : ppmCell(item.value)}</td>
      <td>${status}</td>
    </tr>`;
  }).join("");
  const personRows = (mapped.person || []).map((item) =>
    `<tr><th>${ppmEsc(item.label)}</th><td>${ppmCell(item.value)}</td></tr>`
  ).join("");
  const custom = (rec.custom_fields || []).map((item) =>
    `<tr><td>${ppmEsc(item.probate_field)}</td><td>${ppmEsc(item.fub_field)}</td><td>${ppmCell(item.value)}</td></tr>`
  ).join("");
  const addr = rec.address || {};
  const addrLine = [addr.street, addr.city, addr.state, addr.code].filter(Boolean).join(", ");
  const mappedFallback = personRows || `
    <tr><th>firstName</th><td>${ppmCell(rec.firstName)}</td></tr>
    <tr><th>lastName</th><td>${ppmCell(rec.lastName)}</td></tr>
    <tr><th>assignedTo</th><td>${ppmCell(rec.assignedTo)}</td></tr>
    <tr><th>addresses</th><td>${ppmCell(addrLine)}</td></tr>
  `;
  const attach = rec.de111_attach || {};
  const attachLine = attach.ok
    ? (attach.reason === "notes_link"
      ? `${attach.file || "DE-111"} (Notes link${attach.uri ? `: ${attach.uri}` : ""})`
      : (attach.file ? `${attach.file} (${attach.reason || "attached"})` : (attach.reason || "attached")))
    : (attach.reason || (posted ? "not attached" : ""));
  const noGo = rec.gate === "no-go";
  const heading = noGo
    ? "Last live extract (no-go)"
    : (viewOnly
    ? "Last live extract (view only)"
    : (posted ? (updated ? "Last verify record (updated)" : "Last verify record (posted)") : "Last verify record"));
  const blurb = noGo
    ? `This case was skipped (${ppmEsc(rec.gate_reason || "no-go")}). Follow Up Boss was not updated.`
    : (viewOnly
    ? "This is one live go-case from Placer. Follow Up Boss was not updated."
    : (posted
      ? (updated
        ? "This existing Follow Up Boss person was updated with the current mapping, including the DE-111 on Files. Confirm Address 1/2, notes, name, and Files in FUB."
        : "This go-case was posted to Follow Up Boss, including the DE-111 on Files. Confirm it in FUB, then turn off Verify only.")
      : "This is the go-case Verify tried to upload. Follow Up Boss did not accept it."));
  const pill = noGo
    ? '<span class="ppm-pill off">NO-GO</span>'
    : (viewOnly
    ? '<span class="ppm-pill wait">VIEW ONLY</span>'
    : (posted
      ? (updated ? '<span class="ppm-pill live">GO · UPDATED</span>' : '<span class="ppm-pill live">GO · POSTED</span>')
      : '<span class="ppm-pill off">GO · NOT POSTED</span>'));
  el.innerHTML = `
    <h2>${heading}</h2>
    <p class="ppm-note">${blurb}</p>
    ${fubError ? `<div class="ppm-banner show err">${ppmEsc(fubError)}</div>` : ""}
    ${pill}
    <span class="ppm-pill">${ppmEsc(rec.case_number || "")}</span>
    ${posted && rec.fub_person_id ? `<span class="ppm-pill live">FUB person ${ppmEsc(rec.fub_person_id)}</span>` : ""}
    <div class="ppm-compare">
      <div>
        <h2>1. Pulled from Placer</h2>
        <p class="ppm-note">Check these against the notice, eCourt, and petition PDF.</p>
        <table>
          <thead><tr><th>Field</th><th>Value</th><th></th></tr></thead>
          <tbody>${pulledRows}</tbody>
        </table>
      </div>
      <div>
        <h2>2. How it looks for Follow Up Boss</h2>
        <p class="ppm-note">Person name is the petitioner. Decedent and counsel stay on custom fields.</p>
        <table>
          <tbody>
            ${mappedFallback}
            <tr><th>event type</th><td>${ppmCell(mapped.event_type || rec.event_type)}</td></tr>
            <tr><th>lead source</th><td>${ppmCell(mapped.lead_source || rec.lead_source)}</td></tr>
            <tr><th>system</th><td>${ppmCell(mapped.system)}</td></tr>
            ${attachLine && !viewOnly ? `<tr><th>Files</th><td>${ppmCell(attachLine)}</td></tr>` : ""}
            ${(rec.court_url || rec.court_search) ? `<tr><th>eCourt Public</th><td>${ppmCell((rec.court_url_note && rec.court_url_note.uri) || rec.court_url || rec.court_search)}</td></tr>` : ""}
          </tbody>
        </table>
        ${mapped.message ? `<label>Event message</label><p class="ppm-pre">${ppmCell(mapped.message)}</p>` : ""}
        ${mapped.description ? `<label>Event description</label><p class="ppm-pre">${ppmCell(mapped.description)}</p>` : ""}
        ${custom ? `<h2 style="margin-top:16px;">Custom fields</h2><table><thead><tr><th>Probate</th><th>FUB</th><th>Value</th></tr></thead><tbody>${custom}</tbody></table>` : ""}
      </div>
    </div>
    ${note && !posted ? `<p class="ppm-note">${ppmEsc(note)}</p>` : ""}
    ${ppmSkipTable(skips)}
  `;
}

class PlacerProbateSourcesPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._ready = false;
    this._source = "placer";
    this._data = { sources: [], placer: {}, fields: [], source_fields: {} };
    this._jobSt = {};
    this._mapData = { fub_custom_fields: [], mapping: {}, source_fields: {} };
    this._fubPerson = null;
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
    el.className = "ppm-banner show " + ppmBannerKind(ok);
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
      let pill = "wait";
      let label = "Coming next";
      if (src.status === "live" && src.enabled) {
        pill = "live";
        label = "On";
      } else if (src.status === "live") {
        pill = "off";
        label = "Off";
      }
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
    if (src.status === "live") {
      const on = !!src.enabled;
      const label = src.id === "sacramento" ? "Sacramento" : "Placer";
      const p = src.id === "sacramento" ? (this._data.sacramento || {}) : (this._data.placer || {});
      const keywords = src.id === "sacramento"
        ? '"NOTICE OF PETITION"'
        : (p.keywords || '"NOTICE OF PETITION TO ADMINISTER ESTATE"');
      const county = src.id === "sacramento" ? "Sacramento" : "Placer";
      const skipLabel = src.id === "sacramento" ? "Skip court-portal lookups" : "Skip eCourt lookups";
      const pauseLabel = src.id === "sacramento" ? "Portal pause (seconds)" : "eCourt pause (seconds)";
      const fields = (this._mapData.source_fields && this._mapData.source_fields[src.id])
        || this._data.fields || [];
      const custom = ((this._mapData.mapping && this._mapData.mapping.source_mappings
        && this._mapData.mapping.source_mappings[src.id]
        && this._mapData.mapping.source_mappings[src.id].custom_fields)
        || (src.id === "placer" && this._mapData.mapping && this._mapData.mapping.custom_fields)
        || {});
      body.innerHTML = `
        <section class="ppm-card">
          <h2>${ppmEsc(src.name)} import</h2>
          <p class="ppm-note">${ppmEsc(src.description)}</p>
          <div class="ppm-toggle">
            <input id="source_enabled" type="checkbox" ${on ? "checked" : ""} />
            <div>
              <label style="margin:0;">Use this county in the daily job</label>
              <p class="ppm-note" style="margin:4px 0 0;">Off keeps ${ppmEsc(label)} out of the scheduled run and Follow Up Boss import. The other county is unchanged.</p>
            </div>
          </div>
          <div class="ppm-row">
            <div><label>Lookback days</label><input id="lookback_days" type="number" min="1" max="120" value="${ppmEsc(p.lookback_days ?? 21)}" ${src.id === "sacramento" ? "disabled" : ""} /></div>
            <div><label>Lookahead days</label><input id="lookahead_days" type="number" min="0" max="120" value="${ppmEsc(p.lookahead_days ?? 21)}" ${src.id === "sacramento" ? "disabled" : ""} /></div>
          </div>
          <div class="ppm-row">
            <div><label>County</label><input id="county" value="${ppmEsc(county)}" disabled /></div>
            <div>
              <label>${ppmEsc(skipLabel)}</label>
              <select id="skip_portal" ${src.id === "sacramento" ? "disabled" : ""}><option value="false">No</option><option value="true">Yes</option></select>
            </div>
          </div>
          <label>CNPA keywords</label>
          <input id="keywords" value="${ppmEsc(keywords)}" ${src.id === "sacramento" ? "disabled" : ""} />
          <div class="ppm-row">
            <div>
              <label>Generate PDF</label>
              <select id="generate_pdf" ${src.id === "sacramento" ? "disabled" : ""}><option value="true">Yes</option><option value="false">No</option></select>
            </div>
            <div><label>${ppmEsc(pauseLabel)}</label><input id="ecourt_pause_seconds" type="number" step="0.1" min="0.5" max="10" value="${ppmEsc(p.ecourt_pause_seconds ?? 1.2)}" ${src.id === "sacramento" ? "disabled" : ""} /></div>
          </div>
          <label>Max CNPA pages</label>
          <input id="max_search_pages" type="number" min="1" max="20" value="${ppmEsc(p.max_search_pages ?? 10)}" ${src.id === "sacramento" ? "disabled" : ""} />
          ${src.id === "sacramento" ? `
          <h2 style="margin-top:16px;">Court portal login</h2>
          <p class="ppm-note">Email and password for the Sacramento Journal Technologies public portal. Jobs scrape the math CAPTCHA from the login HTML. Confidential and Not Viewable filings are never downloaded. Leave the password blank to keep the saved password.</p>
          <label>Portal email</label>
          <input id="sacramento_portal_user" type="email" autocomplete="username" value="${ppmEsc(p.sacramento_portal_user || "")}" />
          <label>Portal password</label>
          <input id="sacramento_portal_password" type="password" autocomplete="new-password" placeholder="${p.sacramento_portal_password_set ? "unchanged if blank" : ""}" />
          <p class="ppm-note">${p.sacramento_portal_password_set ? "A portal password is already saved." : "No portal password saved yet. Public PDFs will not download until this is set."}</p>
          ` : ""}
          <div class="ppm-actions">
            ${src.id === "placer" ? '<button id="save-source" type="button">Save Placer import</button>' : '<button id="save-source" type="button">Save Sacramento portal login</button>'}
            <button class="secondary" id="preview-source" type="button">Preview one extract</button>
            <button class="secondary" id="run-source" type="button">Run ${ppmEsc(label)} job</button>
          </div>
          <p class="ppm-note">Preview and Run use the same Follow Up Boss path as ${src.id === "placer" ? "today" : "Placer"}. They only process ${ppmEsc(src.name)}. Turn the county off to leave it out of the scheduled job.</p>
        </section>
        <section class="ppm-card" id="source-preview">
          <h2>Last live extract</h2>
          <p class="ppm-note">Run Preview one extract to see pulled values and the Follow Up Boss mapping for one case.</p>
        </section>
        ${ppmGoNoGoCard(ppmSourceGoNoGo(this._data, this._mapData, src.id), src.name)}
        <section class="ppm-card">
          <h2>Follow Up Boss mapping</h2>
          <p class="ppm-note">${(this._mapData.fub_custom_fields || []).length
            ? `Each ${ppmEsc(src.name)} field can map to a custom field that already exists in Follow Up Boss.`
            : (this._mapData.fub_custom_error || "Save a Follow Up Boss API key, then reload to load custom fields.")}</p>
          ${ppmExamplePersonBar(this._fubPerson && this._fubPerson.query)}
          <table>
            <thead><tr><th>Source field</th><th>From</th><th>FUB custom field</th><th>Example person</th></tr></thead>
            <tbody>
              ${ppmMappingRows(
                fields,
                custom,
                this._mapData.fub_custom_fields || [],
                this._fubPerson,
                this._mapData.fub_builtin_fields || [],
                (this._mapData.catalog && this._mapData.catalog.default_custom_fields) || {},
              )}
            </tbody>
          </table>
          <div class="ppm-actions"><button id="save-source-map" type="button">Save ${ppmEsc(src.name)} mapping</button></div>
        </section>
      `;
      const skip = this._qs("#skip_portal");
      if (skip) skip.value = String(!!p.skip_portal);
      const pdf = this._qs("#generate_pdf");
      if (pdf) pdf.value = String(p.generate_pdf !== false);
      const saveBtn = this._qs("#save-source");
      if (saveBtn) saveBtn.addEventListener("click", () => this._save());
      this._qs("#source_enabled").addEventListener("change", (ev) => this._toggleEnabled(src.id, ev.target.checked));
      this._qs("#preview-source").addEventListener("click", () => this._preview(src.id));
      this._qs("#run-source").addEventListener("click", () => this._run(src.id));
      const saveMap = this._qs("#save-source-map");
      if (saveMap) saveMap.addEventListener("click", () => this._saveSourceMap(src.id));
      this._bindExamplePerson();
      ppmBindMappingExamples(body, this._fubPerson);
      ppmRenderPreview(this._qs("#source-preview"), this._jobSt);
      const shot = this._qs(".fub-person-shot");
      if (shot && this._fubPerson) shot.innerHTML = ppmPersonSnapshot(this._fubPerson)
        + ppmCompareExtractToFub(ppmPreviewRecord(this._jobSt), this._fubPerson);
      return;
    }
    if (src.status !== "live") {
      const fields = (this._mapData.source_fields && this._mapData.source_fields[src.id])
        || [];
      const custom = ((this._mapData.mapping && this._mapData.mapping.source_mappings
        && this._mapData.mapping.source_mappings[src.id]
        && this._mapData.mapping.source_mappings[src.id].custom_fields) || {});
      const fubFields = this._mapData.fub_custom_fields || [];
      body.innerHTML = `
        <section class="ppm-card">
          <h2>${ppmEsc(src.name)}</h2>
          <p>${ppmEsc(src.description)}</p>
          <p class="ppm-note">Import is not live yet. You can still map this source’s future fields to Follow Up Boss custom fields.</p>
        </section>
        ${ppmGoNoGoCard(ppmSourceGoNoGo(this._data, this._mapData, src.id), src.name)}
        <section class="ppm-card">
          <h2>Follow Up Boss mapping</h2>
          <p class="ppm-note">${fubFields.length
            ? `Choose a FUB custom field for each ${ppmEsc(src.name)} column. Pull an example person to see real values.`
            : (this._mapData.fub_custom_error || "Save a Follow Up Boss API key, then reload to load custom fields.")}</p>
          ${ppmExamplePersonBar(this._fubPerson && this._fubPerson.query)}
          <table><thead><tr><th>Source field</th><th>From</th><th>FUB custom field</th><th>Example person</th></tr></thead>
          <tbody>${ppmMappingRows(fields, custom, fubFields, this._fubPerson, this._mapData.fub_builtin_fields || [], (this._catalog && this._catalog.default_custom_fields) || (this._mapData.catalog && this._mapData.catalog.default_custom_fields) || {})}</tbody></table>
          <div class="ppm-actions"><button id="save-source-map" type="button">Save ${ppmEsc(src.name)} mapping</button></div>
        </section>`;
      const saveBtn = this._qs("#save-source-map");
      if (saveBtn) saveBtn.addEventListener("click", () => this._saveSourceMap(src.id));
      this._bindExamplePerson();
      const shot = this._qs(".fub-person-shot");
      if (shot && this._fubPerson) shot.innerHTML = ppmPersonSnapshot(this._fubPerson);
      ppmBindMappingExamples(body, this._fubPerson);
      return;
    }
  }

  async _load() {
    try {
      const [data, job, mapping] = await Promise.all([
        this._hass.callApi("GET", "placer_probate_monitor/sources"),
        this._hass.callApi("GET", "placer_probate_monitor/job").catch(() => ({})),
        this._hass.callApi("GET", "placer_probate_monitor/fub_mapping").catch(() => ({})),
      ]);
      this._data = data;
      this._jobSt = job || {};
      this._mapData = mapping || {};
      this._renderList();
      this._renderBody();
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _save() {
    const src = this._source || "placer";
    const body = src === "sacramento"
      ? {
        source_id: "sacramento",
        sacramento_portal_user: (this._qs("#sacramento_portal_user") || {}).value || "",
        sacramento_portal_password: (this._qs("#sacramento_portal_password") || {}).value || "",
      }
      : {
        source_id: "placer",
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
      this._flash(src === "sacramento" ? "Sacramento portal login saved." : "Placer import settings saved.", true);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _toggleEnabled(sourceId, enabled) {
    try {
      this._data = await this._hass.callApi("POST", "placer_probate_monitor/sources", {
        source_id: sourceId,
        enabled,
      });
      this._renderList();
      this._renderBody();
      const name = sourceId === "sacramento" ? "Sacramento County" : "Placer County";
      this._flash(
        enabled
          ? `${name} is on. Scheduled jobs and Follow Up Boss import include this county.`
          : `${name} is off. The other county and Follow Up Boss settings are unchanged.`,
        true,
      );
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _run(sourceId) {
    const id = sourceId || "placer";
    const label = id === "sacramento" ? "Sacramento" : "Placer";
    this._flash(`Starting ${label} job…`, "wait");
    try {
      const st = await ppmRunJob(this._hass, "run", { source_id: id }, (live) => {
        this._flash(ppmJobLiveMessage(live) || `${label} job is running…`, "wait");
      });
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      this._flash(ok ? ppmJobDoneMessage(st) : (ppmText(st.last_error) || `${label} job failed. Check last_run.log.`), ok);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _preview(sourceId) {
    const id = sourceId || "placer";
    const label = id === "sacramento" ? "Sacramento" : "Placer";
    this._flash(`Preview started… pulling one live ${label} go-case (view only).`, "wait");
    try {
      const st = await ppmRunJob(this._hass, "preview", { source_id: id }, (live) => {
        this._flash(ppmJobLiveMessage(live) || "Preview is running…", "wait");
      });
      this._jobSt = st;
      ppmRenderPreview(this._qs("#source-preview"), st);
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      const rec = ppmPreviewRecord(st);
      this._flash(
        ok
          ? (rec
            ? `Preview loaded ${rec.case_number}. Review pulled values below.`
            : (st.fub_verify_note || "Preview finished. No go-case in this window."))
          : (ppmText(st.last_error) || "Preview failed."),
        ok,
      );
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _saveSourceMap(sourceId) {
    const mapping = this._mapData.mapping || {};
    const custom_fields = {};
    this.querySelectorAll("[data-custom]").forEach((el) => {
      const value = el.value.trim();
      if (value) custom_fields[el.dataset.custom] = value;
    });
    try {
      this._mapData = await this._hass.callApi("POST", "placer_probate_monitor/fub_mapping", {
        source_id: sourceId,
        system: mapping.system || "PlacerProbateMonitor",
        subject_address_type: mapping.subject_address_type || "subject property",
        court_search_url: mapping.court_search_url || "",
        skip_petitioner_contains: mapping.skip_petitioner_contains || [],
        send: mapping.send || {},
        custom_fields,
      });
      this._renderList();
      this._renderBody();
      this._flash("Follow Up Boss mapping saved.", true);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  _bindExamplePerson() {
    const btn = this._qs(".fub-person-load");
    if (!btn) return;
    btn.addEventListener("click", () => this._loadFubExample());
  }

  async _loadFubExample() {
    const input = this._qs(".fub-person-q");
    const q = ((input && input.value) || "").trim();
    if (!q) {
      this._flash("Enter a Follow Up Boss person id or name.", false);
      return;
    }
    this._flash("Loading example person from Follow Up Boss…", true);
    try {
      this._fubPerson = await ppmFetchFubPerson(this._hass, q);
      this._renderList();
      this._renderBody();
      this._flash(`Loaded example FUB person ${this._fubPerson.person_id}.`, true);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }
}

class PlacerProbateFubPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._catalog = { probate_fields: [], send_toggles: [], go_no_go: [], default_custom_fields: {} };
    this._fubFields = [];
    this._fubBuiltins = [];
    this._ready = false;
    this._tab = "connection";
    this._mapSource = "placer";
    this._mapData = {};
    this._fubPerson = null;
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
    el.className = "ppm-banner show " + ppmBannerKind(ok);
  }

  _renderShell() {
    this.innerHTML = `
      <style>${PPM_CSS}</style>
      <div class="ppm-wrap">
        <header>
          <h1>Follow Up Boss</h1>
          <p>CRM connection, one-case verification, and field mapping. County import screens are under Probate sources.</p>
          <div class="ppm-tabs">
            <button class="ghost active" type="button" data-tab="connection">Connection &amp; preview</button>
            <button class="ghost" type="button" data-tab="mapping">Field mapping</button>
          </div>
        </header>
        <main class="ppm-wide">
          <div id="flash" class="ppm-banner"></div>
          <div class="ppm-fub-layout">
            <div>
          <section class="ppm-card" id="tab-connection">
            <h2>Connection</h2>
            <label class="ppm-toggle"><input id="fub_enabled" type="checkbox" /><span>Enable Follow Up Boss export</span></label>
            <label>API URL</label>
            <input id="fub_api_url" />
            <label>API key (leave blank to keep the saved key)</label>
            <input id="fub_api_key" type="password" placeholder="unchanged if blank" />
            <p class="ppm-note" id="key-note"></p>
            <label>FUB system key (optional, for Files). Leave blank to keep the saved key</label>
            <input id="fub_system_key" type="password" placeholder="unchanged if blank" />
            <p class="ppm-note" id="system-key-note">Follow Up Boss Files requires a registered X-System-Key. Without it the DE-111 is posted as a Notes link instead.</p>
            <div class="ppm-row">
              <div><label>Lead source name</label><input id="fub_source" /></div>
              <div><label>Assign to</label><input id="fub_assigned_to" /></div>
            </div>
            <label>Person stage</label>
            <input id="fub_stage" placeholder="Must match a Follow Up Boss stage name (leave blank for FUB default)" />
            <label>Event type</label>
            <select id="fub_event_type"></select>
            <label class="ppm-toggle"><input id="fub_strict_property" type="checkbox" /><span>Require decedent residence before upload</span></label>
            <label class="ppm-toggle"><input id="fub_verify_only" type="checkbox" /><span>Verify only: update one person per run</span></label>
            <label class="ppm-toggle"><input id="fub_update_existing" type="checkbox" /><span>Update all existing Follow Up Boss people on this run</span></label>
            <p class="ppm-note">Turn Verify only off and turn Update all existing on, then Run Placer job. That PUTs every matched person (addresses, notes, DE-111) even if they were skipped as unchanged. Turn Update all existing back off after the catch-up so daily runs stay quiet.</p>
            <label class="ppm-toggle"><input id="fub_verify_existing" type="checkbox" /><span>Use existing Follow Up Boss person</span></label>
            <label>Existing person ID</label>
            <input id="fub_verify_person_id" inputmode="numeric" placeholder="e.g. 12345" />
            <div class="ppm-actions">
              <button id="save-fub" type="button">Save FUB connection</button>
              <button class="secondary" id="preview-one" type="button">Preview one record</button>
              <button class="secondary" id="verify-fub" type="button">Verify one FUB import</button>
            </div>
            <p class="ppm-note">Preview does not post. Check Use existing and enter a Follow Up Boss person ID to refresh that contact. Leave it unchecked to reuse the last test person, or create one if none exist.</p>
          </section>
          <section class="ppm-card" id="verify-record">
            <h2>Last verify record</h2>
            <p class="ppm-note">Run Verify one FUB import to show the go-case that was posted.</p>
          </section>
          <div id="tab-mapping" class="ppm-hide">
            <section class="ppm-card" id="go-no-go">
              <h2>Go / no-go data requirements</h2>
              <div id="go-no-go-body"></div>
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
              <p class="ppm-note">Dropdowns are live custom fields from Follow Up Boss. Pick a county source, then map each extract column. Built-in person fields (name, address) are not listed here.</p>
              <div class="ppm-tabs" id="map-sources"></div>
              <div class="ppm-actions" style="margin-top:12px;">
                <button class="secondary" id="load-fub" type="button">Reload FUB custom fields</button>
              </div>
              <p class="ppm-note" id="fub-fields-note"></p>
              <table><thead><tr><th>Source field</th><th>From</th><th>FUB custom field</th><th>Example person</th></tr></thead>
              <tbody id="matrix"></tbody></table>
              <div class="ppm-actions"><button id="save" type="button">Save mapping</button></div>
            </section>
          </div>
            </div>
            <aside class="ppm-card ppm-fub-side" id="live-client">
              <h2>Live FUB client</h2>
              <p class="ppm-note">Stays open while you map. Pull a real contact to see its values and which probate fields are associated.</p>
              <label>Person id or name</label>
              <input id="live-client-q" placeholder="e.g. 12345 or Jane Doe" />
              <div class="ppm-actions">
                <button class="secondary" id="load-live-client" type="button">Pull live client</button>
              </div>
              <div id="live-client-body"></div>
            </aside>
          </div>
        </main>
      </div>
    `;
    this.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => this._setTab(btn.dataset.tab));
    });
    this._qs("#save").addEventListener("click", () => this._saveMapping());
    this._qs("#load-fub").addEventListener("click", () => this._loadMapping(true));
    this._qs("#load-live-client").addEventListener("click", () => this._loadPerson());
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
    this._qs("#fub_system_key").value = "";
    this._qs("#key-note").textContent = data.fub_api_key_set
      ? "An API key is already saved."
      : "No API key saved yet.";
    this._qs("#system-key-note").textContent = data.fub_system_key_set
      ? "A FUB system key is already saved. Files uploads will use it."
      : "No FUB system key saved. Files API will 403; DE-111 goes to Notes as a download link.";
    this._qs("#fub_source").value = data.fub_source || "probate";
    this._qs("#fub_assigned_to").value = data.fub_assigned_to || "";
    this._qs("#fub_stage").value = data.fub_stage || "";
    const types = data.event_types || ["Seller Inquiry"];
    this._qs("#fub_event_type").innerHTML = types
      .map((item) => `<option value="${ppmEsc(item)}">${ppmEsc(item)}</option>`)
      .join("");
    this._qs("#fub_event_type").value = data.fub_event_type || "Seller Inquiry";
    this._qs("#fub_strict_property").checked = !!data.fub_strict_property;
    this._qs("#fub_verify_only").checked = data.fub_verify_only !== false;
    this._qs("#fub_update_existing").checked = !!data.fub_update_existing;
    this._qs("#fub_verify_existing").checked = !!data.fub_verify_existing;
    this._qs("#fub_verify_person_id").value = data.fub_verify_person_id || "";
  }

  _renderVerify(st) {
    this._jobSt = st || this._jobSt;
    this._lastRec = ppmPreviewRecord(st);
    ppmRenderPreview(this._qs("#verify-record"), st);
    this._renderLiveClient();
  }

  _applyMapping(data) {
    this._mapData = data || {};
    this._catalog = data.catalog || this._catalog;
    this._fubFields = data.fub_custom_fields || [];
    this._fubBuiltins = data.fub_builtin_fields || [];
    this._mapSource = data.source_id || this._mapSource || "placer";
    const mapping = data.mapping || {};
    const send = mapping.send || {};
    this._renderGoNoGo();
    const sources = data.data_sources || [];
    this._qs("#map-sources").innerHTML = sources.map((src) => {
      const active = src.id === this._mapSource ? "active" : "";
      const label = src.status === "live" ? "Live" : "Later";
      return `<button class="secondary ${active}" type="button" data-map-source="${ppmEsc(src.id)}">${ppmEsc(src.name)} <span class="ppm-pill ${src.status === "live" ? "live" : "wait"}">${label}</span></button>`;
    }).join("");
    this.querySelectorAll("[data-map-source]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._mapSource = btn.dataset.mapSource;
        this._renderGoNoGo();
        this._renderMatrix();
        this._renderLiveClient();
        this.querySelectorAll("[data-map-source]").forEach((el) => {
          el.classList.toggle("active", el.dataset.mapSource === this._mapSource);
        });
      });
    });
    const sourceName = (sources.find((item) => item.id === this._mapSource) || {}).name
      || this._catalog.data_source_name
      || "Placer County";
    this._qs("#path-line").textContent =
      "Mapping file: " + (data.path || "fub_mapping.yaml")
      + " · Source: " + sourceName
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
    this._renderMatrix();
    this._qs("#fub-fields-note").textContent = data.fub_custom_error
      ? data.fub_custom_error
      : (this._fubFields.length
        ? `Loaded ${this._fubFields.length} custom fields plus built-in person fields as dropdown options.`
        : "No custom fields came back from Follow Up Boss. Create them in FUB, then reload.");
    this._renderLiveClient();
  }

  _renderGoNoGo() {
    const el = this._qs("#go-no-go-body");
    if (!el) return;
    const data = this._mapData || {};
    const sources = data.data_sources || [];
    const sourceName = (sources.find((item) => item.id === this._mapSource) || {}).name
      || this._catalog.data_source_name
      || this._mapSource
      || "this source";
    const spec = ppmSourceGoNoGo(data, data, this._mapSource || "placer");
    el.innerHTML = ppmGoNoGoInner(spec, sourceName);
  }

  _renderMatrix() {
    const data = this._mapData || {};
    const fields = (data.source_fields && data.source_fields[this._mapSource])
      || this._catalog.probate_fields
      || [];
    const mapping = data.mapping || {};
    const custom = ((mapping.source_mappings
      && mapping.source_mappings[this._mapSource]
      && mapping.source_mappings[this._mapSource].custom_fields)
      || (this._mapSource === "placer" ? mapping.custom_fields : {})
      || {});
    this._qs("#matrix").innerHTML = ppmMappingRows(
      fields,
      custom,
      this._fubFields || [],
      this._fubPerson,
      this._fubBuiltins || [],
      this._catalog.default_custom_fields || {},
    );
    ppmBindMappingExamples(this._qs("#matrix"), this._fubPerson);
    this.querySelectorAll("#matrix select[data-custom]").forEach((el) => {
      el.addEventListener("change", () => this._renderLiveClient());
    });
  }

  _renderLiveClient() {
    const el = this._qs("#live-client-body");
    if (!el) return;
    const data = this._mapData || {};
    const fields = (data.source_fields && data.source_fields[this._mapSource])
      || this._catalog.probate_fields
      || [];
    const mapping = Object.assign({}, data.mapping || {});
    const custom = {};
    this.querySelectorAll("#matrix select[data-custom]").forEach((input) => {
      if (input.value.trim()) custom[input.dataset.custom] = input.value.trim();
    });
    if (Object.keys(custom).length) {
      mapping.source_mappings = Object.assign({}, mapping.source_mappings || {});
      mapping.source_mappings[this._mapSource || "placer"] = { custom_fields: custom };
    }
    const associations = ppmFieldAssociations(mapping, this._mapSource, fields);
    el.innerHTML = ppmLiveClientHtml(this._fubPerson, associations)
      + (this._fubPerson && this._lastRec ? ppmCompareExtractToFub(this._lastRec, this._fubPerson) : "");
  }

  _mappingPayload() {
    const send = {};
    this.querySelectorAll("[data-send]").forEach((el) => {
      send[el.dataset.send] = !!el.checked;
    });
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
      source_id: this._mapSource,
    };
  }

  async _loadAll(refreshMapping) {
    try {
      const [settings, mapping, job] = await Promise.all([
        this._hass.callApi("GET", "placer_probate_monitor/fub_settings"),
        this._hass.callApi("GET", "placer_probate_monitor/fub_mapping"),
        this._hass.callApi("GET", "placer_probate_monitor/job").catch(() => ({})),
      ]);
      this._applySettings(settings);
      this._applyMapping(mapping);
      this._renderVerify(job);
      if (refreshMapping) {
        this._flash(this._fubFields.length ? "Loaded FUB custom fields." : "No FUB fields loaded.", !!this._fubFields.length);
      }
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _loadMapping(refresh) {
    await this._loadAll(refresh);
  }

  async _loadPerson() {
    const input = this._qs("#live-client-q");
    const q = ((input && input.value) || "").trim();
    if (!q) {
      this._flash("Enter a Follow Up Boss person id or name.", false);
      return;
    }
    this._flash("Loading live FUB client…", true);
    try {
      this._fubPerson = await ppmFetchFubPerson(this._hass, q);
      this._renderMatrix();
      this._renderLiveClient();
      this._flash(`Loaded live FUB client ${this._fubPerson.person_id}.`, true);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _saveSettings() {
    const body = {
      fub_enabled: this._qs("#fub_enabled").checked,
      fub_api_url: this._qs("#fub_api_url").value.trim(),
      fub_api_key: this._qs("#fub_api_key").value,
      fub_system_key: this._qs("#fub_system_key").value,
      fub_source: this._qs("#fub_source").value.trim(),
      fub_assigned_to: this._qs("#fub_assigned_to").value.trim(),
      fub_stage: this._qs("#fub_stage").value.trim(),
      fub_event_type: this._qs("#fub_event_type").value,
      fub_strict_property: this._qs("#fub_strict_property").checked,
      fub_verify_only: this._qs("#fub_verify_only").checked,
      fub_update_existing: this._qs("#fub_update_existing").checked,
      fub_verify_existing: this._qs("#fub_verify_existing").checked,
      fub_verify_person_id: this._qs("#fub_verify_person_id").value.trim(),
    };
    try {
      const data = await this._hass.callApi("POST", "placer_probate_monitor/fub_settings", body);
      this._applySettings(data);
      this._flash("Follow Up Boss connection saved.", true);
    } catch (err) {
      this._flash(ppmText(err), false);
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
      this._flash(ppmText(err), false);
    }
  }

  async _verify() {
    const useExisting = this._qs("#fub_verify_existing").checked;
    const personId = (this._qs("#fub_verify_person_id").value || "").trim();
    if (useExisting && !/^\d+$/.test(personId)) {
      this._flash("Enter the Follow Up Boss person ID to update.", false);
      return;
    }
    this._flash(
      useExisting
        ? `Verify started… updating FUB person ${personId}.`
        : "Verify started… scraping Placer, then importing one go-case.",
      "wait",
    );
    try {
      const st = await ppmRunJob(this._hass, "verify", {
        fub_verify_existing: useExisting,
        fub_verify_person_id: personId,
        source_id: this._mapSource || "placer",
      }, (live) => {
        this._flash(ppmJobLiveMessage(live) || "Verify is running…", "wait");
      });
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      this._renderVerify(st);
      const rec = ppmPreviewRecord(st);
      this._flash(
        ok
          ? (rec
            ? (rec.posted
              ? (rec.updated
                ? `Verify updated ${rec.case_number} (FUB person ${rec.fub_person_id}).`
                : `Verify posted ${rec.case_number} as FUB person ${rec.fub_person_id}.`)
              : `Verify mapped ${rec.case_number} but Follow Up Boss did not accept it. Record is shown below.`)
            : (st.fub_verify_note || "Verify finished. No go-case was mapped."))
          : (ppmText(st.last_error) || "Verify failed."),
        ok && !(rec && rec.fub_error),
      );
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }

  async _preview() {
    this._flash("Preview started… retrieving one live go-case (view only).", "wait");
    try {
      const st = await ppmRunJob(this._hass, "preview", {
        source_id: this._mapSource || "placer",
      }, (live) => {
        this._flash(ppmJobLiveMessage(live) || "Preview is running…", "wait");
      });
      const ok = st.last_result !== "failed" && st.last_result !== "running";
      this._renderVerify(st);
      const rec = ppmPreviewRecord(st);
      this._flash(
        ok
          ? (rec
            ? `Preview loaded ${rec.case_number} (not posted).`
            : (st.fub_verify_note || "Preview finished. No go-case in this window."))
          : (ppmText(st.last_error) || "Preview failed."),
        ok,
      );
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }
}

customElements.define("placer-probate-sources-panel", PlacerProbateSourcesPanel);
customElements.define("placer-probate-fub-panel", PlacerProbateFubPanel);

class PlacerProbateListingsPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._ready = false;
    this._rows = [];
    this._query = "";
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
    el.className = "ppm-banner show " + ppmBannerKind(ok);
  }

  _renderShell() {
    this.innerHTML = `
      <style>${PPM_CSS}</style>
      <div class="ppm-wrap">
        <header>
          <h1>Probate listings</h1>
          <p>Collected county cases. Date is the newspaper notice date. Source is the county import. Placer decedent address is DE-111 item 3.a.(2) when marked, else 3c. Sacramento uses the published notice and court summary (no petition PDF).</p>
        </header>
        <main class="ppm-listings">
          <div id="flash" class="ppm-banner"></div>
          <section class="ppm-card">
            <div class="ppm-row">
              <div>
                <label>Filter</label>
                <input id="listing-q" placeholder="Case, petitioner, decedent, address" />
              </div>
              <div>
                <label>&nbsp;</label>
                <div class="ppm-actions" style="margin-top:0;">
                  <button type="button" id="listing-reload">Reload</button>
                </div>
              </div>
            </div>
            <p class="ppm-note" id="listing-count"></p>
            <div class="ppm-table-wrap" id="listing-table"></div>
          </section>
        </main>
      </div>
    `;
    this._qs("#listing-reload").addEventListener("click", () => this._load());
    this._qs("#listing-q").addEventListener("input", (ev) => {
      this._query = ev.target.value || "";
      this._renderTable();
    });
  }

  _filtered() {
    const q = this._query.trim().toLowerCase();
    if (!q) return this._rows;
    return this._rows.filter((row) => {
      const blob = [
        row.case_number, row.date, row.source, row.petitioner, row.decedent,
        row.decedent_address, row.petitioner_address, row.newspaper, row.filed,
      ].map((item) => String(item || "").toLowerCase()).join(" ");
      return blob.includes(q);
    });
  }

  _renderTable() {
    const rows = this._filtered();
    this._qs("#listing-count").textContent = rows.length
      ? `${rows.length} listing${rows.length === 1 ? "" : "s"}`
      : "No collected listings yet. Run a Placer import or Preview one extract.";
    if (!rows.length) {
      this._qs("#listing-table").innerHTML = "";
      return;
    }
    const body = rows.map((row) => {
      const caseCell = row.notice_url
        ? `<a href="${ppmEsc(row.notice_url)}" target="_blank" rel="noopener">${ppmEsc(row.case_number)}</a>`
        : ppmEsc(row.case_number);
      return `<tr>
        <td>${ppmEsc(row.date || row.filed || "—")}</td>
        <td>${ppmEsc(row.source || "Placer County")}</td>
        <td>${caseCell}</td>
        <td>${ppmEsc(row.petitioner || "—")}<div class="ppm-note">${ppmEsc(row.petitioner_address || "")}</div></td>
        <td>${ppmEsc(row.decedent || "—")}</td>
        <td>${ppmEsc(row.decedent_address || "—")}</td>
      </tr>`;
    }).join("");
    this._qs("#listing-table").innerHTML = `
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Source</th>
            <th>Case</th>
            <th>Petitioner</th>
            <th>Decedent</th>
            <th>Decedent address</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    `;
  }

  async _load() {
    this._flash("Loading collected listings…", true);
    try {
      const data = await this._hass.callApi("GET", "placer_probate_monitor/listings");
      this._rows = data.listings || [];
      this._renderTable();
      this._flash(`Loaded ${this._rows.length} collected listing${this._rows.length === 1 ? "" : "s"}.`, true);
    } catch (err) {
      this._flash(ppmText(err), false);
    }
  }
}

customElements.define("placer-probate-listings-panel", PlacerProbateListingsPanel);
