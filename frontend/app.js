/**
 * app.js — DataIQ front-end logic
 * Communicates with Flask server at /api/* endpoints,
 * or falls back to pure browser-side simple ops if no server.
 */

"use strict";

// ── State ────────────────────────────────────────────────────────────────
const state = {
  sessionId: null,
  datasetLoaded: false,
  datasetName: "",
  schema: null,
  history: [],
  busy: false,
};

// ── DOM refs ─────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const uploadZone       = $("uploadZone");
const fileInput        = $("fileInput");
const datasetCard      = $("datasetCard");
const datasetName      = $("datasetName");
const datasetMeta      = $("datasetMeta");
const clearDatasetBtn  = $("clearDataset");
const schemaSection    = $("schemaSection");
const schemaToggle     = $("schemaToggle");
const schemaPanel      = $("schemaPanel");
const schemaContent    = $("schemaContent");
const suggestionsSection = $("suggestionsSection");
const suggestionsList  = $("suggestionsList");
const historyList      = $("historyList");
const clearHistoryBtn  = $("clearHistory");
const welcomeScreen    = $("welcomeScreen");
const messages         = $("messages");
const queryInput       = $("queryInput");
const sendBtn          = $("sendBtn");
const statusPill       = $("statusPill");
const statusDot        = statusPill.querySelector(".status-dot");
const statusText       = $("statusText");
const topbarDatasetName= $("topbarDatasetName");
const loadingOverlay   = $("loadingOverlay");
const loaderText       = $("loaderText");
const toastContainer   = $("toastContainer");
const sidebar          = $("sidebar");
const sidebarToggle    = $("sidebarToggle");
const sidebarToggleMobile = $("sidebarToggleMobile");
const sidebarExpandDesktopBtn = $("sidebarExpandDesktopBtn");
const themeToggleBtn   = $("themeToggleBtn");
const themeText        = $("themeText");

// ── API base (works when Flask server is running) ─────────────────────────
const API = "http://127.0.0.1:5000/api";

// ── Utilities ────────────────────────────────────────────────────────────
function toast(msg, type = "info", duration = 3500) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function setStatus(mode, text) {
  statusDot.className = `status-dot ${mode}`;
  statusText.textContent = text;
}

function showLoader(text = "Processing…") {
  loaderText.textContent = text;
  loadingOverlay.classList.remove("hidden");
}

function hideLoader() {
  loadingOverlay.classList.add("hidden");
}

function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

// ── Marked + highlight.js config ─────────────────────────────────────────
if (window.marked) {
  marked.setOptions({
    highlight: (code, lang) => {
      if (window.hljs && lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return code;
    },
    breaks: true,
    gfm: true,
  });
}

function renderMarkdown(md) {
  if (!window.marked) return `<pre>${md}</pre>`;
  return marked.parse(md || "");
}

// Add copy buttons to code blocks inside an element
function addCopyButtons(container) {
  container.querySelectorAll("pre").forEach((pre) => {
    if (pre.querySelector(".copy-btn")) return;
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "Copy";
    btn.addEventListener("click", () => {
      const code = pre.querySelector("code");
      navigator.clipboard.writeText(code ? code.innerText : pre.innerText).then(() => {
        btn.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 1800);
      });
    });
    pre.style.position = "relative";
    pre.appendChild(btn);
  });
}

// ── Message rendering ─────────────────────────────────────────────────────
function appendUserMessage(query) {
  const div = document.createElement("div");
  div.className = "message msg-user";
  div.innerHTML = `<div class="msg-user-bubble">${escapeHtml(query)}</div>`;
  messages.appendChild(div);
  scrollToBottom();
}

function appendThinking() {
  const div = document.createElement("div");
  div.className = "message msg-agent msg-thinking";
  div.id = "thinkingBubble";
  div.innerHTML = `
    <div class="msg-agent-header">
      <div class="agent-avatar">DQ</div>
      <span class="agent-name">DataIQ</span>
    </div>
    <div class="msg-agent-body">
      <span style="margin-right:8px">Analyzing</span>
      <span class="thinking-dots"><span></span><span></span><span></span></span>
    </div>`;
  messages.appendChild(div);
  scrollToBottom();
  return div;
}

