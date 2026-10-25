(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const h = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
  const graphics = ElevenGraphics.createRenderer(h);
  const number = new Intl.NumberFormat("en-US");
  const fmt = (value) => value == null ? "N/A" : number.format(value);
  const pct = (value) => value == null ? "N/A" : `${(value * 100).toFixed(1)}%`;
  const raw = (value) => value == null ? "N/A" : value.toFixed(3);
  const width = (value) => Math.max(0, Math.min(100, value ?? 0));
  const norm = (values) => Array.isArray(values) ? Math.hypot(...values) : null;
  const basename = (path) => String(path).split(/[\\/]/).pop();
  const date = (value, year = false) => new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString("en-US", {
    month: "short", day: "numeric", ...(year ? {year: "numeric"} : {})
  });
  const colors = {
    "shot-landing": "#36775a", "rally-reception": "#8aaf78", "serve-legality": "#d2b46d",
    "serve-reception": "#839fb4", "return-unspecified": "#b3a2c4", "contact-rules": "#b6bdb1",
    "unclassified": "#c4c7c1"
  };
  const labels = {
    "shot-landing": "Shot landing", "rally-reception": "Rally returns", "serve-legality": "Serve faults",
    "serve-reception": "Serve returns", "return-unspecified": "Unresolved returns",
    "contact-rules": "Contact rules", "unclassified": "Unclassified"
  };
  let data, publishing, catalogue;
  const state = {mode: "all", query: "", result: "all", page: 0, stack: []};
  const pageSize = 10;
  const view = () => data.views[state.mode];
  const scopeLabel = () => ({all: "All matches", ranked: "Ranked only", unranked: "Unranked only"}[state.mode]);
  const matches = () => data.matches.filter((match) => state.mode === "all" || match.ranked === (state.mode === "ranked"));
  function pointFor(id) {
    const match = matches().find(item => item.points.some(point => point.id === id));
    const point = match?.points.find(item => item.id === id);
    if (!point) throw new Error("This point is not available in the selected mode");
    return {match, point};
  }
  const category = (id) => view().loss_analysis.categories.find((item) => item.id === id);
  const plansFor = (recipeIds) => view().training_plan.filter((item) => item.recipe_ids.some((id) => recipeIds.includes(id)));
  const empty = (title, text) => `<div class="empty-state"><strong>${h(title)}</strong>${h(text)}</div>`;
  const table = (headers, rows) => `<table><thead><tr>${headers.map((cell) => `<th scope="col">${h(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const metric = (label, value, caption, icon = "") => `<article class="metric"><div class="metric-label">${h(label)}<span aria-hidden="true">${icon}</span></div><div class="metric-value">${h(value)}</div><p class="metric-caption">${h(caption)}</p></article>`;
  const stat = (value, label) => `<div class="dialog-stat"><strong>${h(value)}</strong><small>${h(label)}</small></div>`;
  const evidenceButton = (id, label = "View evidence") => `<button class="button small secondary" data-action="evidence" data-id="${h(id)}">${h(label)} <span aria-hidden="true">&#8599;</span></button>`;
  const resultBadge = (match) => `<span class="chip ${match.won === true ? "win" : match.won === false ? "loss" : "neutral"}">${h(match.won === true ? "Win" : match.won === false ? "Loss" : match.status)}</span>`;

  function showError(error) {
    console.error("11 Analyst dashboard:", error);
    const target = $("#app-error");
    target.textContent = `The dashboard could not complete this action: ${error.message}. Your log files have not been changed.`;
    target.hidden = false;
  }

  function renderOverview() {
    const current = view(), summary = current.summary, analysis = current.loss_analysis;
    const top = current.training_plan[0], focus = top?.category_id ? category(top.category_id) : null;
    $("#next-focus").innerHTML = `<p class="eyebrow">YOUR NEXT BEST FOCUS / ${h(scopeLabel())}</p>
      <h2>${h(focus ? top.focus : "Build a stronger sample")}</h2>
      <p>${h(focus ? `${pct(focus.share_of_lost_points)} of observed losses fall in this pattern. Start here, then reassess.` : "There is not enough repeated loss evidence to prescribe a specific technical priority.")}</p>
      <div class="focus-bottom"><div class="focus-number">${fmt(focus ? focus.category_losses : analysis.observed_points)}<small>${focus ? "observed losses in this pattern" : "validated point observations"}</small></div><a class="button light" href="#training">See training plan <span aria-hidden="true">&#8594;</span></a></div>`;
    $("#metrics").innerHTML = [
      metric("Point-win rate", pct(summary.point_win_rate), `${fmt(summary.points_won)} / ${fmt(summary.points_won + summary.points_lost)} completed-match points`, "&#8599;"),
      metric("Completed matches", fmt(summary.completed), `${fmt(summary.wins)} wins / ${fmt(summary.losses)} losses`, "&#9638;"),
      metric("Losses analysed", fmt(analysis.observed_lost_points), `Across ${fmt(analysis.observed_points)} validated points`, "&#9678;"),
      metric("Opponents observed", fmt(summary.opponents), `${fmt(summary.observed_matches)} matches in this selection`, "&#9671;")
    ].join("");
    renderLossChart();
    renderTrend();
    $("#context-strip").innerHTML = `<span class="context-icon" aria-hidden="true">i</span><span><strong>Context matters.</strong> ${summary.completed ? `${fmt(summary.higher_rated_matches)} of ${fmt(summary.completed)} completed matches were against opponents over 100 Elo higher.` : "There are no completed matches in this selection."} Loss evidence also includes ${fmt(analysis.incomplete_match_lost_points)} validated losses from unfinished matches. Overall win rate is not a skill diagnosis.</span>`;
  }

  function renderLossChart() {
    const analysis = view().loss_analysis, total = analysis.observed_lost_points;
    if (!total) {
      $("#loss-chart").innerHTML = empty("No observed losses", "There is no loss distribution to plot for this selection.");
      return;
    }
    const radius = 69, circumference = 2 * Math.PI * radius;
    let offset = 0;
    const arcs = analysis.categories.map((item) => {
      const length = circumference * item.category_losses / total;
      const arc = `<circle cx="100" cy="100" r="${radius}" fill="none" stroke="${colors[item.id] || colors.unclassified}" stroke-width="19" stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 100 100)"><title>${h(item.focus)}: ${fmt(item.category_losses)} losses (${pct(item.share_of_lost_points)})</title></circle>`;
      offset += length;
      return arc;
    }).join("");
    $("#loss-chart").innerHTML = `<div class="loss-chart-layout"><div class="donut-wrap"><svg viewBox="0 0 200 200" role="img" aria-label="${h(`${fmt(total)} lost points, grouped by logged outcome`)}">${arcs}<text class="donut-total" x="100" y="98" text-anchor="middle">${fmt(total)}</text><text class="donut-label" x="100" y="118" text-anchor="middle">lost points</text></svg></div><div class="loss-legend">${analysis.categories.map((item) => `<div class="legend-row"><i class="legend-dot" style="background:${colors[item.id] || colors.unclassified}"></i><button class="text-button legend-label" data-action="evidence" data-id="${h(item.id)}">${h(labels[item.id] || item.focus)}</button><span class="legend-number">${fmt(item.category_losses)}</span></div>`).join("")}</div></div>`;
  }

  function renderTrend() {
    const days = view().daily, available = days.filter((day) => day.point_win_rate !== null);
    $("#trend-context").textContent = "Completed-match scores, grouped by match start date. Opponent mix and small samples limit conclusions about improvement.";
    if (!available.length) {
      $("#trend-chart").innerHTML = empty("No completed-match trend", "Missing days are not treated as a zero point-win rate.");
      return;
    }
    const left = 35, right = 400, top = 12, bottom = 150;
    const x = (index) => days.length === 1 ? (left + right) / 2 : left + index * (right - left) / (days.length - 1);
    const y = (value) => bottom - value * (bottom - top);
    const points = days.map((day, index) => day.point_win_rate == null ? null : [x(index), y(day.point_win_rate), day]).filter(Boolean);
    const line = points.map(([px, py], index) => `${index ? "L" : "M"}${px},${py}`).join(" ");
    const area = points.length > 1 ? `${line} L${points[points.length - 1][0]},${bottom} L${points[0][0]},${bottom} Z` : "";
    $("#trend-chart").innerHTML = `<svg class="trend-svg" viewBox="0 0 430 190" role="img" aria-label="Point-win rate by day on a zero to one hundred percent scale">
      <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#9db98d" stop-opacity=".32"/><stop offset="100%" stop-color="#9db98d" stop-opacity=".03"/></linearGradient></defs>
      ${[0, .25, .5, .75, 1].map((tick) => `<line x1="${left}" x2="${right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#e7ece4" stroke-dasharray="3 4"/><text x="26" y="${y(tick) + 3}" text-anchor="end">${tick * 100}%</text>`).join("")}
      ${area ? `<path d="${area}" fill="url(#trend-fill)"/>` : ""}<path d="${line}" fill="none" stroke="#36775a" stroke-width="2.5" stroke-linejoin="round"/>
      ${points.map(([px, py, day]) => `<circle cx="${px}" cy="${py}" r="4" fill="#fff" stroke="#36775a" stroke-width="2"><title>${h(date(day.date))}: ${pct(day.point_win_rate)}, ${day.matches} matches</title></circle><text x="${px}" y="${py - 12}" text-anchor="middle">${pct(day.point_win_rate)}</text>`).join("")}
      ${days.map((day, index) => `<text x="${x(index)}" y="177" text-anchor="middle">${h(date(day.date))}</text>`).join("")}</svg>
      <details class="method-note"><summary>Daily values</summary><div class="table-scroll">${table(["Date", "Matches", "Point-win rate"], days.map((day) => [h(date(day.date)), fmt(day.matches), pct(day.point_win_rate)]))}</div></details>`;
  }

  function planKeyAction(plan) {
    if (plan.category_id === "serve-legality") return '<span class="caption">Manual coaching / own-serve practice. No machine key.</span>';
    if (!plan.machine_practice_eligible) return '<span class="caption">No machine key: requires five eligible return losses across two matches, excluding conflicting contacts and own serves.</span>';
    const id = `plan-${plan.category_id}`;
    if (!data.publishing.plans.some((item) => item.id === id)) return '<span class="caption">Practice template unavailable. A serve-return plan requires a verified-format serve seed.</span>';
    return `<button class="button" data-action="publish" data-id="${h(id)}">Generate Ball Machine Key</button>`;
  }

  function renderTraining() {
    const current = view(), priorities = current.training_plan.filter((plan) => plan.category_id);
    publishing.setPlans(data.publishing.plans.filter((item) => priorities.some((plan) => plan.category_id === item.category_id && plan.machine_practice_eligible)));
    $("#nav-priorities").textContent = priorities.length || "";
    $("#priority-count").textContent = `${priorities.length} evidence-backed ${priorities.length === 1 ? "priority" : "priorities"}`;
    $("#training-cards").innerHTML = priorities.length ? priorities.map((plan) => {
      const item = category(plan.category_id), supported = item.contact_evidence_counts.supported_by_final_hit || 0;
      return `<article class="training-card"><div class="training-card-top"><span class="rank-badge">${String(plan.priority).padStart(2, "0")}</span><h3>${h(plan.focus)}</h3></div>
        <div class="evidence-strip"><div class="evidence-stat">${fmt(item.category_losses)}<small>lost points</small></div><div class="evidence-stat">${pct(item.share_of_lost_points)}<small>of observed losses</small></div></div>
        <div class="share-track" aria-hidden="true"><span style="width:${width(item.share_of_lost_points * 100)}%"></span></div>
        <div class="sample-line">${fmt(item.distinct_matches)} matches / ${fmt(item.distinct_opponents)} opponents / ${fmt(supported)} with final-hit support</div>
        <p class="practice-copy">${h(plan.practice)}</p>
        ${plan.recipe_ids[0] ? graphics.intent(plan.recipe_ids[0]) : ""}
        <div class="recipe-tags">${plan.recipe_ids.map((id) => `<button class="text-button" data-action="recipe" data-id="${h(id)}">${h(data.practice.recipes.find((recipe) => recipe.id === id)?.title || id)}</button>`).join('<span aria-hidden="true"> / </span>')}</div>
        ${plan.machine_practice_eligible ? `<p class="caption">General template-based practice for ${fmt(plan.machine_practice_losses)} eligible return losses across ${fmt(plan.machine_practice_matches)} matches. Not a reproduction of an opponent's ball.</p>` : ""}
        <div class="card-footer">${evidenceButton(item.id, "Why this priority?")}${plan.recipe_ids.length ? `<button class="button small secondary" data-action="plan" data-id="${h(plan.category_id)}">Preview training shots</button>` : ""}${planKeyAction(plan)}</div></article>`;
    }).join("") : `<article class="panel">${empty("More evidence before a prescription", current.training_plan[0]?.evidence || "No classified loss pattern meets the evidence threshold.")}</article>`;
    const watch = current.loss_analysis.categories.filter((item) => !item.eligible_for_priority);
    $("#watchlist").innerHTML = watch.length ? `<div class="watchlist"><strong>Monitor, not prescribe:</strong>${watch.map((item) => `<button class="text-button" data-action="evidence" data-id="${h(item.id)}">${h(labels[item.id] || item.focus)} (${fmt(item.category_losses)})</button>`).join('<span aria-hidden="true"> / </span>')}</div>` : "";
    const opportunities = current.opponent_opportunities;
    $("#opportunity-count").textContent = `Showing ${Math.min(6, opportunities.length)} of ${opportunities.length} repeated opportunities`;
    $("#opportunity-cards").innerHTML = opportunities.length ? opportunities.slice(0, 6).map((item) => `<article class="training-card">
      <h3>${h(item.incoming_context === "serve" ? "Serve returns" : item.incoming_context === "rally" ? "Rally returns" : "Returns with unknown incoming context")} against ${h(item.opponent_name)}</h3>
      <div class="sample-line">Player ${h(item.opponent_id)} / ${fmt(item.losses)} observed losses / ${fmt(item.distinct_matches)} matches</div>
      <p>${fmt(item.missed_returns)} missed returns; ${fmt(item.failed_landings)} returns that failed to land.</p>
      ${graphics.lossSplit(item)}
      <p class="caption">Player-specific key withheld: serve/shot reproduction is not validated. No spin family is inferred.</p>
      <div class="card-footer"><button class="button secondary" data-action="opportunity" data-id="${h(item.id)}">Inspect supporting points</button></div></article>`).join("")
      : empty("No repeated opponent-specific opportunity yet", "Each opponent and incoming-context group needs five eligible return losses across two matches in this mode.");
  }

  function court(id) {
    const paths = id === "serve-returns"
      ? '<path d="M110 20 Q64 33 85 65 T65 102" stroke="#dfc484" stroke-width="2" stroke-dasharray="4 4" fill="none"/><circle cx="110" cy="20" r="5" fill="#d6b86e"/><circle cx="65" cy="102" r="6" fill="#d5ee9b" stroke="#fff"/>'
      : id === "rally-practice"
        ? '<path d="M94 24 L43 102 M94 24 L131 102" stroke="#d7edb3" stroke-width="2" stroke-dasharray="4 4"/><circle cx="94" cy="24" r="5" fill="#dfc484"/><circle cx="43" cy="102" r="6" fill="#d5ee9b" stroke="#fff"/><circle cx="131" cy="102" r="6" fill="#d5ee9b" stroke="#fff"/>'
        : '<path d="M105 20 Q69 38 83 67 L45 104 M100 28 L131 104" stroke="#d7edb3" stroke-width="2" stroke-dasharray="4 4" fill="none"/><circle cx="105" cy="20" r="5" fill="#dfc484"/><circle cx="45" cy="104" r="6" fill="#d5ee9b" stroke="#fff"/><circle cx="131" cy="104" r="6" fill="#d5ee9b" stroke="#fff"/>';
    return `<svg viewBox="0 0 180 135" aria-hidden="true"><path d="M37 38 L143 38 L170 113 L10 113 Z" fill="#4f735b" stroke="#6b8971" stroke-width="2"/><path d="M39 42 L141 42 L164 108 L16 108 Z" fill="none" stroke="#d6e4d1" stroke-width="1"/><path d="M90 42 L90 109" stroke="#d6e4d1" stroke-width=".8"/><path d="M22 74 L158 74" stroke="#f1f5df" stroke-width="2"/><path d="M22 70 L158 70" stroke="#b6caaa" stroke-width=".8"/>${paths}</svg>`;
  }

  function renderMachines() {
    const collections = data.practice.collections;
    const descriptions = {
      "serve-returns": "A predictable serve feed. Build a reliable return, then introduce controlled variation.",
      "rally-practice": "Two manageable rally locations. Land more balls before increasing pace or spread.",
      "combined": "Receive, recover, continue. A short point-like sequence with time to reset."
    };
    $("#machine-cards").innerHTML = collections.length ? collections.map((item, index) => {
      const candidate = data.practice.settings_candidates.find((entry) => entry.recipe_id === item.id);
      const linked = plansFor(item.recipe_ids);
      return `<article class="machine-card"><div class="court"><span class="court-label">${["RECEIVE", "RALLY", "PUT IT TOGETHER"][index] || "PRACTICE"}</span><span class="court-step">0${index + 1}</span>${court(item.id)}</div><div class="machine-body"><h3>${h(item.title)}</h3><p>${h(descriptions[item.id] || item.notes)}</p><div class="sequence-pills">${item.planned_sequence.map((step) => `<span>${h(step)}</span>`).join(" &#8594; ")}</div><p class="machine-support">${linked.length ? `Supports ${linked.length === 1 ? "priority" : "priorities"} ${linked.map((plan) => `#${plan.priority}`).join(", ")}` : "Optional template for this selection, not a diagnosed priority."}</p><a class="button secondary" href="#training">View return training plans</a><p class="machine-key">${candidate ? "Reference template; generate keys from eligible training plans." : "Serve template unavailable."}</p><button class="button ghost" data-action="collection" data-id="${h(item.id)}">Setup &amp; evidence</button></div></article>`;
    }).join("") : empty("No machine collections", "Run the complete analysis pipeline to generate candidate practice collections.");
    $("#recipe-library").innerHTML = `<div class="recipe-library-grid">${data.practice.recipes.map((recipe) => `<div class="recipe-library-item"><strong>${h(recipe.title)}</strong><p>${h(recipe.goal)}</p><button class="text-button" data-action="recipe" data-id="${h(recipe.id)}">Practice steps &amp; evidence</button></div>`).join("")}</div>
      <h3 style="margin-top:24px">Individual feed candidates</h3><div class="recipe-tags">${data.practice.settings_candidates.filter((candidate) => !candidate.kind).map((candidate) => `<button class="button small secondary" data-action="download" data-id="${h(candidate.recipe_id)}">${h(candidate.title)} &#8595;</button>`).join("")}</div>
      <div class="reference-links">${data.practice.methodology_sources.map((source) => `<p><strong>${h(source.title)}</strong><br>${h(source.supports)} ${h(source.caveat)}<br><a href="${safeResearchUrl(source.url)}" target="_blank" rel="noopener noreferrer">Read the methodology &#8599;</a></p>`).join("")}</div>`;
  }

  function safeResearchUrl(url) {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") throw new Error("Unsupported research link protocol");
    return h(parsed.href);
  }

  function filteredMatches() {
    return matches().filter((match) => {
      const search = `${match.opponent_name} ${match.match_id}`.toLocaleLowerCase();
      const result = state.result === "all" || (state.result === "win" && match.won === true)
        || (state.result === "loss" && match.won === false) || state.result === match.status;
      return search.includes(state.query.toLocaleLowerCase()) && result;
    }).sort((a, b) => b.first_observed.localeCompare(a.first_observed) || b.match_id.localeCompare(a.match_id));
  }

  function renderMatches() {
    const items = filteredMatches();
    state.page = Math.min(state.page, Math.max(0, Math.ceil(items.length / pageSize) - 1));
    const start = state.page * pageSize, selected = items.slice(start, start + pageSize);
    $("#match-table").innerHTML = selected.length ? table(
      ["Date", "Opponent", "Mode", "Elo gap", "Result", "Game scores", "Point coverage", ""],
      selected.map((match) => [
        `<span class="nowrap">${h(date(match.first_observed))}</span><small>${h(match.first_observed.slice(11, 16))} log time</small>`,
        `<div class="opponent-cell"><strong>${h(match.opponent_name)}</strong><small>Match ${h(match.match_id)}</small></div>`,
        `<span class="chip neutral">${match.ranked ? "Ranked" : "Unranked"}</span>`,
        `${match.elo_gap > 0 ? "+" : ""}${fmt(match.elo_gap)}<small>${fmt(match.opponent_elo)} observed Elo</small>`,
        resultBadge(match),
        `<span class="nowrap">${h(match.scores.map((score) => score.join("-")).join(" / ") || "No scores")}</span>`,
        `<span class="coverage-bar" aria-hidden="true"><span style="width:${width((match.point_coverage || 0) * 100)}%"></span></span>${pct(match.point_coverage)}`,
        `<button class="button small secondary" data-action="match" data-id="${h(match.match_id)}" aria-label="Inspect points for match ${h(match.match_id)}">Inspect points</button>`
      ])
    ) : empty("No matching matches", "Try another opponent, match ID, result, or match mode.");
    $("#match-count").textContent = items.length ? `${start + 1}-${Math.min(start + pageSize, items.length)} of ${fmt(items.length)} matches` : "0 matches";
    $("#prev-page").disabled = state.page === 0;
    $("#next-page").disabled = start + pageSize >= items.length;
  }

  function renderQuality() {
    const telemetry = view().telemetry, statuses = telemetry.point_status;
    const bounded = (statuses.bounded || 0) + (statuses.bounded_multiple_attempts || 0);
    $("#telemetry-summary").innerHTML = [
      metric("Bounded point windows", fmt(bounded), `${fmt(statuses.partial || 0)} partial / ${fmt(statuses.unavailable || 0)} unavailable in this mode`),
      metric("Your observed contacts", fmt(telemetry.player_hits), "From start/end-bounded attempts only"),
      metric("Paired incoming/outgoing", fmt(telemetry.paired_hits), "Raw ball states, not paddle motion")
    ].join("");
    $("#source-summary").innerHTML = `<p class="eyebrow">ALL INPUT FILES / NOT MODE-FILTERED</p><h3>Know your sample</h3><div class="source-numbers"><div><strong>${fmt(data.quality.input_files)}</strong><small>log files</small></div><div><strong>${fmt(data.quality.files_with_player_snapshots)}</strong><small>with player snapshots</small></div></div><p class="caption">${fmt(data.physics_diagnostics)} physics parse warnings / ${fmt(data.quality.invalid_snapshots)} invalid snapshots / ${fmt(data.quality.score_transition_gaps)} score-transition gaps. A bounded point window can still contain missing measurements.</p>`;
    $("#source-table").innerHTML = table(["Log file", "Status", "Size", "Player snapshots", "Diagnostics"], data.sources.map((source) => [
      `<span class="source-path">${h(source.name)}</span>`, h(source.status.replaceAll("_", " ")),
      `${(source.size_bytes / 1024).toFixed(1)} KB`, fmt(source.player_snapshots),
      `<div class="source-diagnostics">${source.diagnostics.length ? source.diagnostics.map(h).join("<br>") : "None recorded"}</div>`
    ]));
    $("#limits").innerHTML = `<ul>${data.limitations.map((item) => `<li>${h(item)}</li>`).join("")}</ul><h3>Observed rating values</h3><p class="caption">Snapshot observations, not a live rating or verified rating-change ledger. These observations cover all input matches.</p><div class="table-scroll">${table(["Timestamp", "Elo", "Match"], data.rating_observations.map((item) => [h(item.timestamp), fmt(item.elo), h(item.match_id)]))}</div>`;
  }

  function render() {
    renderOverview();
    renderTraining();
    renderMachines();
    renderMatches();
    renderQuality();
    renderPilot();
    catalogue?.updateScope(view());
    $("#scope-status").textContent = `${scopeLabel()}: ${view().summary.completed} completed matches, ${view().loss_analysis.observed_lost_points} observed lost points. Training priorities recalculated for this selection.`;
  }

  const pilotLabels = {
    missed_first_return: "Missed first return", first_return_failed_to_land: "First return failed to land",
    return_continued: "Opponent contacted the returned ball", point_won_on_first_return: "Point won on first return",
    unknown: "First-return outcome unknown"
  };

  function renderPilot() {
    const pilot = view().serve_reception_pilot;
    $("#pilot-evidence").innerHTML = `<div class="metric-grid">${metric("Observed receiving attempts", fmt(pilot.receiving_attempts), `${pilot.distinct_matches} matches in this selection`)}${metric("Resolved first returns", fmt(pilot.resolved_attempts), `${pct(pilot.outcome_coverage)} outcome coverage`)}${metric("Confirmed first-return failures", fmt(pilot.confirmed_failures), "Missed contact or failed first-return landing")}${metric("Failures / resolved attempts", pct(pilot.failure_fraction_of_resolved_attempts), "Selected observed sample, not an all-match error rate")}</div>
      <div class="panel"><p>Classifier ${h(pilot.classifier_version)}: provisional contact-based evidence, not independently validated in-game.</p>
      <div class="recipe-tags">${Object.entries(pilot.counts).map(([id,count])=>`<button class="button small secondary" data-action="pilot" data-id="${h(id)}">${h(pilotLabels[id])}: ${fmt(count)}</button>`).join("")}</div>
      <details class="method-note"><summary>Denominator, exclusions and uncertainty</summary>${pilot.limits.map(text=>`<p>${h(text)}</p>`).join("")}${table(["Excluded condition (units differ)", "Count"],Object.entries(pilot.exclusions).map(([key,value])=>[h(key.replaceAll("_"," ")),fmt(value)]))}</details></div>`;
  }

  function contextTable(values, label) {
    return `<div class="table-scroll">${table([label, "Observed points", "All losses", "Pattern losses", "Losses / 100 points"], Object.entries(values).map(([key, value]) => [
      h(key), fmt(value.observed_points), fmt(value.lost_points), fmt(value.category_losses),
      value.losses_per_100_observed_points == null ? "N/A" : value.losses_per_100_observed_points.toFixed(1)
    ]))}</div>`;
  }

  function dialogContent(route) {
    if (route.type === "pilot") {
      const pilot=view().serve_reception_pilot, rows=pilot.examples.filter(item=>item.outcome===route.id);
      if(!(route.id in pilotLabels))throw new Error("Unknown pilot outcome");
      return {kicker:`FIRST-RETURN PILOT / ${scopeLabel()}`,title:pilotLabels[route.id],
        body:`<p>${rows.length} observed attempts in this group. Showing the first ${Math.min(30,rows.length)} source examples; the selected-mode summary export retains all records. This is not spin, length or backhand classification.</p>
        <div class="table-scroll">${table(["Opponent","Attempt","Serve line","Point outcome",""],rows.slice(0,30).map(row=>[
          h(row.opponent_name),fmt(row.attempt),fmt(row.serve_line),row.point_won?"Won":"Lost",
          `<button class="button small secondary" data-action="point" data-id="${h(`${row.match_id}:${row.round}:${row.score[0]}:${row.score[1]}`)}">Inspect point</button>`
        ]))}</div>`};
    }
    if (route.type === "plan") {
      const plan = view().training_plan.find(item => item.category_id === route.id);
      if (!plan) throw new Error("This training plan is not available in the selected mode");
      const candidate = plan.machine_practice_eligible
        ? data.practice.settings_candidates.find(item => item.recipe_id === `plan-${plan.category_id}`) : null;
      return {
        kicker: `TRAINING GRAPHICS / ${scopeLabel()}`, title: plan.focus,
        body: `<p>${h(plan.evidence)}</p><p>${h(plan.practice)}</p>
          ${candidate ? graphics.training(candidate) : `${graphics.intent(plan.recipe_ids[0])}<p>No machine package is available for this plan in the selected mode. This is coaching guidance only.</p>`}
          <h3>Progression &amp; measurement</h3>${plan.recipe_ids.map(id => {
            const recipe = data.practice.recipes.find(item => item.id === id);
            return recipe ? `<h4>${h(recipe.title)}</h4><p>${h(recipe.volume)} ${h(recipe.success)}</p><p>${h(recipe.progression)}</p>` : "";
          }).join("")}<p>${h(plan.measure)}</p>${planKeyAction(plan)}`
      };
    }
    if (route.type === "opportunity") {
      const item = view().opponent_opportunities.find((entry) => entry.id === route.id);
      if (!item) throw new Error("This opponent opportunity is not available in the selected mode");
      return {
        kicker: `OPPONENT RETURN EVIDENCE / ${scopeLabel()}`, title: `Returns against ${item.opponent_name}`,
        body: `<p>${fmt(item.losses)} observed return losses across ${fmt(item.distinct_matches)} matches. Incoming context: ${h(item.incoming_context)}.</p>
          <p>${h(item.limitation)} More losses can reflect more play against this opponent or stronger opposition, not a higher error probability.</p>
          <p>Exact serve families and calibrated launcher parameters are not established. A generic preset will not be presented as this player's serve.</p>
          <div class="table-scroll">${table(["Match", "Round", "Score", "Source", "Incoming hit line", ""], item.examples.map((example) => [
            h(example.match_id), fmt(example.round), h(example.score.join("-")),
            `${h(basename(example.source))}:${example.line}`, example.incoming_hit_source_line == null ? "Unknown" : fmt(example.incoming_hit_source_line),
            `<button class="button small secondary" data-action="point" data-id="${h(`${example.match_id}:${example.round}:${example.score[0]}:${example.score[1]}`)}">Inspect point</button>`
          ]))}</div>`
      };
    }
    if (route.type === "evidence") {
      const item = category(route.id);
      if (!item) throw new Error("This loss pattern is not available in the selected mode");
      const plan = view().training_plan.find((entry) => entry.category_id === item.id);
      return {
        kicker: `POINT-LOSS EVIDENCE / ${scopeLabel()}`, title: item.focus,
        body: `<div class="dialog-stats">${stat(fmt(item.category_losses), "observed lost points")}${stat(pct(item.share_of_lost_points), "share of losses")}${stat(fmt(item.distinct_matches), "matches")}${stat(fmt(item.distinct_opponents), "opponents")}</div>
          <p>${h(item.interpretation)}</p><p class="reason-label">${item.priority ? `Priority #${item.priority}, ranked by observed loss count.` : "Monitoring item: insufficient repeated evidence or an unsupported reason; no technical prescription."} These counts do not estimate recoverable points.</p>
          ${item.id === "shot-landing" ? `<h3>What the contact records support</h3><p>Net contact after your final observed hit: <strong>${fmt(item.net_contact_observed)}</strong> losses. Not recorded: ${fmt(item.net_contact_not_observed)}. Unknown: ${fmt(item.net_contact_unknown)}. No recorded net contact does not establish a long or wide miss.</p>` : ""}
          <div class="table-scroll">${table(["Contact corroboration", "Losses"], Object.entries(item.contact_evidence_counts).map(([key, value]) => [h(key.replaceAll("_", " ")), fmt(value)]))}</div>
          <h3>Opponent-strength context</h3><p>Similar means within 100 Elo, inclusive, using first observed match ratings. Losses per 100 points are not shot-error rates.</p>${contextTable(item.by_opponent_strength, "Opponent band")}
          <h3>Match-mode context</h3>${contextTable(item.by_mode, "Mode")}
          <h3>Trace the evidence</h3><div class="table-scroll">${table(["Match", "Round", "Recorded score", "Source line", ""], item.examples.map((example) => [
            h(example.match_id), fmt(example.round), h(example.score.join("-")),
            `<span class="source-path">${h(basename(example.source))}:${example.line}</span>`,
            `<button class="button small secondary" data-action="point" data-id="${h(`${example.match_id}:${example.round}:${example.score[0]}:${example.score[1]}`)}">Inspect point</button>`
          ]))}</div>
          <h3>Logged reasons</h3><div class="table-scroll">${table(["Reason", "Lost points"], Object.entries(item.raw_reason_counts).map(([key, value]) => [h(key), fmt(value)]))}</div>
          ${plan ? `<h3>Suggested practice</h3><p>${h(plan.practice)}</p><h3>How to reassess</h3><p>${h(plan.measure)}</p>${planKeyAction(plan)}` : ""}`
      };
    }
    if (route.type === "match") {
      const match = matches().find((item) => item.match_id === route.id);
      if (!match) throw new Error("This match is not available in the selected mode");
      return {
        kicker: `MATCH ${match.match_id} / ${match.ranked ? "RANKED" : "UNRANKED"}`, title: `Against ${match.opponent_name}`,
        body: `<div class="dialog-stats">${stat(match.won === true ? "Win" : match.won === false ? "Loss" : match.status, "recorded result")}${stat(fmt(match.points.length), "observed point transitions")}${stat(pct(match.point_coverage), "score-transition coverage")}</div>
          <p>Game scores (you-opponent): <strong>${h(match.scores.map((score) => score.join("-")).join(" / ") || "Not recorded")}</strong>. Point scores below retain participant order from the logs.</p>
          ${match.issues.length ? `<div class="notice">${match.issues.map(h).join("<br>")}</div>` : ""}
          <p>${fmt(match.score_transition_gaps)} score-transition gaps. Inspect a point for raw reasons, measurements, and source provenance.</p>
          <div class="table-scroll">${table(["Round", "Recorded score", "Outcome", "Loss pattern", "Boundaries", "Your hits", ""], match.points.map((point) => [
            fmt(point.round), h(point.score.join("-")),
            `<span class="chip ${point.winner_id === data.player.id ? "win" : "loss"}">${point.winner_id === data.player.id ? "Won" : "Lost"}</span>`,
            h(point.loss ? labels[point.loss.category] || point.loss.category : "-"),
            h((point.telemetry.status || "unavailable").replaceAll("_", " ")),
            fmt(point.telemetry.observed_player_hits ?? 0),
            `<button class="button small secondary" data-action="point" data-id="${h(point.id)}">View</button>`
          ]))}</div>`
      };
    }
    if (route.type === "point") {
      const {match, point} = pointFor(route.id);
      const telemetry = point.telemetry, own = point.winner_id === data.player.id;
      return {
        kicker: `MATCH ${match.match_id} / ROUND ${point.round}`, title: `${own ? "Point won" : "Point lost"} at ${point.score.join("-")} (recorded order)`,
        body: `<p class="reason-label"><strong>Logged reason:</strong> ${h(point.reason)}</p>
          ${point.loss ? `<p><strong>${h(labels[point.loss.category] || point.loss.category)}</strong>. ${h(point.loss.interpretation)}</p>` : "<p>This point was won by the selected player and does not contribute to their loss priorities.</p>"}
          <div class="dialog-stats">${stat(fmt(telemetry.observed_player_hits ?? 0), "your observed hits")}${stat(fmt(telemetry.observed_opponent_hits ?? 0), "opponent hits")}${stat(fmt(telemetry.paired_player_hits ?? 0), "paired incoming/outgoing")}${stat(fmt(telemetry.attempts ?? 0), "attempts")}</div>
          <p>Boundary status: <strong>${h(telemetry.status || "unavailable")}</strong>. Measurements: ${h(telemetry.measurement_status || "unavailable")}. Counts are observed contacts, not guaranteed rally lengths.</p>
          ${(telemetry.issues || []).length ? `<div class="notice">${telemetry.issues.map(h).join("<br>")}</div>` : ""}
          ${graphics.pointBrowser(point, data.player.id, route.shotIndex)}
          <h3>Recorded contacts &amp; ball states</h3><p>Speed magnitudes below are raw log units, not m/s or km/h. Ball orientation is not paddle orientation.</p>
          <div class="table-scroll">${table(["Attempt", "Event", "Who / type", "Phase", "Incoming speed (raw)", "Outgoing speed (raw)", "Log line", ""], point.events.map((event, index) => [
            fmt(event.attempt), h(event.kind),
            h(event.kind === "hit" ? event.actor_id === data.player.id ? "You" : event.actor_id ? "Opponent" : "Unattributed" : event.collision_type || "-"),
            h(event.phase || "-"), raw(norm(event.before?.velocity)), raw(norm(event.after?.velocity)), fmt(event.line),
            ["hit", "collision"].includes(event.kind) ? `<button class="button small secondary" data-action="select-shot" data-id="${index}">Show graphic</button>` : ""
          ]))}</div>
          <h3>Source provenance</h3><p class="source-path">${h(point.source)}<br>Score snapshot line ${point.line}; ${h(point.timestamp)} (log-local time).</p>
          <details><summary>Raw vectors and event metadata</summary><pre>${h(JSON.stringify({source: point.source, score_snapshot_line: point.line, events: point.events}, null, 2))}</pre></details>`
      };
    }
    if (route.type === "recipe") {
      const recipe = data.practice.recipes.find((item) => item.id === route.id);
      if (!recipe) throw new Error("This practice recipe is not available");
      const linked = plansFor([recipe.id]);
      const candidate = data.practice.settings_candidates.find(item => item.recipe_id === recipe.id)
        || (recipe.id === "serve-reception" ? data.practice.settings_candidates.find(item => item.recipe_id === "serve-returns") : null);
      return {
        kicker: `PRACTICE RECIPE / ${scopeLabel()}`, title: recipe.title,
        body: `<p>${h(recipe.goal)}</p><h3>Why practise this?</h3>${linked.length ? linked.map((plan) => `<p><strong>Priority #${plan.priority}:</strong> ${h(plan.evidence)}</p>`).join("") : "<p>This is an optional progression for the selected mode, not an established loss priority.</p>"}
          ${recipe.setup_note ? `<div class="notice">${h(recipe.setup_note)}</div>` : ""}
          ${candidate ? graphics.training(candidate, recipe.id === "serve-reception" ? {planned_sequence: ["serve"]} : null) : graphics.intent(recipe.id)}
          <div class="table-scroll">${table(["Feed", "Origin", "Landing target", "Spin", "Variation"], recipe.sequence.map((step) => [fmt(step.feed), h(step.launch_origin), h(step.landing_target), h(step.spin), h(step.variation)]))}</div>
          ${["ordering", "cadence", "volume", "success", "progression"].map((key) => `<h3>${h(key[0].toUpperCase() + key.slice(1))}</h3><p>${h(recipe[key])}</p>`).join("")}
          <p class="caption">Practice targets are coaching proposals. Machine settings are template-based candidates, not a fitted recreation of a recorded failure.</p>`
      };
    }
    if (route.type === "collection") {
      const item = data.practice.collections.find((entry) => entry.id === route.id);
      if (!item) throw new Error("This collection is not available");
      const candidate = data.practice.settings_candidates.find((entry) => entry.recipe_id === item.id), linked = plansFor(item.recipe_ids);
      return {
        kicker: `BALL-MACHINE COLLECTION / ${scopeLabel()}`, title: item.title,
        body: `<p class="reason-label">Planned sequence: ${h(item.planned_sequence.join(" -> "))}. Status: ${h(item.status)}.</p><p>${h(item.notes)}</p>
          <h3>Training evidence</h3>${linked.length ? linked.map((plan) => `<p><strong>Priority #${plan.priority}: ${h(plan.focus)}</strong><br>${h(plan.evidence)}</p>`).join("") : "<p>No qualifying loss priority links to this template in the current selection. It remains an optional practice progression.</p>"}
          <h3>Before using it</h3><ol>${(data.practice.calibration_steps || []).map((step) => `<li>${h(step)}</li>`).join("")}</ol>
          ${candidate ? graphics.training(candidate, item) : ""}
          ${candidate ? `<p>${h(candidate.changes_from_seed)}</p><p>Generate general-practice keys from eligible return training plans, not reference collections.</p><details><summary>Advanced: reference JSON</summary><button class="button secondary" data-action="download" data-id="${h(item.id)}">Download reference settings</button></details>` : "<div class='notice'>No verified-format serve seed was found, so no serve or combined settings were generated.</div>"}
          ${item.serve_seed ? `<h3>Serve-seed provenance</h3><p class="source-path">${h(item.serve_seed.source)}<br>Line ${item.serve_seed.line}; preset ${h(item.serve_seed.preset_name)} (${h(item.serve_seed.preset_id)}).</p>` : ""}
          <p class="caption">Back up existing game settings. Shape validation is not proof of in-game import compatibility, feed order, or bounce legality.</p>`
      };
    }
    throw new Error("Unknown detail view");
  }

  function showDialog(route, push = true) {
    const content = dialogContent(route), dialog = $("#detail-dialog");
    if (push) state.stack.push(route);
    $("#dialog-kicker").textContent = content.kicker;
    $("#dialog-title").textContent = content.title;
    $("#dialog-body").innerHTML = content.body;
    $("#dialog-back").hidden = state.stack.length < 2;
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
    $("#dialog-title").focus();
  }

  function downloadJson(filename, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function action(event) {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const {action: type, id} = button.dataset;
    if (type === "select-shot") {
      selectShot(Number(id));
      $("#shot-event").focus();
      $("#recorded-shot-graphic").scrollIntoView({block: "nearest"});
    } else if (type === "download") {
      const candidate = data.practice.settings_candidates.find((item) => item.recipe_id === id);
      if (!candidate || !/^[a-z0-9-]+$/.test(id)) throw new Error("This candidate settings file is unavailable");
      downloadJson(`${id}.candidate.json`, candidate.settings);
    } else if (type === "publish") {
      if ($("#detail-dialog").open) $("#detail-dialog").close();
      publishing.select(id);
    } else if (type === "export") {
      downloadJson(`11-analyst-${state.mode}-summary.json`, {
        format: "11analyst.dashboard-summary", generated_at: data.generated_at,
        player: data.player, match_mode: state.mode, ...view()
      });
    } else {
      showDialog({type, id});
    }
  }

  function selectShot(index) {
    const route = state.stack.at(-1);
    if (route?.type !== "point" || !Number.isInteger(index)) throw new Error("No recorded point is selected");
    const {point} = pointFor(route.id);
    const markup = graphics.recorded(point, index, data.player.id);
    route.shotIndex = index;
    $("#shot-event").value = String(index);
    $("#recorded-shot-graphic").innerHTML = markup;
  }

  try {
    data = JSON.parse($("#dashboard-data").textContent);
    const name = data.player.observed_names.join(", ") || data.player.id;
    $("#sidebar-name").textContent = name;
    $(".avatar").textContent = (name.match(/[A-Z]/g)?.join("").slice(0, 2) || name.slice(0, 2)).toUpperCase();
    $("#profile-label").textContent = `${name.toUpperCase()} / PLAYER ${data.player.id}`;
    const dates = data.matches.map((match) => match.first_observed).sort();
    $("#date-range").textContent = dates.length ? `${date(dates[0])} - ${date(dates[dates.length - 1], true)} / Recorded match sample` : "No recorded matches";
    $("#generated-at").textContent = `Generated ${new Date(data.generated_at).toLocaleString("en-US")}`;
    $("#mode").addEventListener("change", () => {
      state.mode = $("#mode").value;
      state.page = 0;
      try { render(); } catch (error) { showError(error); }
    });
    $("#match-search").addEventListener("input", () => {
      state.query = $("#match-search").value.trim();
      state.page = 0;
      renderMatches();
    });
    $("#result-filter").addEventListener("change", () => {
      state.result = $("#result-filter").value;
      state.page = 0;
      renderMatches();
    });
    $("#prev-page").addEventListener("click", () => { state.page -= 1; renderMatches(); });
    $("#next-page").addEventListener("click", () => { state.page += 1; renderMatches(); });
    document.addEventListener("click", (event) => { try { action(event); } catch (error) { showError(error); } });
    $("#dialog-close").addEventListener("click", () => $("#detail-dialog").close());
    $("#detail-dialog").addEventListener("change", event => {
      if (event.target.id === "shot-event") {
        try { selectShot(Number(event.target.value)); } catch (error) { showError(error); }
      }
    });
    $("#detail-dialog").addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        $("#detail-dialog").close();
      }
    });
    $("#detail-dialog").addEventListener("close", () => { state.stack = []; });
    $("#dialog-back").addEventListener("click", () => {
      state.stack.pop();
      try { showDialog(state.stack[state.stack.length - 1], false); } catch (error) { showError(error); }
    });
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        document.querySelectorAll(".nav-link").forEach((link) => {
          const active = link.getAttribute("href") === `#${entry.target.id}`;
          link.classList.toggle("active", active);
          if (active) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        });
      }
    }, {rootMargin: "-8% 0px -75% 0px"});
    document.querySelectorAll("main > .section").forEach((section) => observer.observe(section));
    publishing = ElevenPublishing.initialize({
      playerId: data.player.id, collections: data.publishing.plans,
      candidates: data.practice.settings_candidates, hashes: data.publishing.candidate_sha256,
      downloadJson, onChange: () => { renderTraining(); renderMachines(); }, service: data.publishing.service,
      renderPreview: candidate => graphics.training(candidate)
    });
    render();
    ElevenSpin.initialize(showError);
    ElevenPilot.initialize(data, downloadJson, showError);
    catalogue = ElevenCatalogue.initialize({
      catalogue: data.shot_catalogue, player: data.player, scope: view(), h, downloadJson, onError: showError
    });
  } catch (error) {
    showError(error);
  }
})();
