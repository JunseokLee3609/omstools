const state = {
  config: null,
  dashboard: null,
  dashboardRatio: null,
  dashboardRatioLoaded: false,
  projection: null,
  projectionResults: [],
  activeProjectionIndex: 0,
  comparisons: [],
  ratePlots: null,
  ratePlotSheetCache: null,
  ratePlotSheetRevision: 0,
  rateSnapshot: null,
  rateSnapshotProjection: null,
  rateSnapshotMergedRows: [],
  rateSnapshotView: "snapshot",
  l1PrescaleRows: [],
  l1PrescalePayload: null,
  availableSeeds: [],
  monitoringSeeds: [],
  monitoringPath: "",
  selectedAvailableSeeds: new Set(),
  selectedMonitoringSeeds: new Set(),
  refreshTimer: null,
  projectionSettingsSaveTimer: null,
  dashboardReferenceSaveTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const PROJECTION_SETTINGS_KEY = "oms_l1_projection_settings_v1";
const DASHBOARD_REFERENCE_SETTINGS_KEY = "oms_l1_dashboard_reference_settings_v1";
const RATE_PLOT_SHEETS = {
  "4x4": {
    pageWidth: 3600,
    pageHeight: 2550,
    margin: 64,
    headerHeight: 118,
    gapX: 26,
    gapY: 26,
    cols: 4,
    rows: 4,
  },
  "2x2": {
    pageWidth: 2600,
    pageHeight: 1900,
    margin: 70,
    headerHeight: 126,
    gapX: 42,
    gapY: 42,
    cols: 2,
    rows: 2,
  },
};

function valueOf(selector, fallback = "") {
  const node = $(selector);
  return node ? node.value : fallback;
}

function setValue(selector, value) {
  const node = $(selector);
  if (node) node.value = value;
}

function setChecked(selector, value) {
  const node = $(selector);
  if (node) node.checked = Boolean(value);
}

function bind(selector, eventName, handler) {
  const node = $(selector);
  if (!node) return null;
  node.addEventListener(eventName, handler);
  return node;
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  if (Math.abs(num) >= 10000) return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return num.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtLumi(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toExponential(3);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function csvValue(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
}

function filenameSlug(value) {
  return String(value || "plot")
    .replace(/^L1_/, "")
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 120) || "plot";
}

function downloadCsv(filename, rows, columns) {
  if (!rows || !rows.length) {
    toast("No projection rows to export yet.");
    return;
  }
  const header = columns.map((column) => csvValue(column.label)).join(",");
  const body = rows.map((row) => (
    columns.map((column) => csvValue(row[column.key])).join(",")
  ));
  const blob = new Blob([[header, ...body].join("\n") + "\n"], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadDataUrl(filename, dataUrl) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = dataUrl;
  });
}

function truncateCanvasText(ctx, text, maxWidth) {
  const clean = String(text || "Rate plot");
  if (ctx.measureText(clean).width <= maxWidth) return clean;
  let lo = 0;
  let hi = clean.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(`${clean.slice(0, mid)}...`).width <= maxWidth) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return `${clean.slice(0, lo)}...`;
}

function projectionCsvColumns() {
  return [
    { key: "bit", label: "L1 bit" },
    { key: "pathname", label: "L1 trigger name" },
    { key: "reference_rate", label: "Reference rate" },
    { key: "lumi_ratio", label: "Lumi ratio" },
    { key: "expected_rate", label: "Projection" },
    { key: "rate", label: "Measured" },
    { key: "ratio", label: "Ratio" },
    { key: "run", label: "Run" },
    { key: "lumisection", label: "LS" },
    { key: "model_status", label: "Status" },
  ];
}

function projectionFilename(kind) {
  const context = state.projection?.context || {};
  const current = context.current_run || "comparison";
  const reference = context.reference_run || "reference";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `oms_l1_projection_${kind}_ref${reference}_run${current}_${stamp}.csv`;
}

function fmtBytes(bytes) {
  const num = Number(bytes || 0);
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} kB`;
  return `${(num / 1024 / 1024).toFixed(1)} MB`;
}

function nowText() {
  return new Date().toLocaleTimeString();
}

function toast(message) {
  const node = $("#toast");
  if (!node) {
    console.error(message);
    return;
  }
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 4200);
}

function setBusy(isBusy, message = "Working...") {
  document.body.classList.toggle("busy", isBusy);
  const progress = $("#global-progress");
  if (progress) progress.setAttribute("aria-hidden", isBusy ? "false" : "true");
  const overlay = $("#busy-overlay");
  if (overlay) overlay.setAttribute("aria-hidden", isBusy ? "false" : "true");
  const busyTitle = $("#busy-title");
  if (busyTitle) busyTitle.textContent = message;
  const busySubtitle = $("#busy-subtitle");
  if (busySubtitle) busySubtitle.textContent = isBusy ? "OMS request is running. Please wait." : "";
  const title = $("#topbar-page-title");
  if (!title) return;
  if (isBusy) {
    title.dataset.previousText = title.textContent;
    title.textContent = message;
  } else if (title.dataset.previousText) {
    title.textContent = title.dataset.previousText;
    delete title.dataset.previousText;
  }
}

function setButtonBusy(button, isBusy, label, busyLabel) {
  if (!button) return;
  button.disabled = isBusy;
  button.classList.toggle("button-loading", isBusy);
  button.innerHTML = isBusy
    ? `<span class="button-spinner" aria-hidden="true"></span>${busyLabel}`
    : label;
}

function waitForPaint() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(resolve);
    });
  });
}

async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    const fullUrl = new URL(url, window.location.href).href;
    throw new Error(`Cannot reach API: ${fullUrl}. Check tunnel/server connection.`);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || payload.detail || `Request failed: ${response.status}`);
  }
  return payload;
}

function setPage(page) {
  $$(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === page);
  });
  $$(".page").forEach((section) => {
    section.classList.toggle("active", section.id === `page-${page}`);
  });
  const active = document.querySelector(`.nav-item[data-page="${page}"]`);
  $("#topbar-page-title").textContent = active ? active.dataset.title : "Dashboard";
}

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  window.localStorage.setItem("oms_l1_sidebar_collapsed", collapsed ? "1" : "0");
  const button = $("#sidebar-toggle");
  if (button) {
    button.title = collapsed ? "Expand menu" : "Collapse menu";
    button.setAttribute("aria-label", collapsed ? "Expand menu" : "Collapse menu");
    button.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }
  window.setTimeout(() => {
    window.dispatchEvent(new Event("resize"));
    if (window.Plotly) {
      ["deviation-chart", "dashboard-ratio-chart"].forEach((id) => {
        const chart = document.getElementById(id);
        if (chart) Plotly.Plots.resize(chart);
      });
    }
  }, 220);
}

function setupSidebarToggle() {
  const saved = window.localStorage.getItem("oms_l1_sidebar_collapsed") === "1";
  setSidebarCollapsed(saved);
  bind("#sidebar-toggle", "click", () => {
    setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"));
  });
}

function isAllSeedSelection(value) {
  const text = String(value || "").trim().toUpperCase();
  return !text || text === "ALL" || text === "*";
}

function updateSeedPresetState() {
  const value = $("#trigger-file")?.value || "";
  const monitoringPath = state.config?.default_trigger_file || "";
  const isAll = isAllSeedSelection(value);
  const isMonitoring = value.trim() === monitoringPath;
  $("#seed-all")?.classList.toggle("active", isAll);
  $("#seed-monitoring")?.classList.toggle("active", isMonitoring);
}

function setSeedSelection(value) {
  const input = $("#trigger-file");
  if (!input) return;
  input.value = value;
  updateSeedPresetState();
  refreshDashboard({ includeRates: false }).catch((error) => toast(error.message));
}

function setupSeedPresets() {
  updateSeedPresetState();
  bind("#seed-all", "click", () => setSeedSelection("ALL"));
  bind("#seed-monitoring", "click", () => {
    setSeedSelection(state.config?.default_trigger_file || "examples/MuonTriggers.txt");
  });
}

function setMonitoringSeeds(seeds, path = state.monitoringPath) {
  const unique = [];
  const seen = new Set();
  seeds.forEach((raw) => {
    const seed = String(raw || "").trim();
    if (!seed || seen.has(seed)) return;
    seen.add(seed);
    unique.push(seed);
  });
  state.monitoringSeeds = unique;
  state.monitoringPath = path || state.monitoringPath || state.config?.default_trigger_file || "";
  renderMonitoringSeeds();
  renderL1PrescaleTable();
}

function filterSeeds(seeds, selector) {
  const query = String($(selector)?.value || "").trim().toLowerCase();
  if (!query) return seeds;
  return seeds.filter((seed) => seed.toLowerCase().includes(query));
}

function selectableSeedRow(seed, side) {
  const selectedSet = side === "available" ? state.selectedAvailableSeeds : state.selectedMonitoringSeeds;
  const isSelected = selectedSet.has(seed);
  return `
    <button class="seed-row selectable-row ${isSelected ? "selected" : ""}" type="button" data-side="${side}" data-seed="${escapeHtml(seed)}">
      <span title="${escapeHtml(seed)}">${escapeHtml(seed)}</span>
    </button>
  `;
}

function availablePool() {
  const monitoring = new Set(state.monitoringSeeds);
  return state.availableSeeds.filter((seed) => !monitoring.has(seed));
}

function renderAvailableSeeds() {
  const seeds = filterSeeds(availablePool(), "#available-seed-filter");
  $("#available-seed-count").textContent = `${availablePool().length} seeds`;
  const list = $("#available-seed-list");
  if (!list) return;
  list.innerHTML = seeds.length
    ? seeds.map((seed) => selectableSeedRow(seed, "available")).join("")
    : `<div class="seed-empty">No available seeds.</div>`;
}

function renderMonitoringSeeds() {
  $("#monitoring-seed-path").textContent = state.monitoringPath || "No file loaded yet.";
  $("#monitoring-seed-count").textContent = `${state.monitoringSeeds.length} seeds`;
  state.selectedAvailableSeeds = new Set([...state.selectedAvailableSeeds].filter((seed) => availablePool().includes(seed)));
  state.selectedMonitoringSeeds = new Set([...state.selectedMonitoringSeeds].filter((seed) => state.monitoringSeeds.includes(seed)));
  renderAvailableSeeds();
  const list = $("#monitoring-seed-list");
  if (!list) return;
  const seeds = filterSeeds(state.monitoringSeeds, "#monitoring-seed-filter");
  list.innerHTML = seeds.length
    ? seeds.map((seed) => selectableSeedRow(seed, "monitoring")).join("")
    : `<div class="seed-empty">No monitoring seeds.</div>`;
}

function setAvailableSeeds(seeds) {
  state.availableSeeds = [...new Set((seeds || []).map((seed) => String(seed || "").trim()).filter(Boolean))].sort();
  renderAvailableSeeds();
}

async function loadMonitoringSeeds() {
  const payload = await fetchJson("/api/monitoring-seeds");
  setMonitoringSeeds(payload.seeds || [], payload.path);
}

async function loadAvailableSeeds() {
  const params = new URLSearchParams({
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
  });
  const payload = await fetchJson(`/api/l1-seeds?${params.toString()}`);
  setAvailableSeeds(payload.seeds || []);
}

async function saveMonitoringSeeds() {
  const payload = await fetchJson("/api/monitoring-seeds", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seeds: state.monitoringSeeds }),
  });
  setMonitoringSeeds(payload.seeds || [], payload.path);
  toast(`Saved ${payload.count} monitoring seeds.`);
  if (valueOf("#trigger-file").trim() === payload.path) {
    refreshDashboard({ includeRates: true }).catch((error) => toast(error.message));
  }
}

function addMonitoringSeed() {
  const input = $("#monitoring-new-seed");
  const seed = input?.value.trim();
  if (!seed) return;
  if (!state.availableSeeds.includes(seed)) {
    toast(`${seed} is not in available L1 seeds.`);
    return;
  }
  if (state.monitoringSeeds.includes(seed)) {
    toast(`${seed} is already in monitoring seeds.`);
    if (input) input.value = "";
    return;
  }
  setMonitoringSeeds([...state.monitoringSeeds, seed]);
  if (input) input.value = "";
}

function toggleSeedSelection(seed, side) {
  const selectedSet = side === "available" ? state.selectedAvailableSeeds : state.selectedMonitoringSeeds;
  if (selectedSet.has(seed)) {
    selectedSet.delete(seed);
  } else {
    selectedSet.add(seed);
  }
  if (side === "available") {
    renderAvailableSeeds();
  } else {
    renderMonitoringSeeds();
  }
}

function moveSelectedToMonitoring() {
  if (!state.selectedAvailableSeeds.size) return;
  setMonitoringSeeds([...state.monitoringSeeds, ...state.selectedAvailableSeeds]);
  state.selectedAvailableSeeds.clear();
}

function removeSelectedFromMonitoring() {
  if (!state.selectedMonitoringSeeds.size) return;
  const remove = state.selectedMonitoringSeeds;
  setMonitoringSeeds(state.monitoringSeeds.filter((seed) => !remove.has(seed)));
  state.selectedMonitoringSeeds.clear();
}

function setupMonitoringSeeds() {
  bind("#monitoring-reload", "click", () => {
    Promise.all([
      loadAvailableSeeds(),
      loadMonitoringSeeds(),
    ]).catch((error) => toast(error.message));
  });
  bind("#monitoring-save", "click", () => saveMonitoringSeeds().catch((error) => toast(error.message)));
  bind("#monitoring-add", "click", addMonitoringSeed);
  bind("#monitoring-use", "click", () => setSeedSelection(state.monitoringPath || state.config?.default_trigger_file || "examples/MuonTriggers.txt"));
  bind("#move-to-monitoring", "click", moveSelectedToMonitoring);
  bind("#remove-from-monitoring", "click", removeSelectedFromMonitoring);
  bind("#available-seed-filter", "input", renderAvailableSeeds);
  bind("#monitoring-seed-filter", "input", renderMonitoringSeeds);
  bind("#monitoring-new-seed", "keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addMonitoringSeed();
    }
  });
  ["#available-seed-list", "#monitoring-seed-list"].forEach((selector) => {
    const list = $(selector);
    if (!list) return;
    list.addEventListener("click", (event) => {
      const row = event.target.closest(".selectable-row");
      if (!row) return;
      toggleSeedSelection(row.dataset.seed, row.dataset.side);
    });
  });
}

function metric(label, value, hint = "", icon = "fa-chart-line", tone = "blue") {
  const safeValue = value === null || value === undefined || value === "" ? "-" : value;
  return `
    <article class="metric-card ${tone}">
      <div class="metric-icon"><i class="fa-solid ${icon}"></i></div>
      <div class="metric-data">
        <div class="value" title="${safeValue}">${safeValue}</div>
        <div class="label">${label}</div>
        <div class="hint" title="${hint}">${hint}</div>
      </div>
    </article>
  `;
}

function renderMetrics(run) {
  $("#run-metrics").innerHTML = [
    metric("Run", run.run_number || "-", "GLOBAL-RUN", "fa-hashtag", "blue"),
    metric("Fill", run.fill_number || "-", "OMS fill", "fa-circle-nodes", "green"),
    metric("Last LS", run.last_lumisection_number || "-", "latest lumisection", "fa-clock", "purple"),
    metric("L1 rate", fmt(run.l1_rate), "Hz", "fa-gauge-high", "blue"),
    metric("Bunches", run.bunches_colliding || "-", "colliding", "fa-grip", "gold"),
    metric("Stable beam", run.stable_beam ? "Yes" : "No", run.sequence || "", "fa-signal", run.stable_beam ? "green" : "red"),
    metric("Delivered lumi", fmt(run.delivered_lumi), "", "fa-sun", "gold"),
    metric("Recorded lumi", fmt(run.recorded_lumi), "", "fa-database", "purple"),
    metric("HLT throughput", fmt(run.hlt_physics_throughput), "GB/s", "fa-server", "blue"),
    metric("Era", run.era || "-", run.hlt_key || "", "fa-tag", "green"),
  ].join("");
}

function rateClass(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "";
  if (num > 0) return "positive";
  if (num < 0) return "negative";
  return "";
}

function ratioClass(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "";
  return num >= 0.7 && num <= 2.0 ? "ratio-ok" : "ratio-alert";
}

function lsWindowText(row) {
  const minLs = row.lumisection_min;
  const maxLs = row.lumisection_max ?? row.lumisection;
  if (minLs !== null && minLs !== undefined && maxLs !== null && maxLs !== undefined) {
    return Number(minLs) === Number(maxLs) ? String(maxLs) : `${minLs}-${maxLs}`;
  }
  return row.lumisection || "-";
}

function renderLatestRates(rows) {
  const body = $("#latest-rates");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6">No selected L1 rates found.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td class="seed" title="${row.pathname}">${row.pathname}</td>
      <td class="num">${lsWindowText(row)}</td>
      <td class="num">${fmt(row.n_points, 0)}</td>
      <td class="num">${fmt(row.rate)}</td>
      <td class="num">${fmtLumi(row.init_lumi)}</td>
      <td>${row.beams_stable ? "stable" : "not stable"}</td>
    </tr>
  `).join("");
}