function removeThinking() {
  const el = $("thinkingBubble");
  if (el) el.remove();
}

function appendAgentMessage(mdText, isError = false) {
  const div = document.createElement("div");
  div.className = "message msg-agent";
  const bodyClass = isError ? "msg-agent-body" : "msg-agent-body";
  div.innerHTML = `
    <div class="msg-agent-header">
      <div class="agent-avatar">DQ</div>
      <span class="agent-name">DataIQ</span>
    </div>
    <div class="${bodyClass}">${renderMarkdown(mdText)}</div>`;
  messages.appendChild(div);
  addCopyButtons(div);
  if (window.hljs) div.querySelectorAll("pre code").forEach((b) => hljs.highlightElement(b));
  scrollToBottom();
}

function scrollToBottom() {
  const area = document.querySelector(".chat-area");
  area.scrollTop = area.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── File upload ───────────────────────────────────────────────────────────
uploadZone.addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); });

uploadZone.addEventListener("dragover", (e) => { e.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
  const allowed = [".csv", ".tsv", ".txt", ".xls", ".xlsx", ".xlsm"];
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(ext)) {
    toast("Unsupported file type. Use CSV or Excel.", "error");
    return;
  }

  showLoader("Loading dataset…");
  setStatus("busy", "Loading…");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const resp = await fetch(`${API}/load`, { method: "POST", body: formData });
    const data = await resp.json();

    if (!resp.ok || data.error) throw new Error(data.error || "Upload failed");

    state.sessionId = data.session_id;
    state.datasetLoaded = true;
    state.datasetName = file.name;
    state.schema = data.schema;

    updateDatasetUI(file.name, data.schema);
    enableInput();
    welcomeScreen.classList.add("hidden");
    setStatus("ready", "Ready");
    toast(`Loaded ${file.name}`, "success");
    appendAgentMessage(buildSchemaMessage(file.name, data.schema));
  } catch (err) {
    setStatus("error", "Load failed");
    toast("Could not load file: " + err.message, "error");
    console.error(err);
  } finally {
    hideLoader();
    fileInput.value = "";
  }
}

function buildSchemaMessage(name, schema) {
  const rows = schema.shape?.rows?.toLocaleString() ?? "?";
  const cols = schema.shape?.cols ?? "?";
  let md = `### ✅ Dataset Loaded: \`${name}\`\n\n`;
  md += `**${rows} rows × ${cols} columns**\n\n`;
  md += `| Column | Type | Nulls |\n|--------|------|-------|\n`;
  const dtypes = schema.dtypes || {};
  const nulls  = schema.null_counts || {};
  Object.entries(dtypes).forEach(([col, dtype]) => {
    const n = nulls[col] ? `⚠ ${nulls[col].toLocaleString()}` : "—";
    md += `| \`${col}\` | ${dtype} | ${n} |\n`;
  });
  md += `\nYou can now ask questions about this data. Try the suggestions in the sidebar!`;
  return md;
}

function updateDatasetUI(name, schema) {
  datasetName.textContent = name;
  const rows = schema.shape?.rows?.toLocaleString() ?? "?";
  const cols = schema.shape?.cols ?? "?";
  datasetMeta.textContent = `${rows} rows · ${cols} cols`;
  datasetCard.classList.remove("hidden");
  topbarDatasetName.textContent = name;
  if (exportNotebookBtn) exportNotebookBtn.style.display = "inline-flex";

  // Schema panel
  schemaSection.style.display = "";
  const dtypes = schema.dtypes || {};
  const nulls  = schema.null_counts || {};
  schemaContent.innerHTML = Object.entries(dtypes).map(([col, dtype]) => {
    const nullNote = nulls[col] ? `<span class="schema-col-null">[${nulls[col]} nulls]</span>` : "";
    return `<div class="schema-col"><span class="schema-col-name">${col}</span><span class="schema-col-type">${dtype}</span>${nullNote}</div>`;
  }).join("");

  // Suggestions
  buildSuggestions(schema);
}

