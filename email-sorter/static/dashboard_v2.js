(() => {
  "use strict";

  const state = {
    emails: [],
    results: new Map(),
    taxonomy: null,
    selectedId: null,
    controller: null,
    deadlineOnly: false,
  };

  const priority = {
    needs_action: 0,
    needs_reply: 1,
    reminder: 2,
    no_immediate_action: 3,
  };

  function setBusy(busy) {
    $("#go").disabled = busy;
    $("#backend").disabled = busy;
    $("#cancel").hidden = !busy;
  }

  function setProgress(done, total) {
    $("#progress").hidden = !total;
    $("#progress > div").style.width = `${total ? done / total * 100 : 0}%`;
    $("#progress-label").textContent = total ? `Classifying ${done} of ${total}` : "";
  }

  function fillOptions(select, items, allLabel) {
    select.replaceChildren(el("option", { value: "" }, allLabel));
    for (const [key, item] of Object.entries(items)) {
      select.append(el("option", { value: key }, item.label));
    }
  }

  function updateSummary() {
    const results = [...state.results.values()];
    $("#count-total").textContent = state.emails.length;
    $("#count-action").textContent = results.filter(r => r.reply_nature === "needs_action").length;
    $("#count-reply").textContent = results.filter(r => r.reply_nature === "needs_reply").length;
    $("#count-deadline").textContent = results.filter(r => r.deadline).length;
  }

  function updateQuickButtons(filter) {
    for (const [id, active] of [
      ["quick-all", filter === "all"],
      ["quick-action", filter === "action"],
      ["quick-reply", filter === "reply"],
      ["quick-deadline", filter === "deadline"],
    ]) {
      const button = $(`#${id}`);
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  function setQuickFilter(filter) {
    if (filter === "all") {
      $("#search").value = "";
      $("#filter-content").value = "";
    }
    $("#filter-reply").value = filter === "action" || filter === "reply" ? `needs_${filter}` : "";
    state.deadlineOnly = filter === "deadline";
    updateQuickButtons(filter);
    renderRows();
  }

  function timestamp(email) {
    const value = Date.parse(email.received);
    return Number.isFinite(value) ? value : 0;
  }

  function sortedEmails() {
    const sort = $("#sort").value;
    return [...state.emails].sort((a, b) => {
      if (sort === "newest") return timestamp(b) - timestamp(a);
      if (sort === "oldest") return timestamp(a) - timestamp(b);
      const aResult = state.results.get(a.id);
      const bResult = state.results.get(b.id);
      const aPriority = aResult ? (priority[aResult.reply_nature] ?? 4) : -1;
      const bPriority = bResult ? (priority[bResult.reply_nature] ?? 4) : -1;
      return aPriority - bPriority || timestamp(b) - timestamp(a);
    });
  }

  function visibleEmails() {
    const query = $("#search").value.trim().toLowerCase();
    const category = $("#filter-content").value;
    const reply = $("#filter-reply").value;

    return sortedEmails().filter(email => {
      const result = state.results.get(email.id);
      const matchesText = !query || `${email.sender} ${email.subject}`.toLowerCase().includes(query);
      return matchesText &&
        (!category || (result && result.content_category === category)) &&
        (!reply || (result && result.reply_nature === reply)) &&
        (!state.deadlineOnly || (result && result.deadline));
    });
  }

  function displayDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function selectEmail(email) {
    state.selectedId = email.id;
    renderRows();
    renderDetail(email);
  }

  function renderRows() {
    const body = $("#email-rows");
    const emails = visibleEmails();
    body.replaceChildren();
    if (!emails.length) {
      const row = el("tr");
      row.append(el(
        "td",
        { class: "table-empty", colspan: "4" },
        state.emails.length ? "No emails match these filters." : "Connect a mailbox to load and classify emails.",
      ));
      body.append(row);
      $("#results-count").textContent = state.emails.length ? "No matching emails" : "";
      return;
    }
    $("#results-count").textContent = `Showing ${emails.length} of ${state.emails.length} emails`;

    for (const email of emails) {
      const result = state.results.get(email.id);
      const row = el("tr", { class: email.id === state.selectedId ? "selected" : "" });
      const details = el("td", { class: "dashboard-email-cell" });
      const select = el("button", {
        type: "button",
        class: "email-select",
        "aria-pressed": String(email.id === state.selectedId),
      });
      select.append(
        el("strong", {}, email.sender || "Unknown sender"),
        el("span", {}, email.subject || "(no subject)"),
        el("small", {}, displayDate(email.received)),
      );
      select.addEventListener("click", () => {
        selectEmail(email);
        if (!$("#email-detail-dialog").open) $("#email-detail-dialog").showModal();
      });
      details.append(select);

      let category = el("span", { class: "sub" }, "Classifying…");
      let reply = el("span", { class: "sub" }, "—");
      let deadline = el("span", { class: "sub" }, "—");
      if (result?.error) {
        category = el("span", { class: "dashboard-error", title: result.error }, "Failed");
        reply = el("span", { class: "sub" }, "Retry by fetching again");
      } else if (result) {
        category = tagFor(state.taxonomy, "content", result.content_category);
        reply = tagFor(state.taxonomy, "reply", result.reply_nature);
        deadline = el("span", { class: result.deadline ? "deadline" : "sub" }, result.deadline || "—");
      }
      const categoryCell = el("td", { "data-label": "Category" });
      const replyCell = el("td", { "data-label": "Reply / action" });
      const deadlineCell = el("td", { "data-label": "Deadline" });
      categoryCell.append(category);
      replyCell.append(reply);
      deadlineCell.append(deadline);
      row.append(details, categoryCell, replyCell, deadlineCell);
      body.append(row);
    }
  }

  function renderDetail(email) {
    const box = $("#email-detail");
    const result = state.results.get(email.id);
    $("#email-detail-title").textContent = email.subject || "(no subject)";
    box.replaceChildren(
      el("p", { class: "detail-sender" }, email.sender || "Unknown sender"),
      el("p", { class: "sub" }, displayDate(email.received)),
    );
    if (!result) {
      box.append(el("p", { class: "empty" }, "Classification is pending."));
    } else if (result.error) {
      box.append(el("p", { class: "dashboard-error" }, result.error));
    } else {
      const labels = el("div", { class: "detail-tags" });
      labels.append(
        tagFor(state.taxonomy, "content", result.content_category),
        tagFor(state.taxonomy, "reply", result.reply_nature),
      );
      box.append(labels);
      if (result.model_name) box.append(el("p", {}, `Model: ${result.model_name}`));
      if (result.deadline) box.append(el("p", {}, `Deadline: ${result.deadline}`));
      if (result.reason) {
        box.append(el("p", {}, result.reason));
      }
    }
    const body = email.body || email.preview || "(No email body available.)";
    if (email.text_source && email.text_source !== "body") {
      const confidence = email.ocr_confidence == null
        ? ""
        : ` (${email.ocr_confidence}% OCR confidence)`;
      box.append(el("p", { class: "sub" }, `Text source: ${email.text_source}${confidence}`));
    }
    for (const note of email.ocr_notes || []) {
      box.append(el("p", { class: "sub" }, note));
    }
    box.append(el("h3", {}, "Message"), el("pre", { class: "detail-body" }, body));
  }

  async function refreshHealth() {
    const backend = $("#backend").value;
    try {
      const health = await api(`/api/health?backend=${encodeURIComponent(backend)}`, undefined, { timeoutMs: 10000 });
      const isReady = health.backend_ready;
      $("#dot").className = `dot ${isReady === true ? "ok" : isReady === false ? "bad" : ""}`;
      const backendStatus = isReady === true
        ? `${backendLabel(backend)} ready.`
        : isReady === false && backend === "ml"
          ? "Classical ML models not found. Train them with: PYTHONPATH=../classical-ml/src .venv/bin/python -m train_email_ml"
          : isReady === false ? `${backendLabel(backend)} is not ready.` : "Backend readiness unknown.";
      $("#health").textContent = `${backendStatus} ${ocrStatusLabel(health.ocr)}.`;
    } catch (error) {
      $("#dot").className = "dot bad";
      $("#health").textContent = error.message || "Could not check backend status.";
    }
  }

  async function start() {
    const { provider, credentials } = readCredentials();
    const invalid = validateCredentials(provider);
    if (invalid) {
      notice(invalid.msg, true);
      $(invalid.focus).focus();
      return;
    }

    const controller = new AbortController();
    state.controller = controller;
    state.emails = [];
    state.results.clear();
    state.selectedId = null;
    if ($("#email-detail-dialog").open) $("#email-detail-dialog").close();
    notice("");
    updateSummary();
    renderRows();
    $("#email-detail").replaceChildren(el("p", { class: "empty" }, "Loading emails…"));
    setBusy(true);

    try {
      const data = await api("/api/emails", {
        provider,
        credentials,
        count: readCount(),
      }, { signal: controller.signal, timeoutMs: 60000 });
      $("#mailbox-settings").open = false;
      state.emails = data.emails;
      updateSummary();
      if (!state.emails.length) {
        renderRows();
        $("#email-detail").replaceChildren(el("p", { class: "empty" }, "No emails found."));
        notice("No emails found in that mailbox.");
        return;
      }

      setProgress(0, state.emails.length);
      state.selectedId = state.emails[0].id;
      renderRows();
      renderDetail(state.emails[0]);
      for (let index = 0; index < state.emails.length; index++) {
        if (controller.signal.aborted) break;
        const email = state.emails[index];
        try {
          const result = await classifyEmail(email, $("#backend").value, controller.signal);
          state.results.set(email.id, result);
        } catch (error) {
          if (controller.signal.aborted) break;
          state.results.set(email.id, { error: error.message });
        }
        setProgress(index + 1, state.emails.length);
        updateSummary();
        renderRows();
        if (state.selectedId === email.id) renderDetail(email);
      }
      const failures = [...state.results.values()].filter(result => result.error).length;
      notice(failures ? `${failures} email${failures === 1 ? "" : "s"} could not be classified.` : "");
    } catch (error) {
      if (error.name !== "AbortError") notice(error.message, true);
    } finally {
      if (state.controller === controller) {
        state.controller = null;
        setBusy(false);
        setProgress(0, 0);
      }
    }
  }

  async function init() {
    initMailboxForm();
    $("#go").addEventListener("click", start);
    $("#cancel").addEventListener("click", () => state.controller?.abort());
    $("#email-detail-close").addEventListener("click", () => $("#email-detail-dialog").close());
    $("#email-detail-dialog").addEventListener("click", event => {
      if (event.target === $("#email-detail-dialog")) $("#email-detail-dialog").close();
    });
    $("#email-detail-dialog").addEventListener("cancel", event => {
      event.preventDefault();
      $("#email-detail-dialog").close();
    });
    $("#backend").addEventListener("change", refreshHealth);
    $("#quick-all").addEventListener("click", () => setQuickFilter("all"));
    $("#quick-action").addEventListener("click", () => setQuickFilter("action"));
    $("#quick-reply").addEventListener("click", () => setQuickFilter("reply"));
    $("#quick-deadline").addEventListener("click", () => setQuickFilter("deadline"));
    $("#clear-filters").addEventListener("click", () => {
      $("#search").value = "";
      $("#filter-content").value = "";
      $("#filter-reply").value = "";
      setQuickFilter("all");
    });
    for (const selector of ["#search", "#filter-content", "#filter-reply", "#sort"]) {
      $(selector).addEventListener("input", () => {
        state.deadlineOnly = false;
        updateQuickButtons("");
        renderRows();
      });
      $(selector).addEventListener("change", () => {
        state.deadlineOnly = false;
        updateQuickButtons("");
        renderRows();
      });
    }

    try {
      const [taxonomy, backendData] = await Promise.all([
        api("/api/taxonomy"),
        loadBackends(),
      ]);
      state.taxonomy = taxonomy;
      setQuickFilter("all");
      fillOptions($("#filter-content"), taxonomy.content, "All categories");
      fillOptions($("#filter-reply"), taxonomy.reply, "All types");
      $("#backend").replaceChildren(...BACKENDS.map(item =>
        el("option", { value: item.id }, item.label)));
      if (!backendData.backends.length) throw new Error("No classifier backends are available.");
      $("#backend").value = BACKEND_DEFAULT;
      renderRows();
      await refreshHealth();
    } catch (error) {
      notice(error.message, true);
      $("#go").disabled = true;
    }
  }

  init();
})();