function seedSelectionSummary(data) {
  if (data?.all_triggers) return "All L1 seeds";
  const count = Number(data?.trigger_count || 0);
  const triggerFile = String(data?.trigger_file || "");
  const defaultFile = String(state.config?.default_trigger_file || "");
  const source = triggerFile === defaultFile
    ? "Monitoring seeds"
    : (triggerFile.split(/[\\/]/).pop() || "L1 seeds");
  return count > 0 ? `${count} ${source}` : source;
}

function parseRunList(value) {
  return String(value || "")
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item) && item > 0);
}

function plotLayout(yTitle) {
  return {
    margin: { l: 58, r: 22, t: 18, b: 48 },
    paper_bgcolor: "#111720",
    plot_bgcolor: "#111720",
    font: { color: "#dce6f2", family: "Inter, system-ui, sans-serif" },
    hovermode: "x unified",
    hoverlabel: {
      bgcolor: "#0d1117",
      bordercolor: "#58a6ff",
      font: { color: "#f0f6fc" },
    },
    legend: { orientation: "h", y: 1.12, x: 0, font: { color: "#dce6f2" } },
    xaxis: {
      title: { text: "Lumisection", font: { color: "#dce6f2" } },
      color: "#dce6f2",
      gridcolor: "#263241",
      linecolor: "#303946",
      zeroline: false,
    },
    yaxis: {
      title: { text: yTitle, font: { color: "#dce6f2" } },
      color: "#dce6f2",
      gridcolor: "#263241",
      linecolor: "#303946",
      zeroline: false,
    },
  };
}

function ratioAxisRange(values) {
  const finite = (values || [])
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  let min = 0.5;
  let max = 2.0;
  if (finite.length) {
    min = Math.min(min, ...finite);
    max = Math.max(max, ...finite);
  }
  if (max <= 2.0 && min >= 0.5) {
    return [0.5, 2];
  }
  const padding = Math.max((max - min) * 0.08, 0.05);
  return [Math.min(0, min - padding), max + padding];
}

function applyRatioAxisRange(layout, values) {
  layout.yaxis = {
    ...(layout.yaxis || {}),
    range: ratioAxisRange(values),
    autorange: false,
  };
}

function applyLumisectionDataRange(layout, values = []) {
  const finite = (values || [])
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const minValue = finite.length ? Math.min(...finite) : null;
  const maxValue = finite.length ? Math.max(...finite) : null;
  let range = null;
  if (minValue !== null && maxValue !== null) {
    const span = Math.max(1, maxValue - minValue);
    const pad = Math.max(0.5, span * 0.02);
    range = [minValue - pad, maxValue + pad];
  }
  layout.xaxis = {
    ...(layout.xaxis || {}),
    title: { text: "Lumisection", font: { color: "#dce6f2" } },
    ...(range ? { range } : {}),
  };
}

function suspiciousRatioItems(rows) {
  const bySeed = new Map();
  (rows || []).forEach((row) => {
    const ratio = finiteNumber(row.ratio);
    const ls = finiteNumber(row.lumisection);
    if (ratio === null || ls === null) return;
    if (ratio >= 0.7 && ratio <= 2.0) return;
    const seed = String(row.pathname || "Unknown");
    if (!bySeed.has(seed)) bySeed.set(seed, []);
    bySeed.get(seed).push({ ls, ratio, severity: Math.abs(ratio - 1) });
  });
  return Array.from(bySeed.entries())
    .map(([seed, points]) => {
      points.sort((a, b) => a.ls - b.ls);
      return {
        seed,
        points,
        maxSeverity: Math.max(...points.map((point) => point.severity)),
      };
    })
    .sort((a, b) => b.maxSeverity - a.maxSeverity || b.points.length - a.points.length);
}

function renderSuspiciousReport(selector, rows) {
  const node = $(selector);
  if (!node) return;
  const items = suspiciousRatioItems(rows);
  if (!items.length) {
    node.innerHTML = `
      <div class="suspicious-report-head">
        <strong>Suspicious LS</strong>
        <span>No LS outside ratio 0.7-2.0.</span>
      </div>
    `;
    return;
  }

  const total = items.reduce((sum, item) => sum + item.points.length, 0);
  const shown = items.map((item) => {
    const points = item.points.slice(0, 6)
      .map((point) => `(${point.ls}: ${fmt(point.ratio, 3)})`)
      .join(", ");
    const more = item.points.length > 6 ? `, +${item.points.length - 6} more` : "";
    return `<div><span>${escapeHtml(item.seed)}</span>: ${escapeHtml(points + more)}</div>`;
  }).join("");
  node.innerHTML = `
    <div class="suspicious-report-head">
      <strong>Suspicious LS</strong>
      <span>${items.length} triggers, ${total} points outside ratio 0.7-2.0</span>
    </div>
    <div class="suspicious-list">${shown}</div>
  `;
}

function dashboardReferencePayload() {
  return {
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    reference_run: Number(valueOf("#dashboard-reference-run", "387892")),
    reference_lumi_mode: "range",
    reference_ls_min: Number(valueOf("#dashboard-reference-ls-min", "100")),
    reference_ls_max: Number(valueOf("#dashboard-reference-ls-max", "200")),
    reference_single_ls: Number(valueOf("#dashboard-reference-ls-min", "100")),
    reference_hardcoded_lumi: 0,
    max_lumisections: Number(valueOf("#dashboard-ratio-max-ls", "120") || 120),
  };
}

function dashboardReferenceState() {
  return {
    reference_run: valueOf("#dashboard-reference-run", "387892"),
    reference_ls_min: valueOf("#dashboard-reference-ls-min", "100"),
    reference_ls_max: valueOf("#dashboard-reference-ls-max", "200"),
    max_lumisections: valueOf("#dashboard-ratio-max-ls", "120"),
    auto_refresh: Boolean($("#dashboard-ratio-auto")?.checked),
  };
}

function applyDashboardReferenceSettings(saved) {
  if (!hasProjectionSettings(saved)) return false;
  const fields = {
    "#dashboard-reference-run": saved.reference_run,
    "#dashboard-reference-ls-min": saved.reference_ls_min,
    "#dashboard-reference-ls-max": saved.reference_ls_max,
    "#dashboard-ratio-max-ls": saved.max_lumisections,
  };
  Object.entries(fields).forEach(([selector, value]) => {
    if (value !== undefined && value !== null) setValue(selector, value);
  });
  if (saved.auto_refresh !== undefined) {
    setChecked("#dashboard-ratio-auto", saved.auto_refresh);
  }
  return true;
}

function localDashboardReferenceSettings() {
  try {
    return JSON.parse(window.localStorage.getItem(DASHBOARD_REFERENCE_SETTINGS_KEY) || "null");
  } catch (_error) {
    return null;
  }
}

function saveDashboardReferenceSettingsToServer(settings) {
  return fetchJson("/api/dashboard-reference-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings }),
  });
}

function scheduleDashboardReferenceSave(settings) {
  window.clearTimeout(state.dashboardReferenceSaveTimer);
  state.dashboardReferenceSaveTimer = window.setTimeout(() => {
    saveDashboardReferenceSettingsToServer(settings).catch((error) => {
      console.warn("Failed to save dashboard reference settings:", error.message);
    });
  }, 350);
}

function saveDashboardReferenceSettings() {
  const settings = dashboardReferenceState();
  try {
    window.localStorage.setItem(DASHBOARD_REFERENCE_SETTINGS_KEY, JSON.stringify(settings));
  } catch (_error) {
    // Ignore storage failures; server save is the source of truth.
  }
  scheduleDashboardReferenceSave(settings);
}