function buildSuggestions(schema) {
  const numCols = schema.numeric_cols || [];
  const catCols = schema.categorical_cols || [];
  const suggestions = [
    "How many rows are in the dataset?",
    "Describe the dataset with summary statistics",
    numCols[0] ? `What is the total sum of ${numCols[0]}?` : null,
    numCols[0] ? `What is the average ${numCols[0]}?` : null,
    numCols[0] ? `Show me the top 10 rows by ${numCols[0]}` : null,
    catCols[0] && numCols[0] ? `What is the total ${numCols[0]} grouped by ${catCols[0]}?` : null,
  ].filter(Boolean).slice(0, 5);

  suggestionsSection.style.display = "";
  suggestionsList.innerHTML = suggestions.map(s =>
    `<button class="suggestion-btn" data-q="${escapeHtml(s)}">${escapeHtml(s)}</button>`
  ).join("");

  suggestionsList.querySelectorAll(".suggestion-btn").forEach(btn => {
    btn.addEventListener("click", () => submitQuery(btn.dataset.q));
  });
}

// ── Clear dataset ─────────────────────────────────────────────────────────
clearDatasetBtn.addEventListener("click", async () => {
  if (state.sessionId) {
    try { await fetch(`${API}/reset`, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({session_id: state.sessionId}) }); } catch (_) {}
  }
  state.sessionId = null;
  state.datasetLoaded = false;
  state.schema = null;
  state.datasetName = "";
  messages.innerHTML = "";
  welcomeScreen.classList.remove("hidden");
  datasetCard.classList.add("hidden");
  schemaSection.style.display = "none";
  suggestionsSection.style.display = "none";
  topbarDatasetName.textContent = "No dataset loaded";
  if (exportNotebookBtn) exportNotebookBtn.style.display = "none";
  enableInput();
  setStatus("idle", "Ready");
  toast("Dataset cleared", "info");
});

// ── Schema toggle ─────────────────────────────────────────────────────────
schemaToggle.addEventListener("click", () => {
  schemaPanel.classList.toggle("hidden");
  schemaToggle.textContent = schemaPanel.classList.contains("hidden") ? "Show" : "Hide";
});

// ── History ───────────────────────────────────────────────────────────────
function addToHistory(query) {
  state.history.unshift(query);
  const empty = historyList.querySelector(".empty-hint");
  if (empty) empty.remove();
  const item = document.createElement("div");
  item.className = "history-item";
  item.title = query;
  item.textContent = query;
  item.addEventListener("click", () => submitQuery(query));
  historyList.insertBefore(item, historyList.firstChild);
  // Keep max 20
  while (historyList.children.length > 20) historyList.lastChild.remove();
}

clearHistoryBtn.addEventListener("click", () => {
  historyList.innerHTML = `<p class="empty-hint">No questions yet.</p>`;
  state.history = [];
});

// ── Query submission ──────────────────────────────────────────────────────
function enableInput() {
  queryInput.disabled = false;
  sendBtn.disabled = false;
}

function disableInput() {
  queryInput.disabled = true;
  sendBtn.disabled = true;
}

sendBtn.addEventListener("click", () => {
  const q = queryInput.value.trim();
  if (q) submitQuery(q);
});

queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const q = queryInput.value.trim();
    if (q) submitQuery(q);
  }
});

queryInput.addEventListener("input", () => autoGrow(queryInput));

// Example query buttons on welcome screen
document.querySelectorAll(".example-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    submitQuery(btn.dataset.q);
  });
});

