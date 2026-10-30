/* Shared helpers: DOM, API calls, formatting, backend registry. */

const $ = s => document.querySelector(s);

// The dashboard is shared by several people on one machine. The browser keeps
// the current person's email and sends it with every request; the backend uses
// it to separate pushed mail. This is identification, not authentication.
const CURRENT_USER_KEY = "inbox-sorter.currentUser";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

let BACKENDS = [];
let BACKEND_LABELS = {};
let BACKEND_DEFAULT = null;

function normalizeUser(value) {
  return String(value || "").trim().toLowerCase();
}

function currentUser() {
  return normalizeUser(
    document.body?.dataset.currentUser || ""
  );
}

function userInitials(email) {
  const local = email.split("@")[0] || "";
  const parts = local.split(/[._-]+/).filter(Boolean);
  const initials = parts.length > 1 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return (initials || "?").toUpperCase();
}

function renderUserChip() {
  const chip = $("#user-chip");
  if (!chip) return;
  const email = currentUser();
  chip.hidden = !email;
  if (!email) return;
  $("#user-avatar").textContent = userInitials(email);
  $("#user-email").textContent = email;
  chip.title = `Signed in as ${email}. Click to switch user.`;
}

function openUserGate() {
  const gate = $("#user-gate");
  if (!gate) return;
  $("#user-input").value = currentUser();
  $("#user-gate-error").hidden = true;
  if (typeof gate.showModal === "function") {
    if (!gate.open) gate.showModal();
  } else {
    gate.setAttribute("open", "");
  }
  $("#user-input").focus();
}

function initUserGate() {
  // Authentication is already handled by the server.
  const gate = $("#user-gate");

  if (gate) {
    if (gate.open && typeof gate.close === "function") {
      gate.close();
    }
    gate.remove();
  }

  // The old manually entered email is no longer used.
  try {
    localStorage.removeItem("inbox-sorter.currentUser");
  } catch {
    // Continue even if storage access is blocked.
  }

  renderUserChip();

  const chip = $("#user-chip");

  if (chip) {
    chip.title = `Signed in as ${currentUser()}`;

    if (chip instanceof HTMLButtonElement) {
      chip.disabled = true;
    }

    chip.querySelector(".user-switch")?.remove();
  }
}

function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function notice(text, isError) {
  const box = $("#notice");
  if (!box) return;
  box.replaceChildren();
  if (text) {
    box.append(el("div", { class: "msg" + (isError ? " err" : ""), role: isError ? "alert" : "status" }, text));
  }
}

async function api(path, body, { signal, timeoutMs = 30000 } = {}) {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeoutMs);
  const forwardAbort = () => ctrl.abort();
  if (signal) {
    if (signal.aborted) ctrl.abort();
    else signal.addEventListener("abort", forwardAbort, { once: true });
  }
  try {
    const headers = { "Content-Type": "application/json" };
    const r = await fetch(path, {
      method: body ? "POST" : "GET",
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "Request failed (" + r.status + ")");
    return j;
  } catch (e) {
    if (timedOut) {
      const err = new Error("Request timed out. The backend may still be loading — please try again.");
      err.timedOut = true;
      throw err;
    }
    throw e;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", forwardAbort);
  }
}

function setProgress(done, total, text) {
  $("#progress > div").style.width = (total ? done / total * 100 : 0) + "%";
  if (text) $("#count-label").textContent = text;
}

function initMailboxForm() {
  // Mail arrives only through the Power Automate webhook, so there is no source
  // or credential to choose; the hidden #provider keeps the request payloads
  // unchanged for the backend.
  const windowSelect = $("#window");
  windowSelect.addEventListener("change", () => {
    $("#f-custom-range").hidden = windowSelect.value !== "custom";
  });
  $("#f-custom-range").hidden = windowSelect.value !== "custom";
}

function readCredentials() {
  const provider = $("#provider")?.value || "outlook";
  const credentials = provider === "outlook"
    ? { token: ($("#token")?.value || "").trim() }
    : {};
  return { provider, credentials };
}

function classifyEmail(email, backend, signal) {
  return api("/api/classify", { email, backend }, { signal, timeoutMs: 180000 });
}

function formatLatency(ms) {
  if (ms < 1000) return ms + "ms";
  const seconds = Math.floor(ms / 1000);
  const remainingMs = ms % 1000;
  if (seconds < 60) return seconds + "s " + remainingMs + "ms";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes + "m " + remainingSeconds + "s";
}

function backendLabel(id) {
  return BACKEND_LABELS[id] || id || "Model";
}

function ocrStatusLabel(ocr) {
  if (!ocr || ocr.mode === "off") return "OCR disabled";
  return ocr.ready ? "OCR ready" : "OCR unavailable: install Tesseract";
}

function readyClass(ready) {
  return ready === true ? "ok" : ready === false ? "bad" : "";
}

async function loadBackends() {
  const data = await api("/api/backends", undefined, { timeoutMs: 10000 });
  BACKENDS = data.backends || [];
  BACKEND_LABELS = Object.fromEntries(BACKENDS.map(b => [b.id, b.label]));
  BACKEND_DEFAULT = data.default || (BACKENDS[0] && BACKENDS[0].id) || null;
  return data;
}

function validateCredentials(provider) {
  if (provider === "outlook" && !($("#token")?.value || "").trim()) {
    const dialog = $("#graph-token-dialog");
    if (dialog && typeof dialog.showModal === "function" && !dialog.open) {
      dialog.showModal();
    }
    return { msg: "Paste a Graph access token first.", focus: "#token" };
  }
  return null;
}

function readCount(max = 100) {
  const cap = Math.max(1, max || 100);
  let n = parseInt($("#count").value, 10);
  if (!Number.isFinite(n) || n < 1) n = cap;
  n = Math.min(n, cap);
  $("#count").value = n;
  return n;
}

/* Time window -> {since?, before?} as ISO strings for /api/emails.
   Bounds are inclusive; "before" is sent as the end of the chosen day. */
function readWindow() {
  const select = $("#window");
  if (!select) return {};
  const mode = select.value;
  if (mode === "custom") {
    const out = {};
    const from = $("#since")?.value;
    const to = $("#before")?.value;
    const start = from ? new Date(from + "T00:00:00") : null;
    const end = to ? new Date(to + "T23:59:59.999") : null;
    if (start && !Number.isNaN(start.getTime())) out.since = start.toISOString();
    if (end && !Number.isNaN(end.getTime())) out.before = end.toISOString();
    return out;
  }
  const days = parseInt(mode, 10);
  if (!Number.isFinite(days) || days < 1) return {};
  return { since: new Date(Date.now() - days * 86400000).toISOString() };
}

function tagFor(taxonomy, group, key) {
  const item = taxonomy && taxonomy[group] ? taxonomy[group][key] : null;
  return el("span", { class: "tag", "data-k": key }, item ? item.label : key);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initUserGate);
} else {
  initUserGate();
}
