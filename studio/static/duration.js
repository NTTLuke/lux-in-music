"use strict";

// Model-backed duration advice. Only the summary reaches this UI; plans stay on the local server.
const Duration = (() => {
  let analysis = null, sending = false;
  const enabled = () => Boolean(Settings.capability().duration_analysis) && $("duration-mode").value !== "cap";
  const busy = () => sending || analysis && ["queued", "running"].includes(analysis.job.status);
  function signature() {
    const { title, ...inputs } = songInputs();
    return JSON.stringify({ inputs, profile: Settings.profileKey(), mode: $("duration-mode").value,
      random: $("seed-random").checked, seed: $("seed").value });
  }
  const matches = () => analysis && analysis.signature === signature();
  const ready = () => enabled() && matches() && analysis.job.status === "done" && analysis.job.result.status === "ready";

  function refresh() {
    const active = enabled();
    $("duration-guide").hidden = !active;
    $("analyze-duration").disabled = !Settings.ready() || Boolean(busy());
    $("analyze-duration").textContent = analysis ? "Analyze again" : "Analyze duration";
    $("go").disabled = !Settings.ready() || state.submitting || Boolean(busy()) ||
      active && matches() && analysis.job.status === "done" && analysis.job.result.status !== "ready";
    $("go-label").textContent = busy() ? "Analyzing duration…" : active && !ready() ? "Analyze duration" :
      state.variations > 1 ? `Create ${state.variations} variations` : "Create";
    if (!active) return;
    let html;
    if (busy()) {
      const queued = analysis?.job.status === "queued" && !sending;
      html = `<div class="duration-status working"><h3>${queued ? "Waiting for the model" : "Analyzing your song"}</h3>
        <p>${queued ? "Your analysis is queued behind the current task." : "The model is writing a musical plan from your lyrics and style. We check its length and ending before generating audio."}</p>
        <p>This takes model processing time. The first analysis may take longer while the model loads.</p>
        <progress aria-label="Duration analysis in progress"></progress>
        <small id="analysis-elapsed" aria-live="off">${queued ? "Waiting in queue" : "Preparing the arrangement…"}</small>
        ${analysis ? '<button type="button" class="btn" data-duration="cancel">Cancel analysis</button>' : ""}</div>`;
    } else if (analysis && !matches()) {
      html = '<div class="duration-status"><h3>Your inputs changed</h3><p>Analyze again to check the new text, style or settings. The previous estimate belongs to the earlier arrangement.</p></div>';
    } else if (analysis?.job.status === "cancelled") {
      html = '<div class="duration-status"><h3>Analysis cancelled</h3><p>Analyze again when you are ready. No song was created.</p></div>';
    } else if (analysis?.job.status === "error") {
      html = `<div class="duration-status warning"><h3>${analysis.job.stale ? "Analyze again before creating" : "We could not estimate this arrangement"}</h3><p>${esc(analysis.job.error)}</p><p>${analysis.job.stale ? "Analyze again to prepare a fresh matching arrangement." : "Try again, or simplify the style and use clear verse, chorus and outro tags."}</p></div>`;
    } else if (analysis?.job.status === "done") {
      const result = analysis.job.result, short = result.status === "too_short", long = result.status === "too_long";
      const advice = short ? `Your ${fmt(result.selected_target_s)} target is too short for this plan. The ${result.supplied_score ? "supplied score" : "vocal passages and ending"} need about ${fmt(result.planned_duration_s)}.` :
        long ? `This plan needs about ${fmt(result.planned_duration_s)}, beyond this model's ${fmt(result.max_target_s)} complete-song limit.` :
        "The arrangement is ready. Create the song to use this plan; it will not be planned a second time.";
      html = `<div class="duration-status ${short || long ? "warning" : "ready"}">
        <h3>${short ? "Choose a longer duration" : long ? "This arrangement is too long" : `Estimated song duration · ${fmt(result.planned_duration_s)}`}</h3>
        <p>${advice}</p><div class="duration-facts"><span>${result.bpm} BPM</span>${result.recommended_target_s ? `<span>Suggested target · ${fmt(result.recommended_target_s)}</span>` : ""}</div>
        ${result.removed_instrumental_bars ? '<p>Some instrumental passages were shortened. Vocal passages and the final bars were kept.</p>' : ""}
        ${short || long ? `<p>${result.supplied_score ? long ? "Shorten your score, then analyze again." : "Use a longer duration or edit your score." : result.instrumental ? "Ask for a compact arrangement with shorter instrumental sections in the style, then analyze again." : long ? "Remove a repeated chorus or shorten a verse. Ask for a compact arrangement with a short intro and outro, then analyze again." : "Use the suggested duration to give this arrangement enough room. For a shorter song, remove a repeated chorus or shorten a verse, then analyze again."}</p>
        <div class="duration-actions">${short ? '<button type="button" class="btn primary" data-duration="suggested">Use suggested duration</button>' : ""}
        <button type="button" class="btn" data-duration="lyrics">${result.supplied_score ? "Edit score" : "Edit lyrics"}</button>
        ${!result.supplied_score ? '<button type="button" class="btn" data-duration="style">Edit style</button>' : ""}</div>` : ""}
        <p class="duration-note">This is the plan's estimated length. The sung performance can vary; an exact final duration is not guaranteed.</p>
        ${state.variations > 1 ? '<p class="duration-note">All variations use this arrangement with different performance seeds.</p>' : ""}</div>`;
    } else {
      html = '<div class="duration-status"><h3>Find a duration that fits your song</h3><p>Analyze first to get a duration based on the musical arrangement, including vocals, pauses and the ending. You will review the result before creating audio.</p></div>';
    }
    if ($("duration-feedback").innerHTML !== html) $("duration-feedback").innerHTML = html;
    tick();
  }

  async function analyze() {
    if (busy() || !$("form").reportValidity()) return;
    $("form-error").textContent = "";
    sending = true;
    analysis = null;
    const seed = $("seed-random").checked ? Math.floor(Math.random() * 2 ** 31) : Number($("seed").value);
    const key = signature();
    refresh();
    try {
      const response = await fetch("/api/duration-analysis", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...songInputs(), seed }) });
      const job = await response.json();
      if (!response.ok) throw new Error(typeof job.detail === "string" ? job.detail : "Check your inputs and analyze again.");
      analysis = { job, seed, signature: key, takes: 0 };
    } catch (error) {
      analysis = { job: { status: "error", error: error.message }, signature: key };
    } finally {
      sending = false;
      refresh(); pollJobs();
      $("duration-guide").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function onJobs(jobs) {
    if (!analysis?.job.id) return;
    const job = jobs.find((j) => j.id === analysis.job.id);
    if (job) analysis.job = job;
    else analysis.job = { status: "error", stale: true, error: "This analysis is no longer available. Analyze again." };
    refresh();
  }
  function tick() {
    const el = $("analysis-elapsed"), job = analysis?.job;
    if (el && job?.status === "running") el.textContent = `Preparing the musical plan · ${fmt(Math.max(0, Date.now() / 1000 - job.started))} elapsed`;
  }
  function setup() {
    $("analyze-duration").onclick = analyze;
    $("form").addEventListener("input", refresh);
    $("form").addEventListener("change", refresh);
    $("duration-feedback").onclick = async (event) => {
      const action = event.target.closest("[data-duration]")?.dataset.duration;
      if (action === "cancel" && analysis?.job.id) {
        const response = await fetch(`/api/jobs/${analysis.job.id}/cancel`, { method: "POST" });
        if (response.ok) analysis.job = await response.json();
        refresh(); pollJobs();
      }
      if (action === "suggested" && matches()) {
        const result = analysis.job.result;
        $("duration-mode").value = "target"; $("len").value = result.recommended_target_s;
        result.selected_target_s = result.recommended_target_s; result.status = "ready";
        analysis.signature = signature(); updateDurationUI();
        $("go").focus({ preventScroll: true });
      }
      if (action === "lyrics" || action === "style") {
        const el = action === "lyrics" && analysis?.job.result?.supplied_score ? $("abc") : $(action);
        if (el === $("abc")) el.closest("details").open = true;
        el.focus(); el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    };
  }
  return { setup, enabled, ready, analyze, refresh, onJobs, tick,
    seed: () => ready() ? analysis.seed + ($("seed-random").checked ? analysis.takes : 0) : null,
    created: () => { if (ready()) analysis.takes++; },
    unavailable: (message) => { if (analysis) analysis.job = { status: "error", stale: true, error: message }; refresh(); },
    generationInputs: (inputs) => ready() ? { ...inputs, analysis_id: analysis.job.id,
      target_duration_s: inputs.target_duration_s || analysis.job.result.recommended_target_s, max_duration_s: undefined } : inputs };
})();