async function submitQuery(query) {
  if (state.busy) return;

  // Auto-load sample dataset if user hasn't loaded any dataset yet
  if (!state.datasetLoaded) {
    showLoader("Loading sample dataset...");
    setStatus("busy", "Loading dataset...");
    try {
      const resp = await fetch(`${API}/load_sample`, { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(data.error || "Failed to load sample dataset");
      state.sessionId = data.session_id;
      state.datasetLoaded = true;
      state.datasetName = data.filename || "sample_data.csv";
      state.schema = data.schema;
      updateDatasetUI(state.datasetName, data.schema);
      welcomeScreen.classList.add("hidden");
      toast("Auto-loaded sample dataset!", "info");
      appendAgentMessage(buildSchemaMessage(state.datasetName, data.schema));
    } catch (err) {
      setStatus("error", "Failed");
      toast("Could not load sample dataset: " + err.message, "error");
      hideLoader();
      return;
    } finally {
      hideLoader();
    }
  }

  welcomeScreen.classList.add("hidden");
  state.busy = true;
  queryInput.value = "";
  autoGrow(queryInput);
  disableInput();
  setStatus("busy", "Computing…");

  appendUserMessage(query);
  addToHistory(query);
  const thinkingEl = appendThinking();

  try {
    const resp = await fetch(`${API}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, query }),
    });
    const data = await resp.json();

    removeThinking();
    if (!resp.ok || data.error) {
      appendAgentMessage(`### ❌ Error\n\n${data.error || "Unknown error"}`, true);
      setStatus("error", "Error");
    } else {
      appendAgentMessage(data.answer);
      setStatus("ready", "Ready");
    }
  } catch (err) {
    removeThinking();
    appendAgentMessage(`### ❌ Connection Error\n\nCould not reach the DataIQ server.\n\nMake sure \`server.py\` is running:\n\`\`\`\npython server.py\n\`\`\`\n\n_Error: ${err.message}_`, true);
    setStatus("error", "Offline");
  } finally {
    state.busy = false;
    enableInput();
    queryInput.focus();
  }
}

// ── Sidebar toggle ────────────────────────────────────────────────────────
function toggleSidebar() {
  sidebar.classList.toggle("collapsed");
  const isCollapsed = sidebar.classList.contains("collapsed");
  if (sidebarExpandDesktopBtn) {
    sidebarExpandDesktopBtn.style.display = isCollapsed ? "inline-flex" : "none";
  }
}

if (sidebarToggle) sidebarToggle.addEventListener("click", toggleSidebar);
if (sidebarExpandDesktopBtn) sidebarExpandDesktopBtn.addEventListener("click", toggleSidebar);
if (sidebarToggleMobile) sidebarToggleMobile.addEventListener("click", () => sidebar.classList.toggle("mobile-open"));

// ── Settings Modal ────────────────────────────────────────────────────────

const settingsModal      = $("settingsModal");
const openSettingsBtn    = $("openSettingsBtn");
const closeSettingsBtn   = $("closeSettingsBtn");
const closeSettingsBtn2  = $("closeSettingsBtn2");
const saveSettingsBtn    = $("saveSettingsBtn");
const apiKeyInput        = $("apiKeyInput");
const modelSelect        = $("modelSelect");
const toggleKeyVisibility= $("toggleKeyVisibility");
const keyStatusDot       = $("keyStatusDot");
const keyBanner          = $("keyBanner");
const keyBannerIcon      = $("keyBannerIcon");
const keyBannerText      = $("keyBannerText");

// In-memory API key store (never persisted to localStorage)
let _apiKey   = "";
let _llmModel = "gpt-4o-mini";
let _keyConnected = false;

function openSettings() {
  apiKeyInput.value = _apiKey ? "•".repeat(Math.min(_apiKey.length, 32)) : "";
  modelSelect.value = _llmModel;
  _updateBanner(_keyConnected);
  settingsModal.classList.remove("hidden");
  setTimeout(() => apiKeyInput.focus(), 100);
}
function closeSettings() { settingsModal.classList.add("hidden"); }

openSettingsBtn.addEventListener("click", openSettings);
closeSettingsBtn.addEventListener("click", closeSettings);
closeSettingsBtn2.addEventListener("click", closeSettings);
settingsModal.addEventListener("click", (e) => { if (e.target === settingsModal) closeSettings(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSettings(); });

// Show/hide password
toggleKeyVisibility.addEventListener("click", () => {
  if (apiKeyInput.type === "password") {
    apiKeyInput.type = "text";
    toggleKeyVisibility.textContent = "🙈";
  } else {
    apiKeyInput.type = "password";
    toggleKeyVisibility.textContent = "👁";
  }
});

// Clear masked value on focus so user can type fresh key
apiKeyInput.addEventListener("focus", () => {
  if (apiKeyInput.value.includes("•")) apiKeyInput.value = "";
});

function _updateBanner(connected) {
  if (connected) {
    keyBanner.classList.add("ok");
    keyBannerIcon.textContent = "✅";
    keyBannerText.textContent = `Connected: ${_llmModel} — complex queries are enabled.`;
    keyStatusDot.classList.add("connected");
  } else {
    keyBanner.classList.remove("ok");
    keyBannerIcon.textContent = "🔑";
    keyBannerText.textContent = "No API key configured — complex queries use simple pandas ops only.";
    keyStatusDot.classList.remove("connected");
  }
}

function _updateLlmBadge(llmName) {
  const badge = $("llmBadge");
  const nameEl = $("llmName");
  if (llmName && !llmName.startsWith("None")) {
    badge.classList.remove("hidden");
    nameEl.textContent = llmName;
  } else {
    badge.classList.add("hidden");
  }
}

saveSettingsBtn.addEventListener("click", async () => {
  const rawKey = apiKeyInput.value.trim();
  const model  = modelSelect.value;

  // If user typed dots (masked), keep existing key
  const key = rawKey.includes("•") ? _apiKey : rawKey;

  if (!key || !key.startsWith("sk-")) {
    toast("API key must start with 'sk-'", "error");
    apiKeyInput.focus();
    return;
  }

  saveSettingsBtn.disabled = true;
  saveSettingsBtn.textContent = "Connecting…";

  try {
    const resp = await fetch(`${API}/configure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key, model, session_id: state.sessionId }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "Failed");

    _apiKey   = key;
    _llmModel = model;
    _keyConnected = true;

    _updateBanner(true);
    _updateLlmBadge(data.llm);
    toast(`Connected: ${data.llm}`, "success");
    closeSettings();
  } catch (err) {
    toast("Connection failed: " + err.message, "error");
  } finally {
    saveSettingsBtn.disabled = false;
    saveSettingsBtn.textContent = "Save & Connect";
  }
});

// Inject key header into every API call that needs it
const _origFetch = window.fetch;
window.fetch = function(url, options = {}) {
  if (_apiKey && typeof url === "string" && url.includes("/api/")) {
    options.headers = options.headers || {};
    options.headers["X-OpenAI-Key"] = _apiKey;
  }
  return _origFetch(url, options);
};

// Check server key status on load
(async () => {
  try {
    const r  = await _origFetch(`${API}/health`);
    const d  = await r.json();
    if (d.key_configured) {
      _keyConnected = true;
      _llmModel = "gpt-4o-mini";
      _updateBanner(true);
      _updateLlmBadge(d.llm);
    }
  } catch (_) {}
})();

// ── Theme Switcher ────────────────────────────────────────────────────────
function getInitialTheme() {
  const saved = localStorage.getItem("dataiq_theme");
  if (saved) return saved;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (themeText) {
    themeText.textContent = theme === "dark" ? "Dark" : "Light";
  }
  localStorage.setItem("dataiq_theme", theme);
}

applyTheme(getInitialTheme());

if (themeToggleBtn) {
  themeToggleBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    toast(`Switched to ${next} mode`, "info", 2000);
  });
}

// ── Init ──────────────────────────────────────────────────────────────────
setStatus("idle", "Ready");
enableInput();

// Load Sample button on welcome screen
const loadSampleBtn = $("loadSampleBtn");
if (loadSampleBtn) {
  loadSampleBtn.addEventListener("click", async () => {
    showLoader("Loading sample dataset...");
    setStatus("busy", "Loading...");
    try {
      const resp = await fetch(`${API}/load_sample`, { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
      const data = await resp.json();
      if (!resp.ok || data.error) throw new Error(data.error || "Failed");
      state.sessionId = data.session_id;
      state.datasetLoaded = true;
      state.datasetName = data.filename || "sample_data.csv";
      state.schema = data.schema;
      updateDatasetUI(state.datasetName, data.schema);
      enableInput();
      welcomeScreen.classList.add("hidden");
      setStatus("ready", "Ready");
      toast("Sample dataset loaded!", "success");
      appendAgentMessage(buildSchemaMessage(state.datasetName, data.schema));
    } catch (err) {
      setStatus("error", "Failed");
      toast("Could not load sample: " + err.message, "error");
    } finally {
      hideLoader();
    }
  });
}

// ── Export Notebook (.ipynb) ──────────────────────────────────────────────
const exportNotebookBtn = $("exportNotebookBtn");
if (exportNotebookBtn) {
  exportNotebookBtn.addEventListener("click", async () => {
    if (!state.sessionId) { toast("No active session", "info"); return; }
    showLoader("Exporting Jupyter Notebook...");
    try {
      const resp = await fetch(`${API}/export/notebook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      if (!resp.ok) throw new Error("Export failed");
      const blob = await resp.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "dataiq_analysis.ipynb";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast("Jupyter Notebook downloaded!", "success");
    } catch (err) {
      toast("Export failed: " + err.message, "error");
    } finally {
      hideLoader();
    }
  });
}

// Show export notebook button when dataset UI updates
const _origUpdateDatasetUI = updateDatasetUI;
updateDatasetUI = function(name, schema) {
  _origUpdateDatasetUI(name, schema);
  if (exportNotebookBtn) exportNotebookBtn.style.display = "inline-flex";
};

// ── SQLite History Modal ──────────────────────────────────────────────────
const historyModal        = $("historyModal");
const openHistoryModalBtn = $("openHistoryModalBtn");
const closeHistoryBtn     = $("closeHistoryBtn");
const closeHistoryBtn2    = $("closeHistoryBtn2");
const historySearchBtn    = $("historySearchBtn");
const historySearchInput  = $("historySearchInput");
const historyModalList    = $("historyModalList");

async function loadHistoryModal(keyword = "") {
  historyModalList.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem">Loading SQLite history...</p>`;
  try {
    const url = keyword ? `${API}/history?q=${encodeURIComponent(keyword)}` : `${API}/history?limit=30`;
    const resp = await fetch(url);
    const data = await resp.json();
    if (!data.history || data.history.length === 0) {
      historyModalList.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem">No history entries found.</p>`;
      return;
    }
    historyModalList.innerHTML = data.history.map(item => `
      <div class="modal-history-card" data-query="${escapeHtml(item.query || '')}" style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:6px;cursor:pointer;transition:all 0.2s ease;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.75rem;color:var(--text-muted)">
          <span>🕒 ${item.created_at || 'Recent'} · <strong style="color:var(--accent-1)">${item.duration_ms || 0} ms</strong></span>
          <span class="btn-chip" style="font-size:0.68rem;background:var(--accent-g-subtle);color:var(--accent-1);border-color:var(--accent-glow)">${item.query_type || 'query'}</span>
        </div>
        <div style="font-weight:700;font-size:0.88rem;color:var(--text-primary)">${escapeHtml(item.query || '')}</div>
        <div style="font-size:0.8rem;color:var(--text-secondary);max-height:80px;overflow:hidden;text-overflow:ellipsis;line-height:1.4">${escapeHtml(item.answer_text ? item.answer_text.substring(0, 200) + '...' : '')}</div>
      </div>
    `).join("");

    historyModalList.querySelectorAll(".modal-history-card").forEach(card => {
      card.addEventListener("click", () => {
        const q = card.dataset.query;
        if (q) {
          historyModal.classList.add("hidden");
          if (state.datasetLoaded) {
            submitQuery(q);
          } else {
            toast("Load a dataset first to replay queries!", "info");
          }
        }
      });
    });
  } catch (err) {
    historyModalList.innerHTML = `<p style="color:var(--red);font-size:0.85rem">Failed to load history: ${err.message}</p>`;
  }
}

if (openHistoryModalBtn) {
  openHistoryModalBtn.addEventListener("click", () => {
    historyModal.classList.remove("hidden");
    loadHistoryModal();
  });
}
if (closeHistoryBtn) closeHistoryBtn.addEventListener("click", () => historyModal.classList.add("hidden"));
if (closeHistoryBtn2) closeHistoryBtn2.addEventListener("click", () => historyModal.classList.add("hidden"));
if (historySearchBtn) historySearchBtn.addEventListener("click", () => loadHistoryModal(historySearchInput.value.trim()));
if (historySearchInput) {
  historySearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadHistoryModal(historySearchInput.value.trim());
  });
}

// ── Sample Datasets Modal Controller ─────────────────────────────────────
const sampleDatasetsModal      = $("sampleDatasetsModal");
const openSampleModalBtn        = $("openSampleModalBtn");
const openSampleModalWelcomeBtn = $("openSampleModalWelcomeBtn");
const closeSampleModalBtn       = $("closeSampleModalBtn");
const closeSampleModalBtn2      = $("closeSampleModalBtn2");
const sampleDatasetsGrid        = $("sampleDatasetsGrid");

const FALLBACK_SAMPLE_DATASETS = [
  { filename: "01_sales_performance.csv", title: "Sales Performance & Revenue", type: "CSV", icon: "📊", description: "25 retail sales transactions with order status, category, units, price, and total revenue.", questions: ["Total revenue by region?", "Which category has highest sales?", "Show top 5 orders by revenue"] },
  { filename: "02_employee_payroll.csv", title: "HR & Employee Payroll", type: "CSV", icon: "👥", description: "Employee demographics, departments, salary, bonus %, performance score, and remote status.", questions: ["Average salary by department?", "How many remote employees?", "Highest bonus percentage?"] },
  { filename: "03_ecommerce_orders.csv", title: "E-Commerce Order Fulfillment", type: "CSV", icon: "🛒", description: "Customer order data with countries, payment methods, shipping fees, and fulfillment status.", questions: ["Total orders by country?", "Most popular payment method?", "Average order subtotal?"] },
  { filename: "04_financial_transactions.csv", title: "Banking & Financial Audit", type: "CSV", icon: "💳", description: "Financial ledger of wire transfers, payroll, vendor payments, amounts, and risk ratings.", questions: ["Sum of positive transactions?", "Count of high risk transactions?", "Total vendor payments?"] },
  { filename: "05_customer_churn_analytics.csv", title: "SaaS Customer Churn", type: "CSV", icon: "📈", description: "Subscription plans, tenure months, monthly fees, support tickets, and churn flags.", questions: ["Churn rate by subscription plan?", "Average tenure of churned customers?", "Monthly revenue by plan?"] },
  { filename: "06_real_estate_listings.xlsx", title: "Real Estate Property Market", type: "Excel", icon: "🏠", description: "Housing listings with city, property type, bedrooms, sq ft, year built, and listing prices.", questions: ["Average price per square foot by city?", "Highest price property details?", "Average bedrooms per city?"] },
  { filename: "07_marketing_campaigns.xlsx", title: "Digital Marketing Campaigns ROI", type: "Excel", icon: "🎯", description: "Ad campaign performance metrics: budget, impressions, clicks, conversions, and revenue.", questions: ["Channel with highest ROI/Revenue?", "Total budget spent across channels?", "Average CTR by channel?"] },
  { filename: "08_student_academic_performance.xlsx", title: "Student Academic Scores", type: "Excel", icon: "🎓", description: "Student grades in Math, Science, English, attendance percentage, study hours, and GPA.", questions: ["Average GPA by grade level?", "Correlation between study hours and GPA?", "Top 3 students by math score"] },
  { filename: "09_inventory_warehouse_stock.xlsx", title: "Warehouse Inventory Stock", type: "Excel", icon: "📦", description: "SKU catalog, stock quantities, reorder thresholds, unit costs, and warehouse zones.", questions: ["Which items need reordering?", "Total inventory valuation?", "Stock quantity by zone?"] },
  { filename: "10_healthcare_patient_records.xlsx", title: "Healthcare & Patient Billing", type: "Excel", icon: "🏥", description: "Hospital patient admissions, age, blood type, diagnosis, stay duration, and billing amounts.", questions: ["Average hospital stay by diagnosis?", "Total billing amount by diagnosis?", "Patient age distribution?"] }
];

async function renderSampleDatasetsGrid() {
  if (!sampleDatasetsGrid) return;
  sampleDatasetsGrid.innerHTML = `<p style="color:var(--text-muted);font-size:0.85rem">Loading datasets library...</p>`;
  let datasets = FALLBACK_SAMPLE_DATASETS;
  try {
    const resp = await fetch(`${API}/sample_datasets`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.datasets && data.datasets.length > 0) datasets = data.datasets;
    }
  } catch (_) {}

  sampleDatasetsGrid.innerHTML = datasets.map(item => `
    <div style="background:var(--bg-elevated);border:1px solid var(--border);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px;box-shadow:var(--shadow-sm);transition:all 0.2s ease" class="sample-dataset-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:1.6rem">${item.icon || '📄'}</span>
          <div>
            <div style="font-weight:700;font-size:0.92rem;color:var(--text-primary)">${escapeHtml(item.title)}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);font-family:var(--mono)">${escapeHtml(item.filename)}</div>
          </div>
        </div>
        <span class="btn-chip" style="font-size:0.7rem;font-weight:700;background:${item.type === 'Excel' ? 'rgba(16,185,129,0.15)' : 'var(--accent-g-subtle)'};color:${item.type === 'Excel' ? '#10b981' : 'var(--accent-1)'};border-color:${item.type === 'Excel' ? 'rgba(16,185,129,0.3)' : 'var(--accent-glow)'}">${item.type}</span>
      </div>
      <p style="font-size:0.8rem;color:var(--text-secondary);margin:0;line-height:1.4">${escapeHtml(item.description)}</p>
      <div style="display:flex;flex-direction:column;gap:4px">
        <span style="font-size:0.72rem;font-weight:600;color:var(--text-muted)">Suggested questions:</span>
        <div style="display:flex;flex-wrap:wrap;gap:4px">
          ${(item.questions || []).map(q => `<span style="font-size:0.7rem;background:var(--bg-glass);border:1px solid var(--border);padding:2px 6px;border-radius:4px;color:var(--text-secondary)">${escapeHtml(q)}</span>`).join('')}
        </div>
      </div>
      <button class="send-btn load-sample-file-btn" data-file="${escapeHtml(item.filename)}" style="margin-top:auto;width:100%;padding:8px 12px;font-size:0.8rem;border-radius:8px;background:var(--accent-gradient)">
        Load Dataset
      </button>
    </div>
  `).join("");

  sampleDatasetsGrid.querySelectorAll(".load-sample-file-btn").forEach(btn => {
    btn.addEventListener("click", () => loadSampleFile(btn.dataset.file));
  });
}

