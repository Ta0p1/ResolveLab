/* Recorded evidence only. Every displayed metric comes from the audited reports. */
let httpEvidence;
const httpNames = {
  "base-test": "Qwen3 0.6B · one-shot",
  "large-test": "Qwen3 1.7B · one-shot",
  "sft-3407-test": "0.6B LoRA · seed 3407",
  "sft-42-test": "0.6B LoRA · seed 42",
  "sft-2026-test": "0.6B LoRA · seed 2026",
  "ollama-4b-test": "Qwen3 4B · Ollama control",
};
const httpPct = (x) => `${(100 * x).toFixed(1)}%`;

async function loadHTTPStudy() {
  httpEvidence = await api("/static/http-experiment.json");
  const entries = Object.entries(httpEvidence.reports);
  const control = httpEvidence.supplementary.summary;
  const allEntries = [
    ...entries,
    ["ollama-4b-test", httpEvidence.supplementary],
  ];
  const trained = entries.filter(([name]) => name.startsWith("sft-"));
  const rates = trained.map(([, r]) => r.summary.success_rate);
  const rateRange =
    Math.min(...rates) === Math.max(...rates)
      ? httpPct(rates[0])
      : `${(100 * Math.min(...rates)).toFixed(1)}–${httpPct(Math.max(...rates))}`;
  const valid = entries.every(([, r]) => r.summary.schema_valid_rate === 1);
  const table = entries
    .map(([name, r]) => {
      const s = r.summary;
      return `<tr><td><strong>${esc(httpNames[name])}</strong></td><td class="score">${s.passed}/${s.episodes}<span class="bar"><i style="width:${100 * s.success_rate}%"></i></span></td><td>${httpPct(s.schema_valid_rate)}</td><td>${s.unsafe_mutations}</td><td>${s.false_successes}</td><td>${s.redundant_commits}</td><td>${s.mean_tools.toFixed(1)}</td><td>${s.median_seconds.toFixed(2)}s</td></tr>`;
    })
    .join("");
  const seeds = httpEvidence.lock.training_seeds.map((seed) => [
    String(seed),
    httpEvidence.training[String(seed)],
  ]);
  const maxLoss = Math.max(
    ...seeds.flatMap(([, t]) => t.steps.map((s) => s.loss)),
  );
  const colors = ["#24765d", "#5683b3", "#b47e3b"];
  const curves = seeds
    .map(([seed, t], i) => {
      const points = t.steps
        .map(
          (s, n) =>
            `${35 + (525 * n) / Math.max(1, t.steps.length - 1)},${155 - (120 * s.loss) / maxLoss}`,
        )
        .join(" ");
      return `<polyline points="${points}" fill="none" stroke="${colors[i]}" stroke-width="2"><title>Seed ${seed}</title></polyline>`;
    })
    .join("");
  const familyRows = httpEvidence.manifest.splits.test.templates
    .map((t) => {
      const cells = entries
        .map(([, r]) => {
          const rows = r.rows.filter((x) => x.template === t.id);
          return `<td>${rows.filter((x) => x.passed).length}/${rows.length}</td>`;
        })
        .join("");
      return `<tr><td>${esc(t.faults.join(" + "))}</td>${cells}</tr>`;
    })
    .join("");
  const recordRows = httpEvidence.manifest.splits.test.seeds
    .map((seed) => {
      const cells = allEntries
        .map(([, r]) => {
          const rows = r.rows.filter((x) => x.seed === seed);
          return `<td>${rows.filter((x) => x.passed).length}/${rows.length}</td>`;
        })
        .join("");
      return `<tr><td>Record seed ${seed}</td>${cells}</tr>`;
    })
    .join("");
  $("http-study-results").innerHTML = `
    <div class="state-grid experiment-stats">
      <div class="stat"><span>FROZEN TEST</span><strong>30</strong><small>10 compositions × 3 record seeds</small></div>
      <div class="stat"><span>TRAINING SEEDS</span><strong>${seeds.length}</strong><small>All reported, no best-seed selection</small></div>
      <div class="stat"><span>LoRA SUCCESS RANGE</span><strong>${rateRange}</strong><small>Independent final-state checks</small></div>
      <div class="stat"><span>STRUCTURED CALLS</span><strong>${valid ? "100%" : "See table"}</strong><small>Measured across five primary arms</small></div>
    </div>
    <section class="panel"><div class="results-header"><div><h2>Same grammar. Different decisions.</h2><p>One-shot prompt · static JSON Schema · 24 actions · 8192 context tokens · no hidden recovery.</p></div><span class="outline-badge">150 MODEL EPISODES</span></div>
      <div class="table-note"><strong>JSON structure is controlled.</strong> A legal call can still select the wrong ticket, copy an ETag incorrectly, or claim success too early. The grader checks those outcomes separately.</div>
      <div class="table-scroll"><table><thead><tr><th>MODEL / POLICY</th><th>PASS / TOTAL</th><th>VALID CALLS</th><th>UNSAFE WRITES</th><th>FALSE SUCCESS</th><th>REDUNDANT WRITES</th><th>MEAN TOOLS</th><th>MEDIAN TIME</th></tr></thead><tbody>${table}</tbody></table></div>
      <div class="table-note">Pass includes verified resolution and justified permission escalation. Larger and smaller models share budgets, not compute cost. See the report for paired intervals and failure categories.</div>
    </section>
    <section class="panel guide-card experiment-details"><h2>Supplementary 4B control</h2><p><strong>Qwen3 4B · Q4_K_M · Ollama:</strong> ${control.passed}/${control.episodes} passed · ${httpPct(control.schema_valid_rate)} valid calls · ${control.unsafe_mutations} unsafe writes · ${control.false_successes} false success claims · ${control.median_seconds.toFixed(2)}s median.</p><p>Same instructions, example, schema and nominal budgets. Quantization, backend, chat template and grammar engine differ. These 30 additional episodes are a practical reference, not a matched LoRA training effect. All are available in the inspector below.</p></section>
    <div class="guide-grid experiment-details"><section class="panel guide-card"><h2>Three training runs</h2><svg class="loss-chart" viewBox="0 0 600 190" role="img" aria-label="Action loss for all three training seeds"><path d="M35 20V155H565" fill="none" stroke="#cbd5ce"/>${curves}<text x="35" y="15">${maxLoss.toFixed(3)} loss</text><text x="35" y="178">First optimizer step</text><text x="450" y="178">Final step</text></svg><p>${seeds.map(([seed, t], i) => `<span style="color:${colors[i]}">● ${seed}: ${esc(t.selected_checkpoint)}</span>`).join(" · ")}</p><p>Checkpoint selection uses development loss only. ${seeds[0][1].examples.train} verified training actions; all three seeds use the same data.</p></section>
    <section class="panel guide-card"><h2>The second service</h2><p>CaseDesk exposes paginated ticket reads, conditional PATCH requests, idempotency keys and permission checks over actual HTTP sockets.</p><p>The fault injector can return 412, 429 or a 502 after committing. The agent must choose its recovery from observations; the decoder does not know the current state.</p><p class="experiment-hash">Frozen manifest<br><code>${esc(httpEvidence.lock.manifest_sha256)}</code></p><a class="text-button" href="https://github.com/Ta0p1/ResolveLab/blob/main/docs/httpdesk-protocol.md" target="_blank" rel="noopener">Read the registered protocol ↗</a></section></div>
    <h2 class="episode-heading">Results by fault composition</h2><section class="panel table-scroll"><table><thead><tr><th>COMPOSITION</th><th>0.6B BASE</th><th>1.7B BASE</th><th>LoRA 3407</th><th>LoRA 42</th><th>LoRA 2026</th></tr></thead><tbody>${familyRows}</tbody></table></section>
    <h2 class="episode-heading">Check the record variants, too</h2><section class="panel"><div class="table-note">The same three record seeds appear under all ten fault compositions. These are 30 episodes, not 30 independent customer requests. A weakness on one record can affect ten outcomes. Low training loss does not establish rollout reliability.</div><div class="table-scroll"><table><thead><tr><th>RECORD VARIANT</th><th>0.6B BASE</th><th>1.7B BASE</th><th>LoRA 3407</th><th>LoRA 42</th><th>LoRA 2026</th><th>4B CONTROL</th></tr></thead><tbody>${recordRows}</tbody></table></div></section>
    <h2 class="episode-heading">Inspect every model episode</h2>
    <section class="panel http-inspector"><div class="http-pickers"><label>Model<select id="http-model">${allEntries.map(([name]) => `<option value="${esc(name)}">${esc(httpNames[name])}</option>`).join("")}</select></label><label>Test episode<select id="http-case"></select></label></div><div id="http-trace"></div></section>`;
  $("http-model").addEventListener("change", loadHTTPCases);
  $("http-case").addEventListener("change", renderHTTPTrace);
  loadHTTPCases();
}

