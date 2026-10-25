/* Compare page: run the same batch through several backends and summarise timing. */

(() => {
  "use strict";

  const state = {
    tax: null,
    backends: [],
    selected: new Set(),
    ranBackends: [],
    emails: [],
    results: {},       // emailId -> { backendId: { ok, ... } }
    cells: new Map(),  // "emailId\u0000backendId" -> td
    warmup: {},        // backendId -> ms, or null
    warmupUsed: false,
    run: 0,
    controller: null,
    completed: false,
    hadError: false,
    errorShown: false,
  };

  function cellKey(emailId, backendId) {
    return emailId + "\u0000" + backendId;
  }

  function setBusy(busy) {
    $("#go").disabled = busy;
    $("#cancel").hidden = !busy;
    $("#export").hidden = busy || !state.completed;
    document.querySelectorAll("#backend-list input").forEach(cb => { cb.disabled = busy; });
    $("#warmup").disabled = busy;
    if (!busy) $("#go").textContent = "Fetch and compare";
  }

  function renderBackends() {
    const wrap = $("#backend-list");
    wrap.replaceChildren();
    state.selected.clear();

    if (!state.backends.length) {
      wrap.append(el("p", { class: "sub" }, "No backends are registered."));
      return;
    }

    for (const b of state.backends) {
      const lab = el("label", { class: "backend-pick" });
      const cb = el("input", { type: "checkbox", value: b.id });
      cb.checked = true;
      state.selected.add(b.id);
      cb.addEventListener("change", () => {
        cb.checked ? state.selected.add(b.id) : state.selected.delete(b.id);
      });
      const dot = el("span", { class: "dot " + readyClass(b.ready) });
      const text = el("div", { class: "backend-text" });
      text.append(
        el("span", { class: "backend-name" }, b.label),
        el("span", { class: "sub" }, b.description || ""),
      );
      lab.append(cb, dot, text);
      wrap.append(lab);
    }
  }

  function updateHealth() {
    const total = state.backends.length;
    const ready = state.backends.filter(b => b.ready === true).length;
    const dot = $("#dot");
    if (!total) {
      dot.className = "dot bad";
      $("#health").textContent = "No backends registered.";
      return;
    }
    dot.className = "dot " + (ready === total ? "ok" : ready ? "" : "bad");
    $("#health").textContent = `${ready} of ${total} backend${total === 1 ? "" : "s"} ready`;
  }

  function renderTable(chosen) {
    state.cells = new Map();
    const wrap = el("div", { class: "compare-wrap" });
    const table = el("table", { class: "compare" });
    const thead = el("thead");
    const head = el("tr");
    head.append(el("th", {}, "Email"));
    for (const b of chosen) head.append(el("th", {}, b.label));
    thead.append(head);
    table.append(thead);

    const tbody = el("tbody");
    for (const m of state.emails) {
      const row = el("tr");
      const meta = el("td");
      const box = el("div", { class: "mail-meta" });
      box.append(
        el("span", { class: "name" }, m.sender),
        el("span", { class: "subject" }, m.subject),
      );
      meta.append(box);
      row.append(meta);
      for (const b of chosen) {
        const td = el("td", {}, "…");
        state.cells.set(cellKey(m.id, b.id), td);
        row.append(td);
      }
      tbody.append(row);
    }
    table.append(tbody);
    wrap.append(table);
    $("#results").replaceChildren(wrap);
  }

  function setCell(email, backendId, r) {
    const td = state.cells.get(cellKey(email.id, backendId));
    if (!td) return;
    const tags = el("div", { class: "cell-tags" });
    tags.append(
      tagFor(state.tax, "content", r.content_category),
      tagFor(state.tax, "reply", r.reply_nature),
    );
    td.replaceChildren(tags, el("div", { class: "cell-time" }, formatLatency(r.duration_ms || 0)));
  }

  function setCellError(email, backendId, message) {
    const td = state.cells.get(cellKey(email.id, backendId));
    if (!td) return;
    const text = message.length > 160 ? message.slice(0, 157) + "…" : message;
    td.replaceChildren(el("span", { class: "cell-err", title: message }, text));
  }

  function record(email, backendId, r) {
    if (!state.results[email.id]) state.results[email.id] = {};
    state.results[email.id][backendId] = { ok: true, ...r };
  }

  function recordError(email, backendId, message) {
    if (!state.results[email.id]) state.results[email.id] = {};
    state.results[email.id][backendId] = { ok: false, error: message };
  }

  function percentile(sorted, p) {
    if (!sorted.length) return null;
    const idx = Math.ceil(p / 100 * sorted.length) - 1;
    return sorted[Math.max(0, Math.min(sorted.length - 1, idx))];
  }

  function backendStats(backendId) {
    const times = [];
    let errors = 0;
    for (const m of state.emails) {
      const r = state.results[m.id] && state.results[m.id][backendId];
      if (!r) continue;
      if (r.ok && Number.isFinite(r.duration_ms)) times.push(r.duration_ms);
      else if (!r.ok) errors++;
    }
    times.sort((a, b) => a - b);
    const total = times.reduce((a, b) => a + b, 0);
    return {
      ok: times.length,
      errors,
      total: times.length ? total : null,
      avg: times.length ? Math.round(total / times.length) : null,
      median: percentile(times, 50),
      p95: percentile(times, 95),
      warmup: state.warmup[backendId] ?? null,
    };
  }

  function cardRow(label, value) {
    const row = el("div", { class: "card-row" });
    row.append(el("span", {}, label), el("b", {}, value));
    return row;
  }

  function agreementTable(chosen) {
    const wrap = el("div", { class: "compare-wrap" });
    const table = el("table", { class: "compare" });
    const thead = el("thead");
    const head = el("tr");
    head.append(el("th", {}, "Backend"));
    for (const b of chosen) head.append(el("th", {}, b.label));
    thead.append(head);
    table.append(thead);

    const tbody = el("tbody");
    for (const a of chosen) {
      const row = el("tr");
      row.append(el("td", {}, a.label));
      for (const b of chosen) {
        if (a.id === b.id) {
          row.append(el("td", {}, "—"));
          continue;
        }
        let same = 0, both = 0;
        for (const m of state.emails) {
          const ra = state.results[m.id] && state.results[m.id][a.id];
          const rb = state.results[m.id] && state.results[m.id][b.id];
          if (!ra || !rb || !ra.ok || !rb.ok) continue;
          both++;
          if (ra.content_category === rb.content_category && ra.reply_nature === rb.reply_nature) same++;
        }
        const pct = both ? Math.round(same / both * 100) : null;
        row.append(el("td", {}, both ? `${same}/${both} (${pct}%)` : "—"));
      }
      tbody.append(row);
    }
    table.append(tbody);
    wrap.append(table);
    return wrap;
  }

  function renderSummary(chosen, partial) {
    const grid = el("div", { class: "summary-grid" });
    for (const b of chosen) {
      const s = backendStats(b.id);
      const card = el("div", { class: "card" });
      card.append(el("div", { class: "card-title" }, b.label));
      card.append(cardRow("Emails", `${s.ok} / ${state.emails.length}`));
      card.append(cardRow("Total", s.total == null ? "—" : formatLatency(s.total)));
      card.append(cardRow("Average", s.avg == null ? "—" : formatLatency(s.avg)));
      card.append(cardRow("Median", s.median == null ? "—" : formatLatency(s.median)));
      card.append(cardRow("p95", s.p95 == null ? "—" : formatLatency(s.p95)));
      card.append(cardRow("Warm-up", s.warmup == null ? "—" : formatLatency(s.warmup)));
      card.append(cardRow("Errors", String(s.errors)));
      grid.append(card);
    }

    const note = el(
      "p",
      { class: "summary-note" },
      `Latency is measured server-side per request; card totals sum those requests.` +
      (state.warmupUsed ? " Warm-up is excluded from averages." : "") +
      (partial ? " This run was cancelled, so the figures are partial." : ""),
    );

    $("#summary").replaceChildren(grid, note);
    if (chosen.length > 1) {
      $("#summary").append(
        el("div", { class: "section-title" }, "Agreement"),
        el("p", { class: "summary-note" }, "Share of emails where both backends returned the same content and reply labels."),
        agreementTable(chosen),
      );
    }
  }

  function csvCell(value) {
    let s = value == null ? "" : String(value);
    if (/^[=+\-@]/.test(s)) s = "'" + s;
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function exportCsv() {
    const chosen = state.backends.filter(b => state.ranBackends.includes(b.id));
    const lines = [[
      "email_id", "sender", "subject", "backend",
      "content_category", "reply_nature", "duration_ms", "error",
    ]];
    for (const m of state.emails) {
      for (const b of chosen) {
        const r = state.results[m.id] && state.results[m.id][b.id];
        if (!r) continue;
        lines.push([
          m.id, m.sender, m.subject, b.label,
          r.ok ? r.content_category : "",
          r.ok ? r.reply_nature : "",
          r.ok ? r.duration_ms : "",
          r.ok ? "" : r.error,
        ]);
      }
    }
    const csv = lines.map(row => row.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `comparison_${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}.csv`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function startCompare() {
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
    const chosen = state.backends.filter(b => state.selected.has(b.id));
    if (chosen.length < 2) {
      notice("Pick at least two backends to compare.", true);
      return;
    }
    const count = readCount(state.tax.max_emails);

    const my = ++state.run;
    const controller = new AbortController();
    state.controller = controller;
    state.ranBackends = chosen.map(b => b.id);
    state.emails = [];
    state.results = {};
    state.warmup = {};
    state.cells = new Map();
    state.completed = false;
    state.hadError = false;
    state.errorShown = false;
    state.warmupUsed = $("#warmup").checked;
    notice("");
    $("#summary").replaceChildren();
    $("#latency-label").textContent = "";
    $("#count-label").textContent = "";
    $("#export").hidden = true;
    $("#progress > div").style.width = "0%";
    $("#results").replaceChildren(el("p", { class: "empty" }, "Fetching emails..."));
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
        $("#results").replaceChildren(el("p", { class: "empty" }, "No emails found in that mailbox."));
        notice("No emails found in that mailbox.");
        return;
      }
      renderTable(chosen);
      $("#progress").hidden = false;
      const t0 = performance.now();
      const totalSteps = chosen.length * state.emails.length;
      let step = 0;

      for (const b of chosen) {
        if (my !== state.run) return;

        if ($("#warmup").checked) {
          setProgress(step, totalSteps, `Warming up ${b.label}...`);
          let warmupTimedOut = false;
          try {
            const warm = await classifyEmail(state.emails[0], b.id, controller.signal);
            state.warmup[b.id] = warm.duration_ms;
          } catch (e) {
            if (e.name === "AbortError" && controller.signal.aborted) return;
            state.warmup[b.id] = null;
            warmupTimedOut = !!e.timedOut;
            state.hadError = true;
            if (!state.errorShown) {
              notice(e.message, true);
              state.errorShown = true;
            }
          }
          if (my !== state.run) return;
          if (warmupTimedOut) {
            // Don't spend a full timeout on every remaining email.
            for (let j = 0; j < state.emails.length; j++) {
              recordError(state.emails[j], b.id, "Warm-up timed out");
              setCellError(state.emails[j], b.id, "Warm-up timed out");
              step++;
            }
            setProgress(step, totalSteps);
            continue;
          }
        }

        let consecutive = 0;
        for (let i = 0; i < state.emails.length; i++) {
          const m = state.emails[i];
          setProgress(step, totalSteps, `${b.label} · ${i + 1} of ${state.emails.length}`);
          try {
            const r = await classifyEmail(m, b.id, controller.signal);
            record(m, b.id, r);
            setCell(m, b.id, r);
            consecutive = 0;
          } catch (e) {
            if (e.name === "AbortError" && controller.signal.aborted) return;
            state.hadError = true;
            recordError(m, b.id, e.message);
            setCellError(m, b.id, e.message);
            if (!state.errorShown) {
              notice(e.message, true);
              state.errorShown = true;
            }
            consecutive++;
            if (e.timedOut) consecutive = 3;
          }
          step++;
          setProgress(step, totalSteps);

          if (consecutive >= 3) {
            for (let j = i + 1; j < state.emails.length; j++) {
              recordError(state.emails[j], b.id, "Skipped after repeated failures");
              setCellError(state.emails[j], b.id, "Skipped after repeated failures");
              step++;
            }
            setProgress(step, totalSteps);
            break;
          }
        }
      }

      if (my !== state.run) return;
      state.completed = true;
      setBusy(false);
      $("#progress").hidden = true;
      renderSummary(chosen, false);
      $("#export").hidden = false;
      const elapsed = Math.round(performance.now() - t0);
      $("#latency-label").textContent =
        `Compared ${chosen.length} backends on ${state.emails.length} ` +
        `email${state.emails.length === 1 ? "" : "s"} in ${formatLatency(elapsed)}`;
      $("#count-label").textContent = `${state.emails.length} emails × ${chosen.length} backends`;
      if (!state.hadError) notice("");
    } catch (e) {
      if (e.name === "AbortError") return;
      $("#progress").hidden = true;
      $("#results").replaceChildren(el("p", { class: "empty" }, "No emails loaded."));
      notice(e.message, true);
    } finally {
      if (my === state.run) {
        setBusy(false);
        $("#go").textContent = "Fetch and compare";
        if (!state.completed) $("#progress").hidden = true;
        state.controller = null;
      }
    }
  }

  function cancelCompare() {
    if ($("#cancel").hidden) return;
    state.run++;
    if (state.controller) state.controller.abort();
    state.controller = null;
    $("#progress").hidden = true;

    state.cells.forEach(td => {
      if (td.textContent === "…") {
        td.replaceChildren(el("span", { class: "cell-err" }, "Cancelled"));
      }
    });

    if (!state.emails.length) {
      $("#results").replaceChildren(el("p", { class: "empty" }, "Cancelled."));
    }

    const any = state.emails.some(m => state.results[m.id] && Object.keys(state.results[m.id]).length);
    state.completed = any;
    setBusy(false);
    $("#go").textContent = "Fetch and compare";

    if (any) {
      const chosen = state.backends.filter(b => state.ranBackends.includes(b.id));
      renderSummary(chosen, true);
      $("#export").hidden = false;
    }
    notice("Comparison cancelled.");
  }

  async function init() {
    initMailboxForm();
    $("#go").addEventListener("click", startCompare);
    $("#cancel").addEventListener("click", cancelCompare);
    $("#export").addEventListener("click", exportCsv);

    try {
      const data = await loadBackends();
      state.backends = data.backends;
      renderBackends();
      updateHealth();
    } catch (e) {
      $("#dot").className = "dot bad";
      $("#health").textContent = "Could not load backends.";
      notice(e.message, true);
    }

    try {
      state.tax = await api("/api/taxonomy", undefined, { timeoutMs: 15000 });
      $("#count").max = state.tax.max_emails;
    } catch (e) {
      notice(e.message, true);
    }
  }

  init();
})();
