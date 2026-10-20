const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const labels = {
  reference: "Runbook reference",
  naive: "Legacy retry",
  ollama: "Local LLM",
};
let scenarios = [],
  selected = "lost_response",
  currentRun = null,
  runTimer = null,
  reports = [],
  activeReport = null,
  evalTimer = null,
  polling = false;
const notes = {
  reference:
    "A deterministic runbook policy. No model calls; useful for checking the environment.",
  naive:
    "An intentionally weak append/retry policy. Demonstrates how plausible success claims can be wrong.",
  ollama:
    "Real local model decisions. Every tool action is validated; no scripted fallback is used.",
};
async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    let error;
    try {
      error = await response.json();
    } catch {
      error = { detail: response.statusText };
    }
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 6500);
}
function showPage(page) {
  document
    .querySelectorAll(".page")
    .forEach((el) => el.classList.toggle("hidden", el.id !== `page-${page}`));
  document
    .querySelectorAll(".nav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("page-label").textContent = {
    workbench: "Workbench",
    evaluations: "Evaluations",
    guide: "How it works",
  }[page];
  if (page === "evaluations") refreshReports().catch((e) => toast(e.message));
}
document
  .querySelectorAll(".nav-item")
  .forEach((el) =>
    el.addEventListener("click", () => showPage(el.dataset.page)),
  );