async function loadSampleFile(filename) {
  if (sampleDatasetsModal) sampleDatasetsModal.classList.add("hidden");
  showLoader(`Loading ${filename}...`);
  setStatus("busy", "Loading...");
  try {
    const resp = await fetch(`${API}/load_sample_file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "Failed");

    state.sessionId = data.session_id;
    state.datasetLoaded = true;
    state.datasetName = data.filename || filename;
    state.schema = data.schema;
    updateDatasetUI(state.datasetName, data.schema);

    if (data.questions && data.questions.length > 0) {
      renderSuggestions(data.questions);
    }

    enableInput();
    welcomeScreen.classList.add("hidden");
    setStatus("ready", "Ready");
    toast(`Loaded ${state.datasetName}!`, "success");
    appendAgentMessage(buildSchemaMessage(state.datasetName, data.schema));
  } catch (err) {
    setStatus("error", "Failed");
    toast("Could not load dataset: " + err.message, "error");
  } finally {
    hideLoader();
  }
}

if (openSampleModalBtn) {
  openSampleModalBtn.addEventListener("click", () => {
    const modal = $("sampleDatasetsModal");
    if (modal) modal.classList.remove("hidden");
    renderSampleDatasetsGrid();
  });
}
if (openSampleModalWelcomeBtn) {
  openSampleModalWelcomeBtn.addEventListener("click", () => {
    const modal = $("sampleDatasetsModal");
    if (modal) modal.classList.remove("hidden");
    renderSampleDatasetsGrid();
  });
}
if (closeSampleModalBtn) closeSampleModalBtn.addEventListener("click", () => {
  const modal = $("sampleDatasetsModal");
  if (modal) modal.classList.add("hidden");
});
if (closeSampleModalBtn2) closeSampleModalBtn2.addEventListener("click", () => {
  const modal = $("sampleDatasetsModal");
  if (modal) modal.classList.add("hidden");
});