async function restoreDashboardReferenceSettings() {
  let serverSettings = null;
  try {
    const payload = await fetchJson("/api/dashboard-reference-settings");
    serverSettings = payload.settings || null;
  } catch (error) {
    console.warn("Failed to load dashboard reference settings:", error.message);
  }
  if (applyDashboardReferenceSettings(serverSettings)) {
    try {
      window.localStorage.setItem(DASHBOARD_REFERENCE_SETTINGS_KEY, JSON.stringify(serverSettings));
    } catch (_error) {
      // Ignore storage failures.
    }
    return;
  }
  const localSettings = localDashboardReferenceSettings();
  if (applyDashboardReferenceSettings(localSettings)) {
    scheduleDashboardReferenceSave(dashboardReferenceState());
  }
}

function dashboardRatioSummary(context) {
  if (!context) return "Uses the saved Bunch Projection reference run and monitoring seeds.";
  const refLs = `${context.reference_ls_min ?? "-"}-${context.reference_ls_max ?? "-"}`;
  const curLs = context.current_ls_min && context.current_ls_max
    ? `${context.current_ls_min}-${context.current_ls_max}`
    : "-";
  return [
    `Reference ${context.reference_run} LS ${refLs}`,
    `current ${context.current_run} recorded LS ${curLs}`,
    `${context.trigger_count || 0} monitoring seeds`,
    `avg lumi ${fmtLumi(context.current_inst_lumi_avg)}`,
  ].join(" · ");
}

function renderDashboardRatioPlot(data) {
  const chart = document.getElementById("dashboard-ratio-chart");
  if (!chart || !window.Plotly) return;
  const rows = data?.rows || [];
  const context = data?.context || {};
  const summary = $("#dashboard-ratio-summary");
  if (summary) summary.textContent = dashboardRatioSummary(context);

  const grouped = new Map();
  const yValues = [];
  const xValues = [];
  rows.forEach((row) => {
    const ls = finiteNumber(row.lumisection);
    const ratio = finiteNumber(row.ratio);
    if (ls === null || ratio === null) return;
    yValues.push(ratio);
    xValues.push(ls);
    if (!grouped.has(row.pathname)) grouped.set(row.pathname, []);
    grouped.get(row.pathname).push({ ls, ratio });
  });

  const traces = Array.from(grouped.entries()).map(([name, points]) => {
    points.sort((a, b) => a.ls - b.ls);
    return {
      type: "scatter",
      mode: points.length > 1 ? "lines+markers" : "markers",
      name,
      x: points.map((point) => point.ls),
      y: points.map((point) => point.ratio),
      marker: { size: 7 },
      line: { width: 2 },
      hovertemplate: `LS %{x}<br>ratio %{y:.3f}<extra>%{fullData.name}</extra>`,
    };
  });

  const layout = plotLayout("Ratio");
  applyRatioAxisRange(layout, yValues);
  applyLumisectionDataRange(layout, xValues);
  layout.height = 360;
  layout.margin = { l: 58, r: 20, t: 12, b: 50 };
  layout.shapes = [{
    type: "line",
    xref: "paper",
    x0: 0,
    x1: 1,
    yref: "y",
    y0: 1,
    y1: 1,
    line: { color: "#8b949e", width: 1, dash: "dash" },
  }];
  if (!traces.length) {
    layout.annotations = [{
      text: "No stable current LS ratio points yet.",
      xref: "paper",
      yref: "paper",
      x: 0.5,
      y: 0.5,
      showarrow: false,
      font: { color: "#9aa4b2", size: 14 },
    }];
  }
  Plotly.react(chart, traces, layout, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  });
  renderSuspiciousReport("#dashboard-suspicious-report", rows);
}

async function loadDashboardRatioPlot(options = {}) {
  const quiet = Boolean(options.quiet);
  const button = $("#load-dashboard-ratio");
  if (!quiet) {
    setBusy(true, "Loading dashboard plot...");
    setButtonBusy(button, true, "Load plot", "Loading...");
    await waitForPaint();
  }
  try {
    const payload = await fetchJson("/api/dashboard/reference-ratio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dashboardReferencePayload()),
    });
    state.dashboardRatio = payload;
    state.dashboardRatioLoaded = true;
    renderDashboardRatioPlot(payload);
  } finally {
    if (!quiet) {
      setButtonBusy(button, false, "Load plot", "Loading...");
      setBusy(false);
    }
  }
}

async function refreshDashboard(options = {}) {
  await loadDashboard(options);
  if (state.dashboardRatioLoaded && $("#dashboard-ratio-auto")?.checked) {
    await loadDashboardRatioPlot({ quiet: true });
  }
}

async function loadDashboard(options = {}) {
  const includeRates = options.includeRates === true;
  const params = new URLSearchParams({
    trigger_file: valueOf("#trigger-file", "ALL"),
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    window: valueOf("#ls-window", "20") || "20",
    include_rates: includeRates ? "1" : "0",
  });
  const data = await fetchJson(`/api/dashboard?${params.toString()}`);
  state.dashboard = data;
  renderMetrics(data.run);
  renderLatestRates(data.latest || []);
  const triggerSummary = $("#trigger-summary");
  if (triggerSummary) triggerSummary.textContent = seedSelectionSummary(data);
  $("#last-updated").textContent = `updated ${nowText()}`;
  const liveBadge = $("#live-badge");
  liveBadge.textContent = data.is_live ? "LIVE" : "CLOSED";
  liveBadge.className = `badge ${data.is_live ? "live" : "closed"}`;
  const comparisonRun = $("#comparison-run");
  if (comparisonRun && !comparisonRun.value && data.run.run_number) {
    comparisonRun.value = String(data.run.run_number);
    saveProjectionSettings();
  }
  const l1TableRun = $("#l1-table-run");
  if (l1TableRun && !l1TableRun.value && data.run.run_number) {
    l1TableRun.placeholder = String(data.run.run_number);
  }
  const snapshotRun = $("#rate-snapshot-run");
  if (snapshotRun && !snapshotRun.value && data.run.run_number) {
    snapshotRun.placeholder = String(data.run.run_number);
  }
  const lastLs = Number(data.run.last_lumisection_number || 0);
  if (lastLs > 0) {
    if (!valueOf("#rate-snapshot-ls-max") || valueOf("#rate-snapshot-ls-max") === "20") {
      setValue("#rate-snapshot-ls-max", lastLs);
    }
    if (!valueOf("#rate-snapshot-single-ls") || valueOf("#rate-snapshot-single-ls") === "1") {
      setValue("#rate-snapshot-single-ls", lastLs);
    }
    if (!valueOf("#rate-snapshot-ls-min") || valueOf("#rate-snapshot-ls-min") === "1") {
      const windowSize = Math.max(1, Number(valueOf("#ls-window", "20") || 20));
      setValue("#rate-snapshot-ls-min", Math.max(1, lastLs - windowSize + 1));
    }
  }
  if (lastLs > 0) {
    if (!valueOf("#current-ls-max") || valueOf("#current-ls-max") === "20") {
      setValue("#current-ls-max", lastLs);
    }
    if (!valueOf("#current-single-ls") || valueOf("#current-single-ls") === "1") {
      setValue("#current-single-ls", lastLs);
    }
    if (!valueOf("#current-ls-min") || valueOf("#current-ls-min") === "1") {
      const windowSize = Math.max(1, Number(valueOf("#current-ls-window", "20") || 20));
      setValue("#current-ls-min", Math.max(1, lastLs - windowSize + 1));
    }
  }
}