function loadHTTPCases() {
  const report =
    $("http-model").value === "ollama-4b-test"
      ? httpEvidence.supplementary
      : httpEvidence.reports[$("http-model").value];
  $("http-case").innerHTML = report.rows
    .map(
      (r) =>
        `<option value="${esc(r.trace)}">${r.passed ? "PASS" : "FAIL"} · ${esc(r.template.replace("test_", ""))} · ${r.seed}</option>`,
    )
    .join("");
  renderHTTPTrace();
}

function renderHTTPTrace() {
  const model = $("http-model").value;
  const file = $("http-case").value;
  const trace = httpEvidence.previews[model][file];
  const verdict = trace.verdict;
  const actions = trace.observations
    .map((o, i) => {
      const request = trace.http_client[i];
      const status = o.result.status ?? "END";
      const route = request
        ? `${request.method} ${request.path}`
        : "Terminal claim";
      return `<details class="http-action"><summary><span class="step-index">${String(i + 1).padStart(2, "0")}</span><strong>${esc(o.name)}</strong><span class="http-route">${esc(route)}</span><span class="http-status ${Number(status) >= 400 ? "http-error" : ""}">${esc(status)}</span></summary><div class="http-payload"><div><span class="eyebrow">MODEL ARGUMENTS</span><pre>${esc(JSON.stringify(o.arguments, null, 2))}</pre></div><div><span class="eyebrow">HTTP OBSERVATION</span><pre>${esc(JSON.stringify(o.result, null, 2))}</pre></div></div></details>`;
    })
    .join("");
  $("http-trace").innerHTML =
    `<div class="table-note"><strong>${verdict.passed ? "Verified pass" : "Failed outcome"}</strong> · ${esc(verdict.failure_category || verdict.claim)}<p>${esc(trace.task)}</p><span>Exact state: ${verdict.exact_state ? "yes" : "no"} · Fresh verification: ${verdict.fresh_verification ? "yes" : "no"} · Committed writes: ${verdict.commits}</span></div>${actions}<details class="http-action"><summary>Compare initial and final records</summary><div class="http-payload"><pre>${esc(JSON.stringify(trace.initial_state, null, 2))}</pre><pre>${esc(JSON.stringify(trace.final_state, null, 2))}</pre></div></details><p class="hint">Recorded model execution. <a class="text-button" target="_blank" rel="noopener" href="https://github.com/Ta0p1/ResolveLab/blob/main/artifacts/v0.3/${encodeURIComponent(model)}/${encodeURIComponent(file)}">Full raw trace and token output ↗</a></p>`;
}
