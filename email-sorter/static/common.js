/* Shared helpers: DOM, API calls, formatting, backend registry. */

const $ = s => document.querySelector(s);

let BACKENDS = [];
let BACKEND_LABELS = {};
let BACKEND_DEFAULT = null;

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
    const r = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json" },
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
  $("#provider").addEventListener("change", e => {
    $("#f-outlook").hidden = e.target.value !== "outlook";
    $("#f-imap").hidden = e.target.value !== "imap";
  });
}

function readCredentials() {
  const provider = $("#provider").value;
  const credentials = provider === "outlook"
    ? { token: $("#token").value }
    : { host: $("#host").value, user: $("#user").value, password: $("#pass").value };
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
  if (provider === "outlook") {
    if (!$("#token").value.trim()) return { msg: "Paste a Graph access token first.", focus: "#token" };
  } else {
    if (!$("#host").value.trim()) return { msg: "Enter the IMAP server first.", focus: "#host" };
    if (!$("#user").value.trim()) return { msg: "Enter your email address first.", focus: "#user" };
    if (!$("#pass").value) return { msg: "Enter your app password first.", focus: "#pass" };
  }
  return null;
}

function readCount(max = 50) {
  let n = parseInt($("#count").value, 10);
  if (!Number.isFinite(n) || n < 1) n = 10;
  n = Math.min(n, Math.max(1, max || 50));
  $("#count").value = n;
  return n;
}

function tagFor(taxonomy, group, key) {
  const item = taxonomy && taxonomy[group] ? taxonomy[group][key] : null;
  return el("span", { class: "tag", "data-k": key }, item ? item.label : key);
}