function comparisonFromForm() {
  return {
    id: `cmp-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    run: valueOf("#comparison-run").trim() ? Number(valueOf("#comparison-run")) : null,
    lumi_mode: valueOf("#current-lumi-mode", "latest_window"),
    ls_window: Number(valueOf("#current-ls-window", "20") || 20),
    ls_min: Number(valueOf("#current-ls-min", "1") || 1),
    ls_max: Number(valueOf("#current-ls-max", "1") || 1),
    single_ls: Number(valueOf("#current-single-ls", "1") || 1),
    hardcoded_lumi: Number(valueOf("#current-hardcoded-lumi", "0") || 0),
    include_unstable: Boolean($("#comparison-include-unstable")?.checked),
  };
}

function projectionFormState() {
  return {
    trigger_file: valueOf("#trigger-file", "ALL"),
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    reference_run: valueOf("#reference-run"),
    reference_lumi_mode: valueOf("#reference-lumi-mode", "range"),
    reference_ls_min: valueOf("#reference-ls-min"),
    reference_ls_max: valueOf("#reference-ls-max"),
    reference_single_ls: valueOf("#reference-single-ls"),
    reference_hardcoded_lumi: valueOf("#reference-hardcoded-lumi"),
    comparison_run: valueOf("#comparison-run"),
    current_lumi_mode: valueOf("#current-lumi-mode", "latest_window"),
    current_ls_window: valueOf("#current-ls-window"),
    current_ls_min: valueOf("#current-ls-min"),
    current_ls_max: valueOf("#current-ls-max"),
    current_single_ls: valueOf("#current-single-ls"),
    current_hardcoded_lumi: valueOf("#current-hardcoded-lumi"),
    include_unstable: Boolean($("#comparison-include-unstable")?.checked),
    comparisons: state.comparisons,
  };
}

function localProjectionSettings() {
  try {
    return JSON.parse(window.localStorage.getItem(PROJECTION_SETTINGS_KEY) || "null");
  } catch (_error) {
    return null;
  }
}

function hasProjectionSettings(settings) {
  return settings && typeof settings === "object" && Object.keys(settings).length > 0;
}

function applyProjectionSettings(saved) {
  if (!hasProjectionSettings(saved)) return false;
  const fields = {
    "#trigger-file": saved.trigger_file,
    "#rate-field": saved.rate_field,
    "#reference-run": saved.reference_run,
    "#reference-lumi-mode": saved.reference_lumi_mode,
    "#reference-ls-min": saved.reference_ls_min,
    "#reference-ls-max": saved.reference_ls_max,
    "#reference-single-ls": saved.reference_single_ls,
    "#reference-hardcoded-lumi": saved.reference_hardcoded_lumi,
    "#comparison-run": saved.comparison_run,
    "#current-lumi-mode": saved.current_lumi_mode,
    "#current-ls-window": saved.current_ls_window,
    "#current-ls-min": saved.current_ls_min,
    "#current-ls-max": saved.current_ls_max,
    "#current-single-ls": saved.current_single_ls,
    "#current-hardcoded-lumi": saved.current_hardcoded_lumi,
  };
  Object.entries(fields).forEach(([selector, value]) => {
    if (value !== undefined && value !== null) setValue(selector, value);
  });
  if (saved.include_unstable !== undefined) {
    setChecked("#comparison-include-unstable", saved.include_unstable);
  }
  if (Array.isArray(saved.comparisons)) {
    state.comparisons = saved.comparisons.filter((item) => item && typeof item === "object");
  }
  return true;
}

function saveProjectionSettingsToServer(settings) {
  return fetchJson("/api/projection-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings }),
  });
}

function scheduleProjectionSettingsSave(settings) {
  window.clearTimeout(state.projectionSettingsSaveTimer);
  state.projectionSettingsSaveTimer = window.setTimeout(() => {
    saveProjectionSettingsToServer(settings).catch((error) => {
      console.warn("Failed to save projection settings:", error.message);
    });
  }, 350);
}

function saveProjectionSettings() {
  const settings = projectionFormState();
  try {
    window.localStorage.setItem(PROJECTION_SETTINGS_KEY, JSON.stringify(settings));
  } catch (_error) {
    // Ignore storage failures; the form still works normally.
  }
  scheduleProjectionSettingsSave(settings);
}

async function restoreProjectionSettings() {
  let serverSettings = null;
  try {
    const payload = await fetchJson("/api/projection-settings");
    serverSettings = payload.settings || null;
  } catch (error) {
    console.warn("Failed to load server projection settings:", error.message);
  }
  if (applyProjectionSettings(serverSettings)) {
    try {
      window.localStorage.setItem(PROJECTION_SETTINGS_KEY, JSON.stringify(serverSettings));
    } catch (_error) {
      // Ignore storage failures; server settings already loaded.
    }
    return;
  }

  const localSettings = localProjectionSettings();
  if (applyProjectionSettings(localSettings)) {
    scheduleProjectionSettingsSave(projectionFormState());
  }
}

function comparisonLabel(comparison) {
  const run = comparison.run || "auto";
  const mode = comparison.lumi_mode || "latest_window";
  let range = "";
  if (mode === "latest_window") range = `last ${comparison.ls_window} LS from stable`;
  if (mode === "range") range = `LS ${comparison.ls_min}-${comparison.ls_max}`;
  if (mode === "single") range = `LS ${comparison.single_ls}`;
  if (mode === "hardcoded") range = `hardcoded lumi ${comparison.hardcoded_lumi}`;
  return `${run} · ${range}${comparison.include_unstable ? " · stable+unstable" : " · stable only"}`;
}

function resolvedComparisonFromContext(comparison, context) {
  if (!context) return comparison;
  const resolved = { ...comparison };
  if (context.current_run) resolved.run = Number(context.current_run);
  if (context.current_lumi_mode) resolved.lumi_mode = context.current_lumi_mode;
  if (context.current_ls_min !== undefined && context.current_ls_min !== null) {
    resolved.ls_min = Number(context.current_ls_min);
  }
  if (context.current_ls_max !== undefined && context.current_ls_max !== null) {
    resolved.ls_max = Number(context.current_ls_max);
  }
  if (resolved.lumi_mode === "latest_window" && Number.isFinite(resolved.ls_min) && Number.isFinite(resolved.ls_max)) {
    resolved.lumi_mode = "range";
  }
  if (context.stable_only !== undefined) {
    resolved.include_unstable = !context.stable_only;
  }
  return resolved;
}

function renderComparisonList() {
  const node = $("#comparison-list");
  if (!node) return;
  if (!state.comparisons.length) {
    node.innerHTML = `<span class="field-hint">No comparison added yet. Current form will be used once if you run projection.</span>`;
    return;
  }
  node.innerHTML = state.comparisons.map((comparison, index) => `
    <span class="comparison-pill" title="${escapeHtml(comparisonLabel(comparison))}">
      ${escapeHtml(comparisonLabel(comparison))}
      <button type="button" data-remove-comparison="${index}" title="Remove">x</button>
    </span>
  `).join("");
}

function projectionPayload(comparison = null) {
  const activeComparison = comparison || comparisonFromForm();
  return {
    trigger_file: valueOf("#trigger-file", "ALL"),
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    reference_run: Number(valueOf("#reference-run")),
    reference_lumi_mode: valueOf("#reference-lumi-mode", "range"),
    reference_ls_min: Number(valueOf("#reference-ls-min", "1")),
    reference_ls_max: Number(valueOf("#reference-ls-max", "1")),
    reference_single_ls: Number(valueOf("#reference-single-ls", "1")),
    reference_hardcoded_lumi: Number(valueOf("#reference-hardcoded-lumi", "0") || 0),
    current_run: activeComparison.run,
    current_runs: activeComparison.run ? [activeComparison.run] : [],
    current_lumi_mode: activeComparison.lumi_mode,
    current_ls_window: activeComparison.ls_window,
    current_ls_min: activeComparison.ls_min,
    current_ls_max: activeComparison.ls_max,
    current_single_ls: activeComparison.single_ls,
    current_hardcoded_lumi: activeComparison.hardcoded_lumi,
    projection_plot_ls_limit: state.config?.default_projection_plot_ls_limit || 120,
    stable_only: !activeComparison.include_unstable,
  };
}

function updateLumiModeControls(group) {
  const mode = $(`#${group}-lumi-mode`)?.value;
  $$(`[data-mode-for="${group}"]`).forEach((node) => {
    const modes = String(node.dataset.modes || "").split(/\s+/);
    node.hidden = !modes.includes(mode);
  });
}

function setupProjectionControls() {
  ["reference", "current"].forEach((group) => {
    updateLumiModeControls(group);
    bind(`#${group}-lumi-mode`, "change", () => {
      updateLumiModeControls(group);
      saveProjectionSettings();
    });
  });
  [
    "#reference-run",
    "#reference-ls-min",
    "#reference-ls-max",
    "#reference-single-ls",
    "#reference-hardcoded-lumi",
    "#comparison-run",
    "#current-ls-window",
    "#current-ls-min",
    "#current-ls-max",
    "#current-single-ls",
    "#current-hardcoded-lumi",
    "#comparison-include-unstable",
  ].forEach((selector) => {
    bind(selector, "input", saveProjectionSettings);
    bind(selector, "change", saveProjectionSettings);
  });
  bind("#add-comparison", "click", () => {
    const comparison = comparisonFromForm();
    state.comparisons.push(comparison);
    renderComparisonList();
    saveProjectionSettings();
    toast(`Added comparison: ${comparisonLabel(comparison)}`);
  });
  const comparisonList = $("#comparison-list");
  if (comparisonList) {
    comparisonList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-comparison]");
      if (!button) return;
      const index = Number(button.dataset.removeComparison);
      if (!Number.isInteger(index)) return;
      state.comparisons.splice(index, 1);
      renderComparisonList();
      saveProjectionSettings();
    });
  }
  const resultTabs = $("#comparison-result-tabs");
  if (resultTabs) {
    resultTabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-projection-index]");
      if (!button) return;
      showProjectionResult(Number(button.dataset.projectionIndex));
    });
  }
  renderComparisonList();
}

function renderContext(context) {
  const node = $("#projection-context");
  if (!node) return;
  if (!context || !Object.keys(context).length) {
    node.innerHTML = "";
    node.hidden = true;
    return;
  }
  const stableText = context.stable_only ? "stable only" : "stable + unstable";
  const comparisonLs = `${context.current_ls_min ?? "-"}-${context.current_ls_max ?? "-"}`;
  const referenceLs = `${context.reference_ls_min ?? "-"}-${context.reference_ls_max ?? "-"}`;
  node.innerHTML = `
    <div class="projection-summary-grid">
      <article class="projection-summary-card">
        <div class="summary-card-head">
          <span>Reference</span>
          <strong>Run ${escapeHtml(context.reference_run ?? "-")}</strong>
        </div>
        <div class="summary-card-stats">
          <div>
            <span>Avg inst lumi</span>
            <strong>${escapeHtml(fmtLumi(context.reference_inst_lumi_avg))}</strong>
          </div>
          <div>
            <span>Latest inst lumi</span>
            <strong>${escapeHtml(fmtLumi(context.reference_inst_lumi_latest))}</strong>
          </div>
        </div>
        <p>LS ${escapeHtml(referenceLs)}</p>
      </article>
      <article class="projection-summary-card">
        <div class="summary-card-head">
          <span>Comparison</span>
          <strong>Run ${escapeHtml(context.current_run ?? "-")}</strong>
        </div>
        <div class="summary-card-stats">
          <div>
            <span>Avg inst lumi</span>
            <strong>${escapeHtml(fmtLumi(context.current_inst_lumi_avg))}</strong>
          </div>
          <div>
            <span>Latest inst lumi</span>
            <strong>${escapeHtml(fmtLumi(context.current_inst_lumi_latest))}</strong>
          </div>
        </div>
        <p>LS ${escapeHtml(comparisonLs)} · ${escapeHtml(stableText)}</p>
      </article>
    </div>
  `;
  node.hidden = false;
}

function renderExportLinks(exports) {
  const node = $("#export-links");
  if (!node) return;
  if (!exports || (!exports.latest && !exports.full)) {
    node.innerHTML = "";
    node.hidden = true;
    return;
  }
  node.hidden = false;
  const links = [];
  if (exports.latest) {
    links.push(`<a class="chip link-chip" href="${exports.latest.url}">Saved latest CSV: ${exports.latest.filename}</a>`);
    links.push(`<span class="chip">Path: ${exports.latest.path}</span>`);
  }
  if (exports.full) {
    links.push(`<a class="chip link-chip" href="${exports.full.url}">Saved full CSV: ${exports.full.filename}</a>`);
    links.push(`<span class="chip">Path: ${exports.full.path}</span>`);
  }
  node.innerHTML = links.join("");
}

async function saveProjectionCsv(kind) {
  const rows = kind === "full" ? state.projection?.series : state.projection?.latest;
  if (!rows || !rows.length) {
    toast("No projection rows to export yet.");
    return;
  }
  const button = kind === "full" ? $("#export-full-csv") : $("#export-latest-csv");
  const label = kind === "full" ? "Export full CSV" : "Export CSV";
  setButtonBusy(button, true, label, "Saving...");
  try {
    const payload = await fetchJson("/api/export-projection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        rows,
        context: state.projection?.context || {},
      }),
    });
    const exportInfo = payload.export;
    renderExportLinks({ [kind]: exportInfo });
    loadExports().catch((error) => toast(error.message));
    toast(`Saved CSV: ${exportInfo.filename}`);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, label, "Saving...");
  }
}

function renderRatePlotContext(context) {
  const node = $("#rate-plot-context");
  if (!node) return;
  node.innerHTML = Object.entries(context || {})
    .map(([key, value]) => `<span class="chip">${key}: ${value ?? "-"}</span>`)
    .join("");
}

function shortRateSampleLabel(sample, rows) {
  const run = rows[0]?.run;
  if (String(sample || "").startsWith("Reference")) {
    return `Reference ${run || String(sample).replace(/\D/g, "")}`;
  }
  const mode = String(sample || "")
    .replace(/\s*·\s*stable\+unstable/g, "")
    .replace(/\s*·\s*stable only/g, "")
    .replace(/^auto\s*·\s*/, "Auto · ");
  return run ? `${mode} · run ${run}` : mode;
}

function ratePlotLayout(rows, seed) {
  const yValues = rows.map((row) => Number(row.rate)).filter(Number.isFinite);
  const maxY = yValues.length ? Math.max(...yValues) : 1;
  const layout = plotLayout("Rate [Hz]");
  layout.height = 390;
  layout.margin = { l: 62, r: 20, t: 88, b: 58 };
  layout.title = {
    text: seed,
    font: { color: "#f0f6fc", size: 15 },
    x: 0.5,
    xanchor: "center",
    y: 0.98,
  };
  layout.showlegend = true;
  layout.legend = {
    orientation: "h",
    x: 0,
    y: 1.16,
    xanchor: "left",
    yanchor: "bottom",
    bgcolor: "rgba(15, 21, 30, 0.78)",
    bordercolor: "#263241",
    borderwidth: 1,
    font: { color: "#dce6f2", size: 11 },
  };
  layout.paper_bgcolor = "#0f151e";
  layout.plot_bgcolor = "#0f151e";
  layout.xaxis.title = { text: "Inst luminosity", font: { color: "#dce6f2", size: 12 } };
  layout.xaxis.tickformat = ".1e";
  layout.xaxis.zeroline = false;
  layout.xaxis.showspikes = true;
  layout.yaxis.title = { text: "Rate [Hz]", font: { color: "#dce6f2", size: 12 } };
  layout.yaxis.showspikes = true;
  if (maxY > 0 && yValues.length && Math.min(...yValues) > maxY * 0.6) {
    layout.yaxis.range = [maxY * 0.8, maxY * 1.2];
  } else {
    layout.yaxis.rangemode = "tozero";
  }
  return layout;
}

function sampleStyle(sample) {
  if (!sample.startsWith("Reference")) {
    const palette = [
      ["#ff7b72", "diamond", "#ffd1cd"],
      ["#d29922", "square", "#f0d98c"],
      ["#a371f7", "triangle-up", "#d2b6ff"],
      ["#3fb950", "cross", "#9be9a8"],
      ["#39c5cf", "star", "#9beef3"],
      ["#f778ba", "x", "#ffc2e3"],
    ];
    const index = Math.abs([...sample].reduce((sum, char) => sum + char.charCodeAt(0), 0)) % palette.length;
    const [color, symbol, lineColor] = palette[index];
    return {
      color,
      symbol,
      size: 10,
      line: { color: lineColor, width: 1.4 },
    };
  }
  return {
    color: "#58a6ff",
    symbol: "circle",
    size: 7,
    line: { color: "#a5d6ff", width: 0.8 },
  };
}

