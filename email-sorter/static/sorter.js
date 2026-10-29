/* Sorter page: pick one backend, fetch emails, classify them with retry/cancel. */

(() => {
  "use strict";

  const state = {
    tax: null,
    emails: [],
    results: {},
    rows: {},
    run: 0,
    selected: null,
    effective: null,
    lastRunBackend: null,
    controller: null,
    failedIds: new Set(),
    filters: { content: new Set(), reply: new Set() },
  };

  let healthSeq = 0;

  function setResultBackend(name) {
    const note = $("#result-note");
    if (!name) { note.hidden = true; return; }
    $("#result-backend").textContent = backendLabel(name);
    note.hidden = false;
  }

  function updateRetryButton() {
    const btn = $("#retry");
    const n = state.failedIds.size;
    btn.hidden = n === 0 || !state.emails.length;
    btn.textContent = n === 1 ? "Retry 1 failed email" : `Retry ${n} failed emails`;
  }

  function setBusy(busy) {
    $("#go").disabled = busy;
    $("#cancel").hidden = !busy;
    document.querySelectorAll("#backend-buttons .btn-backend").forEach(btn => { btn.disabled = busy; });
    if (busy) $("#retry").hidden = true;
    else updateRetryButton();
  }

  function renderBackends(backends) {
    const wrap = $("#backend-buttons");
    wrap.replaceChildren();
    for (const b of backends) {
      const btn = el("button", {
        type: "button",
        class: "btn-backend",
        "data-backend": b.id,
        "aria-pressed": "false",
        title: b.description || "",
      }, b.label);
      btn.addEventListener("click", () => setBackend(b.id));
      wrap.append(btn);
    }
  }

  function setBackend(name, save = true, check = true) {
    state.selected = name;
    document.querySelectorAll("#backend-buttons .btn-backend").forEach(btn => {
      const on = btn.dataset.backend === name;
      btn.className = on ? "btn-backend active" : "btn-backend";
      btn.setAttribute("aria-pressed", String(on));
    });
    $("#backend-current").textContent = backendLabel(name);
    if (save) localStorage.setItem("email_backend", name);
    if (check) refreshHealth();
  }

  function renderHealth(h) {
    const dot = $("#dot");
    let ok = false, text = "", unknown = false;
    if (h.backend === "bert") {
      ok = !!h.bert_ready;
      text = ok ? "Text-encoder models ready." : "Text-encoder models not found. Train them with: python text-encoders/train.py";
    } else if (h.backend === "ml") {
      ok = !!h.ml_ready;
      text = ok ? "Classical ML models ready." : "Classical ML model files not found. Train them with: PYTHONPATH=../classical-ml/src .venv/bin/python -m train_email_ml";
    } else if (h.backend === "claude") {
      ok = !!h.claude_ready;
      text = ok ? "Claude ready." : "Claude is not ready. Add ANTHROPIC_API_KEY to inbox-sorter/.env and install the anthropic package.";
    } else if (h.backend === "llama") {
      if (!h.ollama_up) text = "Ollama is not running. Start it, then reload.";
      else if (!h.ollama_ready) text = `Model ${h.model} is not installed. Run: ollama pull ${h.model}`;
      else { ok = true; text = `Ollama ready: ${h.model}`; }
    } else if (h.backend_ready === true) {
      ok = true;
      text = "Backend ready.";
    } else if (h.backend_ready === false) {
      text = "Backend not ready.";
    } else {
      unknown = true;
      text = "Backend readiness unknown.";
    }
    dot.className = "dot " + (ok ? "ok" : unknown ? "" : "bad");
    $("#health").textContent = `${text} ${ocrStatusLabel(h.ocr)}.`;
  }

  async function refreshHealth() {
    const seq = ++healthSeq;
    const q = state.selected ? "?backend=" + encodeURIComponent(state.selected) : "";
    try {
      const h = await api("/api/health" + q, undefined, { timeoutMs: 10000 });
      if (seq !== healthSeq) return;
      if (h.backend) state.effective = h.backend;
      renderHealth(h);
    } catch {
      if (seq !== healthSeq) return;
      $("#dot").className = "dot bad";
      $("#health").textContent = "Could not check the backend status.";
    }
  }

  function buildFilters() {
    for (const [group, box] of [["content", "#f-content"], ["reply", "#f-reply"]]) {
      const wrap = $(box);
      wrap.replaceChildren();
      for (const [key, item] of Object.entries(state.tax[group])) {
        const lab = el("label", { class: "check", "data-k": key });
        const cb = el("input", { type: "checkbox", value: key });
        cb.addEventListener("change", () => {
          cb.checked ? state.filters[group].add(key) : state.filters[group].delete(key);
          applyFilters();
        });
        lab.append(
          cb,
          el("span", { "data-k": key, class: "tag" }, item.label),
          el("span", { class: "n", id: `n-${group}-${key}` }, "0"),
        );
        wrap.append(lab);
      }
    }
  }

  function updateCounts() {
    if (!state.tax) return;
    const counts = { content: {}, reply: {} };
    Object.values(state.results).forEach(r => {
      counts.content[r.content_category] = (counts.content[r.content_category] || 0) + 1;
      counts.reply[r.reply_nature] = (counts.reply[r.reply_nature] || 0) + 1;
    });
    for (const group of ["content", "reply"]) {
      for (const key of Object.keys(state.tax[group])) {
        const n = $(`#n-${group}-${key}`);
        if (n) n.textContent = counts[group][key] || 0;
      }
    }
  }

  function applyFilters() {
    state.emails.forEach(m => {
      const r = state.results[m.id], row = state.rows[m.id];
      if (!row) return;
      const okC = !state.filters.content.size || (r && state.filters.content.has(r.content_category));
      const okR = !state.filters.reply.size || (r && state.filters.reply.has(r.reply_nature));
      row.hidden = !(okC && okR);
    });
  }

  function buildRow(m) {
    const d = el("details", { class: "mail" });
    const s = el("summary");
    const left = el("div");
    left.append(
      el("div", { class: "from" }, m.sender),
      el("div", { class: "subj" }, m.subject),
      el("div", { class: "when" }, m.received ? new Date(m.received).toString().slice(0, 21) : ""),
    );
    const tags = el("div", { class: "tags", id: `tags-${CSS.escape(m.id)}` });
    tags.append(el("span", { class: "tag pending" }, "Sorting..."));
    s.append(left, tags);
    const more = el("div", { class: "more" });
    more.append(el("p", {}, m.preview || "(no preview)"));
    d.append(s, more);
    d._tags = tags;
    d._more = more;
    return d;
  }

  function showResult(m, r) {
    const row = state.rows[m.id];
    row._tags.replaceChildren(
      tagFor(state.tax, "content", r.content_category),
      tagFor(state.tax, "reply", r.reply_nature),
    );
    if (r.deadline) row._tags.append(el("span", { class: "deadline" }, "Deadline: " + r.deadline));
    if (r.model_name) {
      row._more.append(el("p", {}, `Model: ${r.model_name}`));
    }
    if (m.text_source && m.text_source !== "body") {
      const confidence = m.ocr_confidence == null
        ? ""
        : ` (${m.ocr_confidence}% OCR confidence)`;
      row._more.append(el("p", {}, `Text source: ${m.text_source}${confidence}`));
    }
    for (const note of m.ocr_notes || []) {
      row._more.append(el("p", { class: "sub" }, note));
    }
    if (r.reason) {
      const p = el("p");
      p.append(el("span", { class: "k" }, "Why: "), document.createTextNode(r.reason));
      row._more.append(p);
    }
  }

  function showFailure(m, text) {
    const row = state.rows[m.id];
    if (!row) return;
    row._tags.replaceChildren(el("span", { class: "tag pending" }, "Could not sort"));
    row._more.append(el("p", {}, text));
  }

  function showSkipped(m, text) {
    const row = state.rows[m.id];
    if (!row) return;
    row._tags.replaceChildren(el("span", { class: "tag pending" }, "Not processed"));
    row._more.append(el("p", {}, text));
  }

  function resetRow(m) {
    const row = state.rows[m.id];
    if (!row) return;
    row._tags.replaceChildren(el("span", { class: "tag pending" }, "Sorting..."));
    while (row._more.children.length > 1) row._more.lastElementChild.remove();
  }

  function showSummary(res, retried) {
    if (!res.sorted) return;
    const name = backendLabel(res.backend);
    const avg = formatLatency(Math.round(res.total / res.sorted));
    const verb = retried ? "re-sorted" : "sorted";
    const failed = res.failed ? `, ${res.failed} failed` : "";
    $("#latency-label").textContent =
      `${name} ${verb} ${res.sorted} email${res.sorted === 1 ? "" : "s"} ` +
      `in ${formatLatency(res.total)} (${avg} each${failed})`;
  }

  async function classifyList(targets, my, signal, backend) {
    let done = 0, success = 0, batchFailed = 0, stop = false;
    const tick = () => setProgress(done, targets.length, `Sorted ${done} of ${targets.length}`);
    tick();
    const sortStart = performance.now();
    let used = backend || null;

    for (let i = 0; i < targets.length; i++) {
      const m = targets[i];
      if (my !== state.run) return null;
      $("#go").textContent = `Sorting ${done + 1} of ${targets.length}...`;
      try {
        const r = await classifyEmail(m, used, signal);
        state.results[m.id] = r;
        state.failedIds.delete(m.id);
        showResult(m, r);
        success++;
        if (r.backend) used = r.backend;
      } catch (e) {
        if (e.name === "AbortError" && signal.aborted) return null;
        batchFailed++;
        state.failedIds.add(m.id);
        showFailure(m, e.message);
        if (batchFailed === 1) {
          const hint = used === "llama" ? " Check that Ollama is running and the model is pulled." : "";
          notice(e.message + hint, true);
        }
        if (e.timedOut) stop = true;
      }
      done++;
      tick();
      updateCounts();
      applyFilters();

      if (stop) {
        // Queue the rest for retry instead of waiting out a timeout on each one.
        for (let j = i + 1; j < targets.length; j++) {
          state.failedIds.add(targets[j].id);
          showSkipped(targets[j], "Skipped after a previous request timed out.");
          batchFailed++;
          done++;
        }
        tick();
        updateCounts();
        applyFilters();
        break;
      }
    }

    if (my !== state.run) return null;
    return {
      total: Math.round(performance.now() - sortStart),
      sorted: success,
      backend: used,
      failed: batchFailed,
    };
  }

  async function start() {
    if (!state.tax) {
      notice("Categories are still loading. Please wait a moment and try again.", true);
      return;
    }
    const { provider, credentials } = readCredentials();
    const invalid = validateCredentials(provider);
    if (invalid) {
      notice(invalid.msg, true);
      $(invalid.focus).focus();
      return;
    }
    const count = readCount(state.tax.max_emails);

    const my = ++state.run;
    const controller = new AbortController();
    state.controller = controller;
    state.results = {};
    state.rows = {};
    state.emails = [];
    state.failedIds.clear();
    state.lastRunBackend = null;
    state.filters.content.clear();
    state.filters.reply.clear();
    notice("");
    $("#latency-label").textContent = "";
    $("#count-label").textContent = "";
    $("#progress > div").style.width = "0%";
    $("#list").replaceChildren(el("p", { class: "empty" }, "Fetching emails..."));
    setResultBackend(null);
    buildFilters();
    updateCounts();
    setBusy(true);
    $("#go").textContent = "Fetching...";

    try {
      const data = await api(
        "/api/emails",
        { provider, credentials, count },
        { signal: controller.signal, timeoutMs: 60000 },
      );
      state.emails = data.emails;
      if (!state.emails.length) {
        $("#list").replaceChildren(el("p", { class: "empty" }, "No emails found in that mailbox."));
        notice("No emails found in that mailbox.");
        return;
      }
      $("#filters").hidden = false;
      const list = $("#list");
      list.replaceChildren();
      state.emails.forEach(m => {
        state.rows[m.id] = buildRow(m);
        list.append(state.rows[m.id]);
      });
      $("#progress").hidden = false;
      state.lastRunBackend = state.selected || state.effective || null;
      const res = await classifyList(state.emails, my, controller.signal, state.lastRunBackend);
      if (!res) return;
      if (res.sorted) {
        state.lastRunBackend = res.backend || state.lastRunBackend;
        setResultBackend(state.lastRunBackend);
      }
      showSummary(res, false);
      if (!res.failed) notice("");
    } catch (e) {
      if (e.name === "AbortError") return;
      $("#progress").hidden = true;
      $("#list").replaceChildren(el("p", { class: "empty" }, "No emails loaded."));
      notice(e.message, true);
    } finally {
      if (my === state.run) {
        setBusy(false);
        $("#go").textContent = "Fetch and sort emails";
        $("#progress").hidden = true;
        state.controller = null;
      }
    }
  }

  async function retryFailed() {
    const targets = state.emails.filter(m => state.failedIds.has(m.id));
    if (!targets.length) return;
    const backend = state.lastRunBackend || state.selected || state.effective || null;
    const my = ++state.run;
    const controller = new AbortController();
    state.controller = controller;
    targets.forEach(resetRow);
    notice("");
    $("#progress > div").style.width = "0%";
    $("#count-label").textContent = "";
    $("#progress").hidden = false;
    setBusy(true);
    $("#go").textContent = `Retrying ${targets.length}...`;

    try {
      const res = await classifyList(targets, my, controller.signal, backend);
      if (!res) return;
      if (res.sorted) {
        state.lastRunBackend = res.backend || state.lastRunBackend;
        setResultBackend(state.lastRunBackend);
      }
      showSummary(res, true);
      if (!res.failed) notice("");
    } catch (e) {
      if (e.name !== "AbortError") notice(e.message, true);
    } finally {
      if (my === state.run) {
        setBusy(false);
        $("#go").textContent = "Fetch and sort emails";
        $("#progress").hidden = true;
        state.controller = null;
      }
    }
  }

  function cancelRun() {
    if ($("#cancel").hidden) return;
    state.run++;
    if (state.controller) state.controller.abort();
    state.controller = null;
    $("#progress").hidden = true;
    setBusy(false);
    $("#go").textContent = "Fetch and sort emails";
    if (!state.emails.length) {
      $("#list").replaceChildren(el("p", { class: "empty" }, "Cancelled."));
    } else {
      state.emails.forEach(m => {
        const row = state.rows[m.id];
        if (row && !state.results[m.id]) {
          row._tags.replaceChildren(el("span", { class: "tag pending" }, "Cancelled"));
        }
      });
    }
    const first = Object.values(state.results)[0];
    if (first && first.backend) setResultBackend(first.backend);
    notice("Sorting cancelled.");
  }

  async function init() {
    try {
      const data = await loadBackends();
      renderBackends(data.backends);
      const saved = localStorage.getItem("email_backend");
      const known = data.backends.some(b => b.id === saved);
      setBackend(known ? saved : data.default, false, false);
      refreshHealth();
    } catch (e) {
      $("#dot").className = "dot bad";
      $("#health").textContent = "Could not load backends.";
      notice(e.message, true);
    }

    try {
      state.tax = await api("/api/taxonomy", undefined, { timeoutMs: 15000 });
      $("#count").max = state.tax.max_emails;
      buildFilters();
      updateCounts();
    } catch (e) {
      notice(e.message, true);
    }
  }

  initMailboxForm();
  $("#go").addEventListener("click", start);
  $("#cancel").addEventListener("click", cancelRun);
  $("#retry").addEventListener("click", retryFailed);
  init();
})();