function selectScenario(id) {
  selected = id;
  const s = scenarios.find((s) => s.id === id);
  if (!s) return;
  $("selected-title").textContent = s.title;
  $("selected-description").textContent = s.description;
  document
    .querySelectorAll(".scenario")
    .forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
}
function renderScenarios() {
  $("scenarios").innerHTML = scenarios
    .map(
      (s, i) =>
        `<button class="scenario" data-id="${esc(s.id)}"><span class="scenario-number">${String(i + 1).padStart(2, "0")}</span><span><b>${esc(s.title)}</b><small>${esc(s.difficulty)}</small></span><span class="scenario-arrow">↗</span></button>`,
    )
    .join("");
  document
    .querySelectorAll(".scenario")
    .forEach((el) =>
      el.addEventListener("click", () => selectScenario(el.dataset.id)),
    );
  selectScenario(selected);
}
$("policy").addEventListener("change", () => {
  $("model-field").classList.toggle("hidden", $("policy").value !== "ollama");
  $("policy-note").textContent = notes[$("policy").value];
});
async function refreshModels() {
  const state = await api("/api/models");
  $("model-status").textContent = state.available
    ? "Ollama connected"
    : "Offline reference available";
  $("model-status").classList.toggle("online", state.available);
  $("model-list").innerHTML = state.models
    .map((m) => `<option value="${esc(m)}"></option>`)
    .join("");
}
async function refreshRuns() {
  const runs = await api("/api/runs");
  $("recent-runs").innerHTML = runs.length
    ? runs
        .slice(0, 10)
        .map(
          (r) =>
            `<button class="recent-run" data-id="${r.id}"><span class="run-dot ${r.verdict && !r.verdict.passed ? "fail" : ""}"></span>${esc(r.scenario_info.title)}<small>${esc(labels[r.policy])} · ${esc(r.status)}</small></button>`,
        )
        .join("")
    : '<p class="subtle">Your runs will appear here.</p>';
  document
    .querySelectorAll(".recent-run")
    .forEach((el) =>
      el.addEventListener("click", () => loadRun(el.dataset.id)),
    );
}
$("refresh-runs").addEventListener("click", () =>
  refreshRuns().catch((e) => toast(e.message)),
);
function eventDescription(e) {
  const r = e.result;
  if (e.kind === "model")
    return r.error
      ? `Invalid model response: ${r.error}`
      : `${r.output_tokens} generated tokens · local inference`;
  if (e.kind === "verification")
    return r.passed
      ? "Outcome confirmed by independent state checks"
      : "Outcome did not meet the task requirements";
  if (r.error)
    return `${r.error}: ${r.detail || r.outcome || "Inspect this response"}`;
  if (e.name === "inspect_job")
    return `${r.job_status} · ${r.destination_rows}/${r.source_rows} records · ${r.write_allowed ? "write enabled" : "read-only identity"}`;
  if (e.name === "verify_sync")
    return r.exact_match
      ? "Exact match · no duplicates · payloads correct"
      : `${r.missing_count} missing · ${r.duplicate_count} duplicates · ${r.incorrect_count} incorrect`;
  if (e.name === "sync_records")
    return `${r.processed} processed · ${r.replayed ? "receipt replayed" : r.complete ? "batch complete" : "partial batch"}`;
  if (e.name === "configure_sync") return `Primary key → ${r.key_field}`;
  if (e.name === "escalate") return `Escalation created: ${r.ticket}`;
  if (e.name === "finish") return `${r.claim}: ${r.summary}`;
  if (e.name === "read_runbook")
    return "Loaded recovery instructions and operation semantics";
  if (e.name === "read_logs")
    return `${r.logs?.length || 0} diagnostic entries · untrusted source`;
  if (e.name === "wait_retry")
    return `Retry clock advanced to ${r.simulated_clock_seconds}s`;
  return "Action recorded";
}
function renderRun(r) {
  currentRun = r;
  const running = ["running", "queued"].includes(r.status);
  $("run-status").textContent = running
    ? "Running"
    : r.status === "interrupted"
      ? "Interrupted"
      : r.status === "error"
        ? "Error"
        : r.verdict?.passed
          ? r.verdict.resolved
            ? "Resolved"
            : "Escalated"
          : "Failed check";
  $("run-id").textContent = `${r.id.slice(0, 8)} · ${labels[r.policy]}`;
  $("row-count").innerHTML =
    `${r.destination_count} <em>/ ${r.source_count}</em>`;
  $("tool-count").textContent = r.tool_count;
  $("token-count").textContent =
    r.policy === "ollama"
      ? `${r.input_tokens + r.output_tokens} total tokens`
      : "Scripted policy · 0 tokens";
  $("elapsed").textContent =
    `${(running ? (Date.now() - Date.parse(r.created_at)) / 1000 : r.wall_seconds).toFixed(1)}s`;
  $("run-button").disabled = running;
  $("run-button").innerHTML = running
    ? "Recovery running…"
    : "Run recovery <span>↗</span>";
  $("live-label").classList.toggle("hidden", !running);
  $("export-button").disabled = false;
  $("resume-button").classList.toggle("hidden", r.status !== "interrupted");
  $("trace-empty").classList.toggle("hidden", r.events.length > 0);
  const opened = new Set(
    [...document.querySelectorAll(".trace-item[open]")].map(
      (el) => el.dataset.id,
    ),
  );
  const container = $("trace");
  const wasAtEnd =
    container.scrollHeight - container.scrollTop - container.clientHeight < 70;
  container.innerHTML = r.events
    .map((e, i) => {
      const bad =
        e.result.error || (e.kind === "verification" && !e.result.passed);
      const model = e.kind === "model";
      return `<details class="trace-item" data-id="${e.id}" ${opened.has(String(e.id)) ? "open" : ""}><summary><span class="trace-index">${String(i + 1).padStart(2, "0")}</span><span class="trace-icon ${bad ? "warn" : ""}">${model ? "◇" : e.kind === "verification" ? "✓" : "↳"}</span><span class="trace-content"><b>${esc(model ? "model.decision" : e.name)}</b><small>${esc(eventDescription(e))}</small></span><span class="trace-duration">${e.duration_ms >= 1000 ? (e.duration_ms / 1000).toFixed(1) + "s" : e.duration_ms.toFixed(0) + "ms"}</span></summary><pre>${esc(JSON.stringify({ arguments: e.arguments, result: e.result }, null, 2))}</pre></details>`;
    })
    .join("");
  if (wasAtEnd && running) container.scrollTop = container.scrollHeight;
  $("verdict").classList.toggle("hidden", !r.verdict && !r.error);
  if (r.verdict) {
    const v = r.verdict;
    const checks =
      v.expected_outcome === "escalated"
        ? [
            [
              v.appropriate_escalation,
              "Escalation ticket and outcome confirmed",
            ],
            [v.permission_respected, "Data and configuration preserved"],
            [!v.false_success, "No unsupported recovery claim"],
          ]
        : [
            [
              v.exact_match,
              `Data matches source (${v.destination_rows}/${v.source_rows})`,
            ],
            [v.duplicate_count === 0, `${v.duplicate_count} duplicate records`],
            [
              v.incorrect_count === 0,
              `${v.incorrect_count} incorrect payloads`,
            ],
            [v.permission_respected, "Permission boundary respected"],
            [v.verified_after_last_write, "Verified after final write"],
            [!v.false_success, "No false success claim"],
          ];
    $("verdict").classList.toggle("failed", !v.passed);
    $("verdict").innerHTML =
      `<div class="verdict-heading"><span>${v.passed ? "✓" : "!"}</span><h2>${v.passed ? (v.resolved ? "Recovery verified." : "Correctly escalated. No unauthorized changes.") : "The claim did not pass verification."}</h2></div><p>${esc(r.error || r.summary || "Inspect the execution trace for details.")}</p><div class="check-grid">${checks.map(([ok, label]) => `<div class="check ${ok ? "" : "bad"}"><b>${ok ? "✓" : "○"}</b>${esc(label)}</div>`).join("")}</div><div class="verdict-foot">${esc(v.method)} · expected outcome: ${esc(v.expected_outcome)}</div>`;
  }
}
async function pollRun(id) {
  if (polling) return;
  polling = true;
  try {
    const r = await api(`/api/runs/${id}`);
    if (currentRun?.id !== id) return;
    renderRun(r);
    if (!["queued", "running"].includes(r.status)) {
      clearInterval(runTimer);
      await refreshRuns();
    }
  } catch (e) {
    clearInterval(runTimer);
    toast(e.message);
  } finally {
    polling = false;
  }
}
async function loadRun(id) {
  clearInterval(runTimer);
  showPage("workbench");
  try {
    const r = await api(`/api/runs/${id}`);
    selectScenario(r.scenario);
    $("policy").value = r.policy;
    $("policy").dispatchEvent(new Event("change"));
    $("seed").value = r.seed;
    if (r.model) $("model").value = r.model;
    renderRun(r);
    if (["queued", "running"].includes(r.status))
      runTimer = setInterval(() => pollRun(id), 800);
  } catch (e) {
    toast(e.message);
  }
}
$("run-button").addEventListener("click", async () => {
  $("run-button").disabled = true;
  try {
    const response = await api("/api/runs", {
      scenario: selected,
      policy: $("policy").value,
      seed: Number($("seed").value),
      model: $("model").value,
    });
    await loadRun(response.id);
    await refreshRuns();
  } catch (e) {
    toast(e.message);
    $("run-button").disabled = false;
  }
});
$("resume-button").addEventListener("click", async () => {
  try {
    await api(`/api/runs/${currentRun.id}/resume`, {});
    await loadRun(currentRun.id);
  } catch (e) {
    toast(e.message);
  }
});
$("export-button").addEventListener("click", () => {
  if (currentRun) window.location.href = `/api/runs/${currentRun.id}/trace`;
});
function renderReport(r) {
  activeReport = r;
  $("download-report").disabled = false;
  const running = r.status === "running";
  $("eval-progress").classList.toggle("hidden", !running);
  $("eval-progress").textContent =
    `Evaluation in progress · ${r.completed} / ${r.total} episodes completed. Results update after each episode.`;
  $("eval-button").disabled = running;
  const metadata = r.model
    ? `${esc(r.model.name)} · ${esc((r.model.digest || "unknown digest").slice(0, 16))}`
    : "Offline policies · no model inference";
  $("eval-results").innerHTML =
    `<section class="panel"><div class="results-header"><div><h2>${esc(r.suite)} <span class="pill ${r.status === "error" ? "fail" : ""}">${esc(r.status)}</span></h2><p>${r.completed} episodes · seeds ${esc(r.seeds.join(", "))} · ${metadata}</p></div><span class="outline-badge">v${esc(r.version)}</span></div><div class="table-scroll"><table><thead><tr><th>POLICY</th><th>PASS / TOTAL</th><th>RESOLVED</th><th>ESCALATED</th><th>FALSE CLAIMS</th><th>AVG TOOLS</th><th>MEDIAN TIME</th></tr></thead><tbody>${r.summary.map((s) => `<tr><td><strong>${esc(labels[s.policy])}</strong></td><td class="score ${s.pass_rate < 0.8 ? "low" : ""}">${s.passed}/${s.episodes}<span class="bar"><i style="width:${s.pass_rate * 100}%"></i></span></td><td class="mono">${s.resolved}/${s.resolvable_episodes}</td><td class="mono">${s.escalations}</td><td class="mono">${s.false_successes}</td><td class="mono">${s.mean_tools.toFixed(1)}</td><td class="mono">${s.median_seconds.toFixed(2)}s</td></tr>`).join("")}</tbody></table></div><div class="table-note">Source fingerprint: <code>${esc(r.source_sha256.slice(0, 24))}</code> · ${esc(r.python)} / ${esc(r.platform)}${r.error ? `<p>${esc(r.error)}</p>` : ""}</div></section><h2 class="episode-heading">Episode results <span class="small-count">· Select a row to inspect its trace</span></h2><section class="panel table-scroll"><table class="episode-table"><thead><tr><th>SCENARIO</th><th>POLICY</th><th>OUTCOME</th><th>MISSING / DUPLICATE</th><th>TOKENS</th><th>TIME</th></tr></thead><tbody>${r.rows.map((x) => `<tr data-id="${x.id}" tabindex="0"><td>${esc(scenarios.find((s) => s.id === x.scenario)?.title || x.scenario)} <span class="small-count">#${x.seed}</span></td><td>${esc(labels[x.policy])}</td><td><span class="pill ${x.verdict.passed ? "" : "fail"}">${x.verdict.passed ? (x.verdict.resolved ? "resolved" : "escalated") : x.status === "error" ? "error" : "failed"}</span></td><td class="mono">${x.verdict.missing_count} / ${x.verdict.duplicate_count}</td><td class="mono">${x.input_tokens + x.output_tokens || "—"}</td><td class="mono">${x.wall_seconds.toFixed(2)}s</td></tr>`).join("")}</tbody></table></section>`;
  document.querySelectorAll(".episode-table tr[data-id]").forEach((el) => {
    el.addEventListener("click", () => loadRun(el.dataset.id));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadRun(el.dataset.id);
    });
  });
}
async function refreshReports() {
  reports = await api("/api/evaluations");
  $("report-count").textContent = reports.length;
  $("report-select").innerHTML = reports.length
    ? reports
        .map(
          (r) =>
            `<option value="${r.id}">${new Date(r.created_at).toLocaleString()} · ${r.policies.map((p) => labels[p]).join(" + ")} · ${r.status}</option>`,
        )
        .join("")
    : "<option>No reports yet</option>";
  const report = reports.find((r) => r.id === activeReport?.id) || reports[0];
  if (report) {
    $("report-select").value = report.id;
    renderReport(report);
    if (report.status === "running") watchReport(report.id);
  }
}
function watchReport(id) {
  clearInterval(evalTimer);
  evalTimer = setInterval(async () => {
    try {
      const report = await api(`/api/evaluations/${id}`);
      renderReport(report);
      if (report.status !== "running") {
        clearInterval(evalTimer);
        await refreshReports();
        await refreshRuns();
      }
    } catch (e) {
      clearInterval(evalTimer);
      toast(e.message);
      $("eval-button").disabled = false;
    }
  }, 1500);
}
$("report-select").addEventListener("change", () => {
  const r = reports.find((r) => r.id === $("report-select").value);
  if (r) {
    clearInterval(evalTimer);
    renderReport(r);
    if (r.status === "running") watchReport(r.id);
  }
});
$("eval-button").addEventListener("click", async () => {
  const policies = [
    ...document.querySelectorAll('input[name="eval-policy"]:checked'),
  ].map((e) => e.value);
  if (!policies.length) {
    toast("Select at least one policy.");
    return;
  }
  $("eval-button").disabled = true;
  try {
    const result = await api("/api/evaluations", {
      policies,
      suite: $("eval-suite").value,
      model: $("eval-model").value,
      seed: 42,
    });
    activeReport = { id: result.id };
    await refreshReports();
    watchReport(result.id);
  } catch (e) {
    toast(e.message);
    $("eval-button").disabled = false;
  }
});
$("download-report").addEventListener("click", () => {
  if (!activeReport) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(activeReport, null, 2)], {
      type: "application/json",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `resolvelab-evaluation-${activeReport.id.slice(0, 8)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
(async () => {
  try {
    scenarios = await api("/api/scenarios");
    renderScenarios();
    await Promise.all([refreshRuns(), refreshModels(), refreshReports()]);
    const run = new URLSearchParams(location.search).get("run");
    if (run) await loadRun(run);
  } catch (e) {
    toast("Could not connect to the local service: " + e.message);
  }
})();