function renderRatePlots(rows) {
  const grid = $("#rate-plot-grid");
  state.ratePlotSheetRevision += 1;
  state.ratePlotSheetCache = null;
  if (!rows || !rows.length) {
    grid.innerHTML = `<div class="seed-empty">No rate points found for the selected settings.</div>`;
    return;
  }

  const grouped = new Map();
  rows.forEach((row) => {
    if (!grouped.has(row.pathname)) grouped.set(row.pathname, []);
    grouped.get(row.pathname).push(row);
  });

  grid.innerHTML = Array.from(grouped.entries()).map(([seed, values], index) => {
    const samples = [...new Set(values.map((row) => row.sample))];
    return `
    <article class="rate-plot-card">
      <header class="rate-plot-head">
        <h4 title="${escapeHtml(seed)}">${escapeHtml(seed)}</h4>
        <div class="rate-plot-actions">
          <span>${values.length} points</span>
          <button class="rate-download-button" type="button" data-rate-download="${index}" data-rate-name="${escapeHtml(seed)}" title="Download PNG" aria-label="Download ${escapeHtml(seed)} as PNG">
            <i class="fa-solid fa-download"></i>
          </button>
        </div>
      </header>
      <div id="rate-plot-${index}" class="rate-plot"></div>
    </article>
  `;
  }).join("");

  grid.querySelectorAll("[data-rate-download]").forEach((button) => {
    button.addEventListener("click", async () => {
      const index = Number(button.dataset.rateDownload);
      const seed = button.dataset.rateName || `rate_plot_${index}`;
      const plotId = `rate-plot-${index}`;
      button.disabled = true;
      try {
        await Plotly.downloadImage(plotId, {
          format: "png",
          filename: `rate_${filenameSlug(seed)}`,
          width: 1400,
          height: 900,
          scale: 2,
        });
      } catch (error) {
        toast(`PNG export failed: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
  });

  Array.from(grouped.entries()).forEach(([seed, values], index) => {
    const bySample = new Map();
    values
      .filter((row) => Number(row.init_lumi) > 0 && Number.isFinite(Number(row.rate)))
      .forEach((row) => {
      if (!bySample.has(row.sample)) bySample.set(row.sample, []);
      bySample.get(row.sample).push(row);
    });
    const order = (sample) => sample.startsWith("Reference") ? -1 : Number(sample.replace(/\D/g, "")) || 0;
    const traces = Array.from(bySample.entries())
      .sort(([a], [b]) => order(a) - order(b))
      .map(([sample, sampleRows]) => {
        const style = sampleStyle(sample);
        return {
          type: "scatter",
          mode: "markers",
          name: shortRateSampleLabel(sample, sampleRows),
          x: sampleRows.map((row) => row.init_lumi),
          y: sampleRows.map((row) => row.rate),
          marker: {
            color: style.color,
            symbol: style.symbol,
            size: style.size,
            opacity: sample.startsWith("Reference") ? 0.62 : 0.96,
            line: style.line,
          },
          hovertemplate: `%{fullData.name}<br>lumi %{x:.3e}<br>rate %{y:.3f} Hz<br>LS %{customdata}<extra></extra>`,
          customdata: sampleRows.map((row) => row.lumisection),
        };
      });
    if (!traces.length) {
      traces.push({
        type: "scatter",
        mode: "markers",
        x: [],
        y: [],
        hoverinfo: "skip",
      });
    }
    const layout = ratePlotLayout(values, seed);
    if (traces.length === 1 && !traces[0].x.length) {
      layout.annotations = [{
        text: "No positive-lumi rate points.",
        xref: "paper",
        yref: "paper",
        x: 0.5,
        y: 0.5,
        showarrow: false,
        font: { color: "#8b949e", size: 13 },
      }];
    }
    Plotly.react(`rate-plot-${index}`, traces, layout, {
      responsive: true,
      displaylogo: false,
      displayModeBar: false,
    });
  });
}

function ratePlotNodes() {
  return $$("#rate-plot-grid .rate-plot")
    .filter((node) => node.id && node._fullLayout);
}

function selectedRatePlotSheetKey() {
  const key = valueOf("#rate-sheet-layout", "4x4");
  return RATE_PLOT_SHEETS[key] ? key : "4x4";
}

function selectedRatePlotSheet() {
  return RATE_PLOT_SHEETS[selectedRatePlotSheetKey()];
}

async function exportRatePlotImage(plotNode, width, height, layoutKey) {
  const large = layoutKey === "2x2";
  const data = JSON.parse(JSON.stringify(plotNode.data || []));
  const layout = JSON.parse(JSON.stringify(plotNode.layout || {}));
  layout.width = width;
  layout.height = height;
  layout.autosize = false;
  layout.title = { text: "" };
  layout.margin = large
    ? { l: 92, r: 28, t: 92, b: 82 }
    : { l: 68, r: 20, t: 66, b: 58 };
  layout.legend = {
    ...(layout.legend || {}),
    orientation: "h",
    x: 0,
    y: 1.1,
    xanchor: "left",
    yanchor: "bottom",
    bgcolor: "rgba(15, 21, 30, 0.82)",
    bordercolor: "#263241",
    borderwidth: 1,
    font: { color: "#dce6f2", size: large ? 18 : 13 },
  };
  layout.xaxis = {
    ...(layout.xaxis || {}),
    title: { text: "Inst luminosity", font: { color: "#dce6f2", size: large ? 20 : 15 } },
    tickfont: { color: "#dce6f2", size: large ? 18 : 13 },
  };
  layout.yaxis = {
    ...(layout.yaxis || {}),
    title: { text: "Rate [Hz]", font: { color: "#dce6f2", size: large ? 20 : 15 } },
    tickfont: { color: "#dce6f2", size: large ? 18 : 13 },
  };

  const node = document.createElement("div");
  node.style.position = "fixed";
  node.style.left = "-10000px";
  node.style.top = "0";
  node.style.width = `${width}px`;
  node.style.height = `${height}px`;
  document.body.appendChild(node);
  try {
    await Plotly.newPlot(node, data, layout, {
      displayModeBar: false,
      displaylogo: false,
      responsive: false,
      staticPlot: true,
    });
    return await Plotly.toImage(node, {
      format: "png",
      width,
      height,
      scale: 1,
    });
  } finally {
    Plotly.purge(node);
    node.remove();
  }
}

async function buildRatePlotSheetPages() {
  const plots = ratePlotNodes();
  if (!plots.length) {
    throw new Error("Draw rate plots first.");
  }

  const layoutKey = selectedRatePlotSheetKey();
  if (
    state.ratePlotSheetCache?.revision === state.ratePlotSheetRevision
    && state.ratePlotSheetCache?.layoutKey === layoutKey
  ) {
    return state.ratePlotSheetCache.pages;
  }

  const { pageWidth, pageHeight, margin, headerHeight, gapX, gapY, cols, rows } = selectedRatePlotSheet();
  const perPage = cols * rows;
  const cellWidth = Math.floor((pageWidth - margin * 2 - gapX * (cols - 1)) / cols);
  const cellHeight = Math.floor((pageHeight - margin * 2 - headerHeight - gapY * (rows - 1)) / rows);
  const pageCount = Math.ceil(plots.length / perPage);
  const pages = [];

  for (let pageIndex = 0; pageIndex < pageCount; pageIndex += 1) {
    setBusy(true, `Building rate plot page ${pageIndex + 1}/${pageCount}...`);
    await waitForPaint();
    const canvas = document.createElement("canvas");
    canvas.width = pageWidth;
    canvas.height = pageHeight;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#0f151e";
    ctx.fillRect(0, 0, pageWidth, pageHeight);

    ctx.fillStyle = "#f0f6fc";
    ctx.font = "700 48px Inter, Arial, sans-serif";
    ctx.fillText("OMS L1 Rate Plots", margin, 72);
    ctx.fillStyle = "#8b949e";
    ctx.font = "500 26px Inter, Arial, sans-serif";
    ctx.fillText(`${layoutKey} sheet · Page ${pageIndex + 1}/${pageCount} · ${new Date().toLocaleString()}`, margin, 112);

    const chunk = plots.slice(pageIndex * perPage, (pageIndex + 1) * perPage);
    for (const [chunkIndex, plotNode] of chunk.entries()) {
      const col = chunkIndex % cols;
      const row = Math.floor(chunkIndex / cols);
      const x = margin + col * (cellWidth + gapX);
      const y = margin + headerHeight + row * (cellHeight + gapY);
      const titleHeight = layoutKey === "2x2" ? 64 : 46;
      const plotY = y + titleHeight;
      const plotHeight = cellHeight - titleHeight;

      ctx.fillStyle = "#111821";
      ctx.strokeStyle = "#263241";
      ctx.lineWidth = 2;
      ctx.fillRect(x, y, cellWidth, cellHeight);
      ctx.strokeRect(x, y, cellWidth, cellHeight);

      const title = plotNode._fullLayout?.title?.text || plotNode.layout?.title?.text || "Rate plot";
      ctx.fillStyle = "#f0f6fc";
      ctx.font = `800 ${layoutKey === "2x2" ? 34 : 25}px Inter, Arial, sans-serif`;
      ctx.textBaseline = "middle";
      ctx.fillText(
        truncateCanvasText(ctx, title, cellWidth - 28),
        x + 16,
        y + Math.floor(titleHeight / 2),
      );

      const dataUrl = await exportRatePlotImage(plotNode, cellWidth, plotHeight, layoutKey);
      const image = await loadImage(dataUrl);
      ctx.drawImage(image, x, plotY, cellWidth, plotHeight);
    }
    pages.push(canvas.toDataURL("image/png", 0.94));
  }

  state.ratePlotSheetCache = {
    revision: state.ratePlotSheetRevision,
    layoutKey,
    pages,
  };
  return pages;
}

async function downloadRatePlotPngSheets() {
  const button = $("#download-rate-png-sheet");
  const layoutKey = selectedRatePlotSheetKey();
  setButtonBusy(button, true, "PNG sheet", "Building...");
  setBusy(true, `Building ${layoutKey} PNG sheet...`);
  try {
    const pages = await buildRatePlotSheetPages();
    pages.forEach((dataUrl, index) => {
      downloadDataUrl(`rate_plots_${layoutKey}_page_${index + 1}.png`, dataUrl);
    });
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "PNG sheet", "Building...");
    setBusy(false);
  }
}

async function downloadRatePlotPdfSheet() {
  const button = $("#download-rate-pdf-sheet");
  const layoutKey = selectedRatePlotSheetKey();
  setButtonBusy(button, true, "PDF sheet", "Building...");
  setBusy(true, `Building ${layoutKey} PDF sheet...`);
  try {
    const JsPdf = window.jspdf?.jsPDF;
    if (!JsPdf) {
      throw new Error("PDF library was not loaded. Use PNG sheets or reload the page.");
    }
    const pages = await buildRatePlotSheetPages();
    const sheet = selectedRatePlotSheet();
    const pdfWidth = 1280;
    const pdfHeight = Math.round(pdfWidth * sheet.pageHeight / sheet.pageWidth);
    const pdf = new JsPdf({ orientation: "landscape", unit: "pt", format: [pdfWidth, pdfHeight] });
    const width = pdf.internal.pageSize.getWidth();
    const height = pdf.internal.pageSize.getHeight();
    pages.forEach((dataUrl, index) => {
      if (index > 0) pdf.addPage();
      pdf.addImage(dataUrl, "PNG", 0, 0, width, height);
    });
    pdf.save(`rate_plots_${layoutKey}_${new Date().toISOString().slice(0, 10)}.pdf`);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "PDF sheet", "Building...");
    setBusy(false);
  }
}

async function runRatePlots() {
  const button = $("#run-rate-plots");
  setBusy(true, "Drawing rate plots...");
  setButtonBusy(button, true, "Draw plots", "Drawing...");
  try {
    await waitForPaint();
    const comparisons = state.comparisons.length ? state.comparisons : [comparisonFromForm()];
    const rows = [];
    const contexts = [];
    for (const [index, comparison] of comparisons.entries()) {
      setBusy(true, `Drawing ${comparisonLabel(comparison)}...`);
      const data = await fetchJson("/api/rate-plots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectionPayload(comparison)),
      });
      contexts.push({
        label: comparisonLabel(comparison),
        context: data.context || {},
      });
      (data.rows || []).forEach((row) => {
        if (index > 0 && String(row.sample || "").startsWith("Reference")) return;
        if (!String(row.sample || "").startsWith("Reference")) {
          row.sample = comparisonLabel(comparison);
        }
        rows.push(row);
      });
    }
    state.ratePlots = { rows, contexts };
    renderRatePlotContext({
      comparisons: contexts.length,
      trigger_file: valueOf("#trigger-file", "ALL"),
    });
    renderRatePlots(rows);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "Draw plots", "Drawing...");
    setBusy(false);
  }
}

function renderExports(payload) {
  const exportDir = payload.export_dir || "No export directory loaded.";
  const exportDirLabel = $("#export-dir-label");
  if (exportDirLabel) exportDirLabel.textContent = exportDir;

  const body = $("#exports-table");
  const files = payload.files || [];
  if (!files.length) {
    if (body) body.innerHTML = `<tr><td colspan="4">No saved CSV exports yet.</td></tr>`;
    return;
  }
  if (body) {
    body.innerHTML = files.map((file) => `
    <tr>
      <td class="seed" title="${file.path}">${file.filename}</td>
      <td>${file.modified_time || "-"}</td>
      <td class="num">${fmtBytes(file.size_bytes)}</td>
      <td><a class="table-link" href="${file.url}">Download</a></td>
    </tr>
    `).join("");
  }
}

async function loadExports() {
  const payload = await fetchJson("/api/exports");
  renderExports(payload);
}

function renderProjectionLatest(rows) {
  const body = $("#projection-latest");
  const fullBody = $("#full-l1-table");
  if (!rows.length) {
    const empty = `<tr><td colspan="9">No projection rows found for this comparison. Include unstable LS or change the LS range.</td></tr>`;
    body.innerHTML = empty;
    if (fullBody) {
      fullBody.innerHTML = `<tr><td colspan="9">Run a projection to populate this table.</td></tr>`;
    }
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td class="seed" title="${row.pathname}">${row.pathname}</td>
      <td class="num">${lsWindowText(row)}</td>
      <td class="num">${row.n_points ?? "-"}</td>
      <td class="num">${row.bit ?? "-"}</td>
      <td class="num">${fmt(row.reference_rate)}</td>
      <td class="num">${fmt(row.lumi_ratio, 3)}</td>
      <td class="num">${fmt(row.expected_rate)}</td>
      <td class="num">${fmt(row.rate)}</td>
      <td class="num ${ratioClass(row.ratio)}">${fmt(row.ratio, 3)}</td>
    </tr>
  `).join("");
  const sorted = [...rows].sort((a, b) => Number(b.ratio || -Infinity) - Number(a.ratio || -Infinity));
  if (fullBody) {
    fullBody.innerHTML = sorted.map((row) => `
      <tr>
        <td class="seed" title="${row.pathname}">${row.pathname}</td>
        <td class="num">${row.lumisection || "-"}</td>
        <td class="num">${row.bit ?? "-"}</td>
        <td class="num">${fmt(row.reference_rate)}</td>
        <td class="num">${fmt(row.lumi_ratio, 3)}</td>
        <td class="num">${fmt(row.expected_rate)}</td>
        <td class="num">${fmt(row.rate)}</td>
        <td class="num ${ratioClass(row.ratio)}">${fmt(row.ratio, 3)}</td>
      </tr>
    `).join("");
  }
}

function renderProjectionTabs() {
  const node = $("#comparison-result-tabs");
  if (!node) return;
  if (!state.projectionResults.length) {
    node.innerHTML = "";
    return;
  }
  node.innerHTML = state.projectionResults.map((result, index) => `
    <button class="comparison-tab ${index === state.activeProjectionIndex ? "active" : ""}" type="button" data-projection-index="${index}">
      ${escapeHtml(result.label)}
    </button>
  `).join("");
}

function showProjectionResult(index) {
  const result = state.projectionResults[index];
  if (!result) return;
  state.activeProjectionIndex = index;
  state.projection = result.data;
  renderProjectionTabs();
  renderContext(result.data.context || {});
  renderExportLinks(null);
  renderProjectionLatest(result.data.latest || []);
  renderDeviationChart(result.data.series || []);
}

function renderL1PrescaleContext(payload) {
  const context = $("#l1-prescale-context");
  const summary = $("#l1-prescale-summary");
  if (!payload || !payload.run) {
    if (context) context.innerHTML = "";
    if (summary) summary.textContent = "Choose a run and load the adopted L1 prescale table.";
    return;
  }
  const run = payload.run;
  if (summary) {
    summary.textContent = `${payload.count || 0} L1 seeds for run ${run.run_number || "-"}.`;
  }
  if (context) {
    const lumi = payload.lumi || {};
    const chips = {
      run: run.run_number,
      latest_inst_lumi: fmtLumi(lumi.latest_init_lumi ?? run.init_lumi),
      avg_inst_lumi: fmtLumi(lumi.average_init_lumi),
      stable_avg_inst_lumi: fmtLumi(lumi.stable_average_init_lumi),
      lumi_ls: lumi.n_lumisections ? `${lumi.ls_min}-${lumi.ls_max}` : "-",
      l1_key: run.l1_key || "-",
      l1_menu: run.l1_menu || "-",
      initial_prescale_index: run.initial_prescale_index ?? "-",
      trigger_mode: run.trigger_mode || "-",
      hlt_key: run.hlt_key || "-",
    };
    context.innerHTML = Object.entries(chips)
      .map(([key, value]) => `<span class="chip">${key}: ${escapeHtml(value)}</span>`)
      .join("");
  }
}

function filteredL1PrescaleRows() {
  const query = valueOf("#l1-table-filter").trim().toLowerCase();
  const monitoringOnly = $("#l1-prescale-monitoring-only")?.checked !== false;
  const monitoring = new Set(state.monitoringSeeds);
  return state.l1PrescaleRows.filter((row) => {
    const name = String(row.name || "");
    if (monitoringOnly && !monitoring.has(name)) return false;
    if (query && !name.toLowerCase().includes(query)) return false;
    return true;
  });
}

function renderL1PrescaleTable() {
  const body = $("#l1-prescale-table");
  if (!body) return;
  const rows = filteredL1PrescaleRows();
  const summary = $("#l1-prescale-summary");
  if (summary && state.l1PrescalePayload?.run) {
    const run = state.l1PrescalePayload.run;
    const monitoringOnly = $("#l1-prescale-monitoring-only")?.checked !== false;
    const suffix = monitoringOnly ? `, filtered to ${state.monitoringSeeds.length} monitoring seeds` : "";
    summary.textContent = `${rows.length}/${state.l1PrescaleRows.length} L1 seeds shown for run ${run.run_number || "-"}${suffix}.`;
  }
  if (!rows.length) {
    const monitoringOnly = $("#l1-prescale-monitoring-only")?.checked !== false;
    const message = state.l1PrescaleRows.length
      ? `No rows match the current ${monitoringOnly ? "monitoring seed and " : ""}text filter.`
      : "No L1 prescale rows loaded.";
    body.innerHTML = `<tr><td colspan="7">${message}</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td class="num">${row.bit ?? "-"}</td>
      <td class="seed" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</td>
      <td class="num">${fmt(row.inferred_prescale, 3)}</td>
      <td class="num">${fmt(row.pre_dt_before_prescale_rate)}</td>
      <td class="num">${fmt(row.pre_dt_rate)}</td>
      <td class="num">${fmt(row.post_dt_rate)}</td>
      <td class="num">${fmt(row.post_dt_hlt_rate)}</td>
    </tr>
  `).join("");
}

function prescaleText(row, prefix) {
  const value = row[`${prefix}_prescale`];
  return value === null || value === undefined ? "-" : fmt(value, 3);
}

const RATE_SNAPSHOT_HELP = {
  "L1A calibration": "L1 accept rate assigned to calibration triggers.",
  "L1A physics": "L1 accept rate from physics triggers.",
  "L1A random": "L1 accept rate from random triggers.",
  "Total L1A": "Total Level-1 accept rate after all L1 accept categories are combined.",
  "PhysicsGeneratedFDL GT": "Physics trigger rate generated by the Global Trigger FDL.",
  "PhysicsGeneratedFDL TCDS": "Physics trigger rate as reported through TCDS.",
  "Total before deadtime": "Total trigger rate before deadtime losses are applied.",
  "Trigger physics beam active": "Physics trigger rate while the beam-active condition is true.",
  "Trigger physics beam inactive": "Physics trigger rate while the beam-active condition is false.",
  "Total": "Overall deadtime fraction and count.",
  "TTS": "Deadtime from Trigger Throttling System states.",
  "Trigger Rules": "Deadtime introduced by trigger rules such as BX spacing limits.",
  "Bunch Mask": "Deadtime or loss associated with bunch mask vetoes.",
  "ReTri": "Deadtime from retrigger protection.",
  "APVE": "Deadtime associated with APV emulation/protection.",
  "Calibration": "Deadtime from calibration activity.",
  "Software Pause": "Deadtime caused by software pause conditions.",
  "Firmware Pause": "Deadtime caused by firmware pause conditions.",
};

function helpLabel(value) {
  const label = escapeHtml(value ?? "-");
  const help = RATE_SNAPSHOT_HELP[value];
  if (!help) return label;
  const safeHelp = escapeHtml(help);
  return `
    <span class="help-label">
      <span>${label}</span>
      <span class="info-dot" tabindex="0" role="note" aria-label="${safeHelp}" data-tooltip="${safeHelp}">i</span>
    </span>
  `;
}

function setupInfoTooltips() {
  let tooltip = null;

  const ensureTooltip = () => {
    if (tooltip) return tooltip;
    tooltip = document.createElement("div");
    tooltip.className = "floating-tooltip";
    document.body.appendChild(tooltip);
    return tooltip;
  };

  const hideTooltip = () => {
    if (!tooltip) return;
    tooltip.classList.remove("visible");
  };

  const showTooltip = (target) => {
    const text = target?.dataset?.tooltip;
    if (!text) return;
    const tip = ensureTooltip();
    tip.textContent = text;
    tip.classList.add("visible");

    const targetBox = target.getBoundingClientRect();
    const tipBox = tip.getBoundingClientRect();
    const padding = 14;
    let left = targetBox.left + targetBox.width / 2 - tipBox.width / 2;
    let top = targetBox.bottom + 10;

    left = Math.max(padding, Math.min(left, window.innerWidth - tipBox.width - padding));
    if (top + tipBox.height + padding > window.innerHeight) {
      top = targetBox.top - tipBox.height - 10;
    }
    top = Math.max(padding, top);

    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };

  document.addEventListener("mouseover", (event) => {
    const target = event.target.closest(".info-dot");
    if (target) showTooltip(target);
  });
  document.addEventListener("focusin", (event) => {
    const target = event.target.closest(".info-dot");
    if (target) showTooltip(target);
  });
  document.addEventListener("mouseout", (event) => {
    if (event.target.closest(".info-dot")) hideTooltip();
  });
  document.addEventListener("focusout", (event) => {
    if (event.target.closest(".info-dot")) hideTooltip();
  });
  window.addEventListener("scroll", hideTooltip, true);
  window.addEventListener("resize", hideTooltip);
}

function renderRateSnapshotSummaryTable(selector, rows, columns) {
  const body = $(selector);
  if (!body) return;
  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="${columns.length}">No rows found.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      ${columns.map((column) => {
        const value = row[column.key];
        const text = column.format === "number"
          ? fmt(value)
          : column.format === "integer"
            ? fmt(value, 0)
            : escapeHtml(value ?? "-");
        const className = column.align === "left" ? "" : "num";
        if (column.help) {
          return `<td class="${className}">${helpLabel(value)}</td>`;
        }
        return `<td class="${className}">${column.format === "text" ? text : escapeHtml(text)}</td>`;
      }).join("")}
    </tr>
  `).join("");
}

function renderRateSnapshot(payload) {
  state.rateSnapshot = payload;
  const rows = payload?.rows || [];
  const reference = payload?.reference || null;
  const summary = $("#rate-snapshot-summary");
  if (summary) {
    const refText = reference?.run?.run_number ? `, reference ${reference.run.run_number}` : "";
    summary.textContent = `${rows.length} monitoring seeds for run ${payload?.run?.run_number || "-"}${refText}.`;
  }
  const head = $("#rate-snapshot-rate-head");
  if (head) head.textContent = `${payload?.rate_label || "Rate"} [Hz]`;

  const metrics = $("#rate-snapshot-metrics");
  if (metrics) {
    const run = payload?.run || {};
    const lumi = payload?.lumi || {};
    const selection = payload?.selection || {};
    const cards = [
      metric("Run", run.run_number || "-", run.sequence || "GLOBAL-RUN", "fa-hashtag", "blue"),
      metric("Fill", run.fill_number || "-", "OMS fill", "fa-circle-nodes", "green"),
      metric("Last LS", run.last_lumisection_number || "-", "latest lumisection", "fa-clock", "purple"),
      metric("Selected LS", selection.label || "Run summary", `${lumi.n_lumisections || 0} points`, "fa-layer-group", "blue"),
      metric("Selected rate", payload?.rate_label || "-", "active rate field", "fa-gauge-high", "blue"),
      metric("Avg inst lumi", fmtLumi(lumi.average_init_lumi), "selected LS", "fa-chart-line", "gold"),
      metric("Latest inst lumi", fmtLumi(lumi.latest_init_lumi), `LS ${lumi.latest_lumisection || "-"}`, "fa-bolt", "purple"),
      metric("L1 key", run.l1_key || "-", `prescale index ${run.initial_prescale_index ?? "-"}`, "fa-key", "green"),
    ];
    if (reference) {
      cards.push(
        metric(
          "Reference run",
          reference.run?.run_number || "-",
          reference.selection?.label || "Run summary",
          "fa-code-compare",
          "blue",
        ),
        metric(
          "Reference lumi",
          fmtLumi(reference.lumi?.average_init_lumi),
          `${reference.lumi?.n_lumisections || 0} points`,
          "fa-chart-simple",
          "gold",
        ),
      );
    }
    metrics.innerHTML = cards.join("");
  }

  renderRateSnapshotSummaryTable("#rate-snapshot-l1-summary", payload?.l1_triggers || [], [
    { key: "name", format: "text", align: "left", help: true },
    { key: "rate", format: "number" },
    { key: "counter", format: "integer" },
  ]);
  renderRateSnapshotSummaryTable("#rate-snapshot-deadtimes", payload?.deadtimes || [], [
    { key: "name", format: "text", align: "left", help: true },
    { key: "percent", format: "number" },
    { key: "counter", format: "integer" },
  ]);

  const body = $("#rate-snapshot-table");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7">No monitoring seed rows found for this run.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td class="num">${escapeHtml(row.current_run ?? payload?.run?.run_number ?? "-")}</td>
      <td class="seed" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</td>
      <td class="num">${fmt(row.reference_rate)}</td>
      <td class="num">${fmt(row.rate)}</td>
      <td class="num ${ratioClass(row.raw_ratio)}">${fmt(row.raw_ratio, 3)}</td>
      <td class="num">${escapeHtml(prescaleText(row, "initial"))}</td>
      <td class="num">${escapeHtml(prescaleText(row, "final"))}</td>
    </tr>
  `).join("");
}

async function loadRateSnapshot() {
  const button = $("#load-rate-snapshot");
  const run = valueOf("#rate-snapshot-run").trim();
  const lsMode = valueOf("#rate-snapshot-ls-mode", "run");
  const referenceRun = valueOf("#rate-snapshot-reference-run").trim();
  const referenceLsMode = valueOf("#rate-snapshot-reference-ls-mode", "run");
  const params = new URLSearchParams({
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    ls_mode: lsMode,
  });
  if (run) params.set("run", run);
  if (lsMode === "range") {
    params.set("ls_min", valueOf("#rate-snapshot-ls-min", "1") || "1");
    params.set("ls_max", valueOf("#rate-snapshot-ls-max", "20") || "20");
  } else if (lsMode === "single") {
    params.set("ls", valueOf("#rate-snapshot-single-ls", "1") || "1");
  }
  if (referenceRun) {
    params.set("reference_run", referenceRun);
    params.set("reference_ls_mode", referenceLsMode);
    if (referenceLsMode === "range") {
      params.set("reference_ls_min", valueOf("#rate-snapshot-reference-ls-min", "1") || "1");
      params.set("reference_ls_max", valueOf("#rate-snapshot-reference-ls-max", "20") || "20");
    } else if (referenceLsMode === "single") {
      params.set("reference_ls", valueOf("#rate-snapshot-reference-single-ls", "1") || "1");
    }
  }
  setBusy(true, "Loading rate snapshot...");
  setButtonBusy(button, true, "Process snapshot", "Loading...");
  try {
    await waitForPaint();
    if (!state.monitoringSeeds.length) {
      await loadMonitoringSeeds();
    }
    const payload = await fetchJson(`/api/rate-snapshot?${params.toString()}`);
    renderRateSnapshot(payload);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "Process snapshot", "Loading...");
    setBusy(false);
  }
}

function updateRateSnapshotLsControls() {
  const mode = valueOf("#rate-snapshot-ls-mode", "run");
  $$('[data-snapshot-ls-mode]').forEach((node) => {
    node.hidden = node.dataset.snapshotLsMode !== mode;
  });
  const referenceMode = valueOf("#rate-snapshot-reference-ls-mode", "run");
  $$('[data-snapshot-reference-ls-mode]').forEach((node) => {
    node.hidden = node.dataset.snapshotReferenceLsMode !== referenceMode;
  });
}

function rateSnapshotProjectionEnabled() {
  return $("#rate-snapshot-do-projection")?.checked === true;
}

function updateRateSnapshotProjectionModeControls(group) {
  const mode = valueOf(`#rate-snapshot-projection-${group}-mode`, group === "current" ? "latest_window" : "range");
  $$(`[data-snapshot-projection-mode="${group}"]`).forEach((node) => {
    const modes = String(node.dataset.modes || "").split(/\s+/).filter(Boolean);
    node.hidden = !modes.includes(mode);
  });
}

function updateRateSnapshotProjectionControls() {
  const enabled = rateSnapshotProjectionEnabled();
  const wrap = $("#rate-snapshot-projection-options");
  if (wrap) wrap.hidden = !enabled;
  if (!enabled) return;
  updateRateSnapshotProjectionModeControls("reference");
  updateRateSnapshotProjectionModeControls("current");
}

function seedRateSnapshotProjectionDefaults() {
  const currentMode = valueOf("#rate-snapshot-ls-mode", "run");
  if (currentMode === "range") {
    setValue("#rate-snapshot-projection-current-mode", "range");
    setValue("#rate-snapshot-projection-current-ls-min", valueOf("#rate-snapshot-ls-min", "1"));
    setValue("#rate-snapshot-projection-current-ls-max", valueOf("#rate-snapshot-ls-max", "20"));
  } else if (currentMode === "single") {
    setValue("#rate-snapshot-projection-current-mode", "single");
    setValue("#rate-snapshot-projection-current-single-ls", valueOf("#rate-snapshot-single-ls", "1"));
  } else {
    setValue("#rate-snapshot-projection-current-mode", "latest_window");
    const lastLs = finiteNumber(state.dashboard?.summary?.last_lumisection_number);
    const windowSize = finiteNumber(valueOf("#ls-window", "20")) || 20;
    if (lastLs !== null) {
      setValue("#rate-snapshot-projection-current-window", Math.max(1, Math.min(windowSize, lastLs)));
    }
  }

  const referenceMode = valueOf("#rate-snapshot-reference-ls-mode", "run");
  if (referenceMode === "single") {
    setValue("#rate-snapshot-projection-reference-mode", "single");
    setValue("#rate-snapshot-projection-reference-single-ls", valueOf("#rate-snapshot-reference-single-ls", "1"));
  } else {
    setValue("#rate-snapshot-projection-reference-mode", "range");
    setValue("#rate-snapshot-projection-reference-ls-min", valueOf("#rate-snapshot-reference-ls-min", "1"));
    setValue("#rate-snapshot-projection-reference-ls-max", valueOf("#rate-snapshot-reference-ls-max", "20"));
  }
  updateRateSnapshotProjectionControls();
}

function rateSnapshotProjectionPayload(snapshotPayload) {
  const currentRun = finiteNumber(valueOf("#rate-snapshot-run"));
  const referenceRun = finiteNumber(valueOf("#rate-snapshot-reference-run"));
  if (referenceRun === null) {
    throw new Error("Reference run is required for projection mode.");
  }

  return {
    trigger_file: snapshotPayload?.monitoring_path || valueOf("#trigger-file", "ALL"),
    rate_field: valueOf("#rate-field", state.config?.default_rate_field || "pre_dt_before_prescale_rate"),
    reference_run: referenceRun,
    reference_lumi_mode: valueOf("#rate-snapshot-projection-reference-mode", "range"),
    reference_ls_min: Number(valueOf("#rate-snapshot-projection-reference-ls-min", "1") || 1),
    reference_ls_max: Number(valueOf("#rate-snapshot-projection-reference-ls-max", "1") || 1),
    reference_single_ls: Number(valueOf("#rate-snapshot-projection-reference-single-ls", "1") || 1),
    reference_hardcoded_lumi: Number(valueOf("#rate-snapshot-projection-reference-hardcoded-lumi", "0") || 0),
    current_run: currentRun,
    current_runs: currentRun !== null ? [currentRun] : [],
    current_lumi_mode: valueOf("#rate-snapshot-projection-current-mode", "latest_window"),
    current_ls_window: Number(valueOf("#rate-snapshot-projection-current-window", "20") || 20),
    current_ls_min: Number(valueOf("#rate-snapshot-projection-current-ls-min", "1") || 1),
    current_ls_max: Number(valueOf("#rate-snapshot-projection-current-ls-max", "1") || 1),
    current_single_ls: Number(valueOf("#rate-snapshot-projection-current-single-ls", "1") || 1),
    current_hardcoded_lumi: Number(valueOf("#rate-snapshot-projection-current-hardcoded-lumi", "0") || 0),
    projection_plot_ls_limit: state.config?.default_projection_plot_ls_limit || 120,
    stable_only: !$("#rate-snapshot-projection-include-unstable")?.checked,
  };
}

function rateSnapshotProjectionSelectionText(context, prefix) {
  if (!context) return "Run summary";
  const mode = String(context[`${prefix}_lumi_mode`] || "");
  const minLs = context[`${prefix}_ls_min`];
  const maxLs = context[`${prefix}_ls_max`];
  const points = context[`${prefix}_lumi_points`];
  if (mode === "single" && minLs !== null && minLs !== undefined) {
    return `LS ${minLs}`;
  }
  if ((mode === "range" || mode === "latest_window") && minLs !== null && minLs !== undefined && maxLs !== null && maxLs !== undefined) {
    return Number(minLs) === Number(maxLs) ? `LS ${maxLs}` : `LS ${minLs}-${maxLs}`;
  }
  if (mode === "hardcoded") return "Hardcoded lumi";
  if (Number.isFinite(Number(points)) && Number(points) > 0) return `${points} points`;
  return "Run summary";
}

function mergeRateSnapshotProjectionRows(snapshotPayload, projectionPayload) {
  const snapshotRows = snapshotPayload?.rows || [];
  const projectionRows = projectionPayload?.latest || [];
  const bySeed = new Map(
    projectionRows.map((row) => [String(row.pathname || ""), row]).filter(([key]) => key),
  );
  const merged = [];
  const seen = new Set();

  snapshotRows.forEach((row) => {
    const name = String(row.name || "");
    const projected = bySeed.get(name);
    seen.add(name);
    merged.push({
      current_run: row.current_run ?? projectionPayload?.context?.current_run ?? snapshotPayload?.run?.run_number,
      name,
      bit: projected?.bit ?? row.bit ?? null,
      ls: projected ? lsWindowText(projected) : "-",
      points: projected?.n_points ?? row.points ?? null,
      reference_rate: projected?.reference_rate ?? row.reference_rate ?? null,
      lumi_ratio: projected?.lumi_ratio ?? null,
      expected_rate: projected?.expected_rate ?? null,
      measured_rate: projected?.rate ?? row.rate ?? null,
      ratio: projected?.ratio ?? null,
      initial_prescale: row.initial_prescale ?? null,
      final_prescale: row.final_prescale ?? null,
    });
  });

  projectionRows.forEach((row) => {
    const name = String(row.pathname || "");
    if (!name || seen.has(name)) return;
    merged.push({
      current_run: projectionPayload?.context?.current_run ?? snapshotPayload?.run?.run_number ?? null,
      name,
      bit: row.bit ?? null,
      ls: lsWindowText(row),
      points: row.n_points ?? null,
      reference_rate: row.reference_rate ?? null,
      lumi_ratio: row.lumi_ratio ?? null,
      expected_rate: row.expected_rate ?? null,
      measured_rate: row.rate ?? null,
      ratio: row.ratio ?? null,
      initial_prescale: null,
      final_prescale: null,
    });
  });

  return merged;
}

function exportRateSnapshotCsv() {
  const payload = state.rateSnapshot;
  const rows = payload?.rows || [];
  if (!rows.length) {
    toast("No rate snapshot rows to export yet.");
    return;
  }
  const run = payload?.run?.run_number || "run";
  const ref = payload?.reference?.run?.run_number;
  const refSuffix = ref ? `_ref${ref}` : "";
  downloadCsv(`rate_snapshot_${run}${refSuffix}_${payload.rate_field || "rate"}.csv`, rows, [
    { key: "current_run", label: "Current Run" },
    { key: "name", label: "Trigger" },
    { key: "reference_rate", label: "Reference Rate [Hz]" },
    { key: "rate", label: `${payload.rate_label || "Rate"} [Hz]` },
    { key: "raw_ratio", label: "Raw Ratio" },
    { key: "initial_prescale", label: "Initial Prescale" },
    { key: "final_prescale", label: "Final Prescale" },
  ]);
}

async function loadL1PrescaleTable() {
  const button = $("#load-l1-prescale-table");
  const run = valueOf("#l1-table-run").trim();
  const params = new URLSearchParams();
  if (run) params.set("run", run);
  setBusy(true, "Loading L1 prescale table...");
  setButtonBusy(button, true, "Load prescale table", "Loading...");
  try {
    await waitForPaint();
    if ($("#l1-prescale-monitoring-only")?.checked !== false && !state.monitoringSeeds.length) {
      await loadMonitoringSeeds();
    }
    const payload = await fetchJson(`/api/l1-prescale-table?${params.toString()}`);
    state.l1PrescalePayload = payload;
    state.l1PrescaleRows = payload.rows || [];
    renderL1PrescaleContext(payload);
    renderL1PrescaleTable();
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "Load prescale table", "Loading...");
    setBusy(false);
  }
}

const projectionMetricConfig = {
  ratio: {
    label: "Ratio",
    hover: "ratio",
    digits: ".3f",
    referenceLine: () => 1,
  },
  rate: {
    label: "Measured rate [Hz]",
    hover: "rate",
    digits: ".3f",
    referenceLine: () => null,
  },
  expected_rate: {
    label: "Projection [Hz]",
    hover: "projection",
    digits: ".3f",
    referenceLine: () => null,
  },
  deviation: {
    label: "Deviation [Hz]",
    hover: "deviation",
    digits: ".3f",
    referenceLine: () => 0,
  },
  deviation_pct: {
    label: "Deviation [%]",
    hover: "deviation",
    digits: ".2f",
    referenceLine: () => 0,
  },
  lumi_ratio: {
    label: "Lumi ratio",
    hover: "lumi ratio",
    digits: ".3f",
    referenceLine: () => 1,
  },
};

function selectedProjectionMetric() {
  const key = $("#projection-y-metric")?.value || "ratio";
  return projectionMetricConfig[key] ? key : "ratio";
}

function renderDeviationChart(rows) {
  const metricKey = selectedProjectionMetric();
  const metric = projectionMetricConfig[metricKey];
  const validOnly = $("#projection-valid-only")?.checked !== false;
  const grouped = new Map();
  const yValues = [];
  const xValues = [];
  rows.forEach((row) => {
    if (!grouped.has(row.pathname)) grouped.set(row.pathname, []);
    grouped.get(row.pathname).push(row);
  });
  const traces = Array.from(grouped.entries())
    .map(([name, values]) => {
      const points = values
        .map((row) => ({
          ls: finiteNumber(row.lumisection),
          y: finiteNumber(row[metricKey]),
        }))
        .filter((point) => point.ls !== null && point.y !== null);
      if (validOnly && !points.length) return null;
      if (!points.length) return null;
      points.forEach((point) => {
        yValues.push(point.y);
        xValues.push(point.ls);
      });
      return {
        type: "scatter",
        mode: "lines+markers",
        name,
        x: points.map((point) => point.ls),
        y: points.map((point) => point.y),
        hovertemplate: `LS %{x}<br>${metric.hover} %{y:${metric.digits}}<extra>%{fullData.name}</extra>`,
      };
    })
    .filter(Boolean);
  const layout = plotLayout(metric.label);
  applyLumisectionDataRange(layout, xValues);
  if (metricKey === "ratio" || metricKey === "lumi_ratio") {
    applyRatioAxisRange(layout, yValues);
  }
  const referenceLine = metric.referenceLine();
  if (referenceLine !== null && Number.isFinite(referenceLine)) {
    layout.shapes = [{
      type: "line",
      xref: "paper",
      x0: 0,
      x1: 1,
      yref: "y",
      y0: referenceLine,
      y1: referenceLine,
      line: { color: "#8b949e", width: 1, dash: "dash" },
    }];
  }
  if (!traces.length) {
    layout.annotations = [{
      text: "No overlayable rows for this Y axis.",
      xref: "paper",
      yref: "paper",
      x: 0.5,
      y: 0.5,
      showarrow: false,
      font: { color: "#8b949e", size: 14 },
    }];
  }
  Plotly.react("deviation-chart", traces, layout, {
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
  });
  renderSuspiciousReport("#projection-suspicious-report", rows);
}

async function runProjection() {
  const button = $("#run-projection");
  setBusy(true, "Running projection...");
  setButtonBusy(button, true, "Run projection", "Running...");
  try {
    await waitForPaint();
    saveProjectionSettings();
    const comparisons = state.comparisons.length ? state.comparisons : [comparisonFromForm()];
    state.projectionResults = [];
    for (const comparison of comparisons) {
      setBusy(true, `Running ${comparisonLabel(comparison)}...`);
      let activeComparison = comparison;
      let data = await fetchJson("/api/projection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectionPayload(activeComparison)),
      });
      if (!activeComparison.include_unstable && !(data.latest || []).length) {
        activeComparison = { ...comparison, include_unstable: true };
        setBusy(true, `Retrying with unstable LS: ${comparisonLabel(activeComparison)}...`);
        data = await fetchJson("/api/projection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(projectionPayload(activeComparison)),
        });
      }
      activeComparison = resolvedComparisonFromContext(activeComparison, data.context);
      state.projectionResults.push({
        label: comparisonLabel(activeComparison),
        comparison: activeComparison,
        data,
      });
    }
    showProjectionResult(0);
    setPage("projection");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false, "Run projection", "Running...");
    setBusy(false);
  }
}

function setupNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      setPage(button.dataset.page);
      if (button.dataset.page === "monitoring" && !state.availableSeeds.length) {
        loadAvailableSeeds().catch((error) => toast(error.message));
      }
      if (button.dataset.page === "table" && !state.l1PrescaleRows.length) {
        loadL1PrescaleTable().catch((error) => toast(error.message));
      }
      if (button.dataset.page === "snapshot" && !state.rateSnapshot) {
        loadRateSnapshot().catch((error) => toast(error.message));
      }
    });
  });
}

function setupRefresh() {
  const schedule = () => {
    window.clearInterval(state.refreshTimer);
    const refreshInput = $("#refresh-seconds");
    const seconds = Math.max(5, Number(refreshInput?.value || 30));
    $("#refresh-label").textContent = `${seconds}s`;
    state.refreshTimer = window.setInterval(() => {
      refreshDashboard({ includeRates: false }).catch((error) => toast(error.message));
    }, seconds * 1000);
  };
  bind("#refresh-seconds", "change", schedule);
  bind("#refresh-now", "click", () => refreshDashboard({ includeRates: false }).catch((error) => toast(error.message)));
  bind("#topbar-refresh", "click", () => refreshDashboard({ includeRates: false }).catch((error) => toast(error.message)));
  bind("#load-dashboard-ratio", "click", () => {
    loadDashboardRatioPlot().catch((error) => toast(error.message));
  });
  bind("#dashboard-ratio-max-ls", "change", () => {
    saveDashboardReferenceSettings();
    if (state.dashboardRatioLoaded) {
      loadDashboardRatioPlot().catch((error) => toast(error.message));
    }
  });
  [
    "#dashboard-reference-run",
    "#dashboard-reference-ls-min",
    "#dashboard-reference-ls-max",
    "#dashboard-ratio-auto",
  ].forEach((selector) => {
    bind(selector, "input", saveDashboardReferenceSettings);
    bind(selector, "change", saveDashboardReferenceSettings);
  });
  bind("#load-rates", "click", async () => {
    const button = $("#load-rates");
    setBusy(true, "Loading seed rates...");
    setButtonBusy(button, true, "Load rates", "Loading...");
    try {
      await waitForPaint();
      await refreshDashboard({ includeRates: true });
    } catch (error) {
      toast(error.message);
    } finally {
      setButtonBusy(button, false, "Load rates", "Loading...");
      setBusy(false);
    }
  });
  bind("#refresh-exports", "click", () => loadExports().catch((error) => toast(error.message)));
  bind("#load-l1-prescale-table", "click", () => loadL1PrescaleTable().catch((error) => toast(error.message)));
  updateRateSnapshotLsControls();
  bind("#rate-snapshot-ls-mode", "change", () => {
    updateRateSnapshotLsControls();
  });
  bind("#rate-snapshot-reference-ls-mode", "change", () => {
    updateRateSnapshotLsControls();
  });
  bind("#load-rate-snapshot", "click", () => loadRateSnapshot().catch((error) => toast(error.message)));
  bind("#export-rate-snapshot-csv", "click", exportRateSnapshotCsv);
  bind("#l1-table-filter", "input", renderL1PrescaleTable);
  bind("#l1-prescale-monitoring-only", "change", renderL1PrescaleTable);
  bind("#l1-table-run", "keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadL1PrescaleTable().catch((error) => toast(error.message));
    }
  });
  bind("#ls-window", "change", () => refreshDashboard({ includeRates: false }).catch((error) => toast(error.message)));
  bind("#rate-field", "change", () => {
    refreshDashboard({ includeRates: false }).catch((error) => toast(error.message));
    if (state.rateSnapshot) {
      loadRateSnapshot().catch((error) => toast(error.message));
    }
  });
  bind("#trigger-file", "change", () => {
    updateSeedPresetState();
    saveProjectionSettings();
    refreshDashboard({ includeRates: false }).catch((error) => toast(error.message));
  });
  bind("#projection-y-metric", "change", () => {
    renderDeviationChart(state.projection?.series || []);
  });
  bind("#projection-valid-only", "change", () => {
    renderDeviationChart(state.projection?.series || []);
  });
  schedule();
}

function setupConfig(config) {
  setValue("#trigger-file", config.default_trigger_selection || config.default_trigger_file || "ALL");
  setValue("#ls-window", config.default_current_ls_window);
  setValue("#current-ls-window", config.default_current_ls_window);
  setValue("#refresh-seconds", config.default_refresh_seconds);
  const refreshLabel = $("#refresh-label");
  if (refreshLabel) refreshLabel.textContent = `${config.default_refresh_seconds}s`;
  const rateField = $("#rate-field");
  if (!rateField) return;
  rateField.innerHTML = Object.entries(config.rate_field_options)
    .map(([label, value]) => `<option value="${value}">${label}</option>`)
    .join("");
  rateField.value = config.default_rate_field;
  const configJson = $("#config-json");
  if (configJson) configJson.textContent = JSON.stringify(config, null, 2);
}

async function init() {
  setupSidebarToggle();
  setupNavigation();
  setupInfoTooltips();
  try {
    const config = await fetchJson("/api/config");
    state.config = config;
    setupConfig(config);
    await restoreProjectionSettings();
    await restoreDashboardReferenceSettings();
    setupSeedPresets();
    setupMonitoringSeeds();
    setupProjectionControls();
    setupRefresh();
    refreshDashboard({ includeRates: false }).catch((error) => toast(error.message));
    loadExports().catch((error) => toast(error.message));
    loadMonitoringSeeds().catch((error) => toast(error.message));
  } catch (error) {
    toast(error.message);
  }
  bind("#run-projection", "click", runProjection);
  bind("#run-rate-plots", "click", runRatePlots);
  bind("#rate-sheet-layout", "change", () => {
    state.ratePlotSheetCache = null;
  });
  bind("#download-rate-png-sheet", "click", downloadRatePlotPngSheets);
  bind("#download-rate-pdf-sheet", "click", downloadRatePlotPdfSheet);
  bind("#clear-state", "click", () => {
    state.projection = null;
    state.projectionResults = [];
    state.activeProjectionIndex = 0;
    renderContext({});
    renderExportLinks(null);
    renderProjectionTabs();
    renderProjectionLatest([]);
    Plotly.purge("deviation-chart");
  });
  bind("#export-latest-csv", "click", () => saveProjectionCsv("latest"));
  bind("#export-full-csv", "click", () => saveProjectionCsv("full"));
}

init();
