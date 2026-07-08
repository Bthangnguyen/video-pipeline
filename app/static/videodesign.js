const state = {
  projectId: "",
  project: null,
  rows: [],
  timeline: null,
  activeView: "start",
  selectedSceneId: "",
  selectedItemId: "",
  previewCandidateId: "",
  materialHealth: null,
  selectedTool: "script",
  timelineFit: true,
  timelinePixelsPerSecond: 48,
  timelinePlayheadSeconds: 0,
  timelinePlaying: false,
  running: false,
  lastProgressMessage: "",
  preset: defaultPreset(),
};

let progressTimer = null;
let dragState = null;
const TIMELINE_LABEL_WIDTH = 122;
const TIMELINE_LABEL_WIDTH_COMPACT = 96;
const TIMELINE_MIN_CLIP_SECONDS = 0.25;
const TIMELINE_MIN_ZOOM = 18;
const TIMELINE_MAX_ZOOM = 140;

const viewTitles = {
  start: "Create video",
  script: "Script creation",
  template: "Template setup",
  plan: "Scene plan",
  materials: "Material review",
  studio: "Studio timeline",
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  updateDurationLabel();
  navigate("start");
  restoreProject();
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.viewTarget));
  });

  document.getElementById("start-duration").addEventListener("input", updateDurationLabel);
  document.getElementById("create-project").addEventListener("click", createProject);
  document.getElementById("load-saved-project").addEventListener("click", () => {
    const projectId = localStorage.getItem("videodesignProjectId");
    if (projectId) loadProject(projectId, "script");
    else setStatus("No saved project found.", "error");
  });

  document.getElementById("script-editor").addEventListener("input", updateScriptMetrics);
  document.getElementById("generate-script").addEventListener("click", generateScript);
  document.getElementById("save-script").addEventListener("click", saveScript);
  document.getElementById("parse-scenes").addEventListener("click", parseScenes);

  document.querySelectorAll("[data-preset-path]").forEach((button) => {
    button.addEventListener("click", () => setPresetChoice(button));
  });
  document.querySelectorAll("[data-template-id]").forEach((button) => {
    button.addEventListener("click", () => setTemplateChoice(button));
  });
  document.querySelectorAll("[data-caption-style]").forEach((button) => {
    button.addEventListener("click", () => setCaptionStyle(button));
  });
  document.getElementById("preset-candidate-count").addEventListener("input", () => {
    state.preset.scene_media.candidate_count = Number(document.getElementById("preset-candidate-count").value || 4);
    renderSummaryRails();
  });
  document.getElementById("preset-pinterest-count").addEventListener("input", () => {
    state.preset.scene_media.pinterest_candidate_count = Number(document.getElementById("preset-pinterest-count").value || 4);
    renderSummaryRails();
  });
  document.getElementById("preset-translate").addEventListener("change", () => {
    state.preset.scene_media.translate_to_chinese = document.getElementById("preset-translate").checked;
    renderSummaryRails();
  });
  document.getElementById("tts-provider").addEventListener("change", () => {
    state.preset.voiceover.provider = document.getElementById("tts-provider").value;
    renderSummaryRails();
  });
  document.getElementById("voice-id").addEventListener("input", () => {
    state.preset.voiceover.voice_id = document.getElementById("voice-id").value.trim() || "en-US-AriaNeural";
    renderSummaryRails();
  });

  document.getElementById("generate-tts").addEventListener("click", generateTts);
  document.getElementById("save-scene").addEventListener("click", saveSelectedScene);
  document.getElementById("generate-scene-keywords").addEventListener("click", generateSelectedSceneKeywords);
  document.getElementById("generate-all-keywords").addEventListener("click", generateAllSceneKeywords);
  document.getElementById("split-scene").addEventListener("click", splitSelectedScene);
  document.getElementById("merge-prev-scene").addEventListener("click", mergePreviousScene);

  document.getElementById("search-current-scene").addEventListener("click", searchSelectedScene);
  document.getElementById("search-all-scenes").addEventListener("click", searchAllScenes);
  document.getElementById("save-material-keywords").addEventListener("click", saveMaterialKeywords);
  document.getElementById("run-material-health").addEventListener("click", runMaterialHealth);
  document.getElementById("clear-scene-candidates").addEventListener("click", clearSelectedSceneCandidates);
  document.getElementById("clear-all-candidates").addEventListener("click", clearAllCandidates);
  document.getElementById("download-approved").addEventListener("click", downloadApproved);

  document.getElementById("create-timeline").addEventListener("click", createTimeline);
  document.getElementById("studio-play").addEventListener("click", toggleStudioPlayback);
  document.getElementById("studio-video").addEventListener("timeupdate", onStudioVideoTimeUpdate);
  document.getElementById("studio-video").addEventListener("loadedmetadata", updateStudioClock);
  document.getElementById("studio-video").addEventListener("ended", onStudioVideoEnded);
  document.getElementById("studio-video").addEventListener("play", updateStudioPlaybackButton);
  document.getElementById("studio-video").addEventListener("pause", updateStudioPlaybackButton);
  document.getElementById("timeline-fit").addEventListener("click", fitTimeline);
  document.getElementById("timeline-zoom-out").addEventListener("click", () => zoomTimeline(-1));
  document.getElementById("timeline-zoom-in").addEventListener("click", () => zoomTimeline(1));
  document.getElementById("timeline-ruler").addEventListener("pointerdown", seekTimelineFromPointer);
  document.getElementById("timeline-tracks").addEventListener("pointerdown", seekTimelineFromPointer);
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTool = button.dataset.studioTool;
      renderStudio();
    });
  });

  document.getElementById("studio-text").addEventListener("pointerdown", startCanvasTextDrag);
  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", endPointerDrag);
}

async function restoreProject() {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("project_id") || localStorage.getItem("videodesignProjectId");
  if (projectId) await loadProject(projectId, params.get("view") || null);
}

async function createProject() {
  await run("Creating project", async () => {
    const prompt = document.getElementById("start-prompt").value.trim();
    if (!prompt) throw new Error("Add an idea or script first.");

    const looksLikeScript = wordCount(prompt) >= 35 || sentenceCount(prompt) > 1;
    const data = await api("/api/videodesign/projects", {
      method: "POST",
      body: {
        idea: looksLikeScript ? null : prompt,
        script: looksLikeScript ? prompt : null,
        target_platform: document.getElementById("start-platform").value,
        aspect_ratio: "9:16",
        target_duration_seconds: Number(document.getElementById("start-duration").value || 45),
        language: "en",
      },
    });

    state.project = data.project;
    state.projectId = data.project.project_id;
    localStorage.setItem("videodesignProjectId", state.projectId);
    hydrateProjectFields();
    await savePreset();
    navigate("script");
  });
}

async function loadProject(projectId, preferredView = null) {
  await run("Loading project", async () => {
    const data = await api(`/api/videodesign/projects/${projectId}`);
    state.project = data.project;
    state.projectId = data.project.project_id;
    state.preset = mergePreset(defaultPreset(), state.project.design_preset || {});
    localStorage.setItem("videodesignProjectId", state.projectId);
    hydrateProjectFields();
    await loadReview();
    await loadTimeline();
    navigate(preferredView || (state.timeline ? "studio" : "script"));
  });
}

async function saveProjectPatch(patch) {
  const data = await api(`/api/videodesign/projects/${state.projectId}`, {
    method: "PATCH",
    body: patch,
  });
  state.project = data.project;
  hydrateProjectFields(false);
  return data.project;
}

async function generateScript() {
  ensureProject();
  await run("Generating script with DeepSeek", async () => {
    const idea = document.getElementById("script-idea").value.trim() || state.project.idea;
    const data = await api(`/api/videodesign/projects/${state.projectId}/script/generate`, {
      method: "POST",
      body: {
        idea,
        target_duration_seconds: Number(state.project.target_duration_seconds || 45),
        language: state.project.language || "en",
      },
    });
    state.project = data.project;
    hydrateProjectFields();
    await loadReview();
    setStatus("Script generated.", "idle");
  });
}

async function saveScript() {
  ensureProject();
  await run("Saving script", async () => {
    await saveProjectPatch({
      idea: document.getElementById("script-idea").value.trim(),
      script: document.getElementById("script-editor").value.trim(),
    });
    setStatus("Script saved.", "idle");
  });
}

async function parseScenes() {
  ensureProject();
  await run("Preparing template", async () => {
    await saveScript();
    await saveSplitSettings();
    await savePreset();
    navigate("template");
  });
}

async function createScenePlan() {
  await saveScript();
  await saveSplitSettings();
  await api(`/api/videodesign/projects/${state.projectId}/plan`, { method: "POST" });
  await loadReview();
  selectFirstScene();
  navigate("plan");
}

async function saveSplitSettings() {
  await api(`/api/videodesign/projects/${state.projectId}/split-settings`, {
    method: "PATCH",
    body: {
      split_mode: document.getElementById("split-mode").value,
      target_scene_duration_seconds: Number(document.getElementById("scene-seconds").value || 4),
      min_scene_duration_seconds: 2.5,
      max_scene_duration_seconds: 7,
      max_words_per_scene: Number(document.getElementById("max-words").value || 18),
      allow_manual_boundaries: true,
    },
  });
}

async function savePreset() {
  if (!state.projectId) return;
  state.preset.template = {
    ...(state.preset.template || {}),
    template_id: "short_form_editor",
    template_category: "timeline_template",
  };
  state.preset.scene_media.media_source = "multi_source";
  state.preset.scene_media.candidate_count = Number(inputValue("preset-candidate-count", state.preset.scene_media.candidate_count || 4));
  state.preset.scene_media.pinterest_candidate_count = Number(inputValue("preset-pinterest-count", state.preset.scene_media.pinterest_candidate_count || 4));
  state.preset.scene_media.translate_to_chinese = inputChecked("preset-translate", true);
  state.preset.voiceover.provider = inputValue("tts-provider", state.preset.voiceover.provider || "free_tts");
  state.preset.voiceover.voice_id = inputValue("voice-id", state.preset.voiceover.voice_id || "en-US-AriaNeural").trim() || "en-US-AriaNeural";
  const data = await api(`/api/videodesign/projects/${state.projectId}/preset`, {
    method: "PATCH",
    body: state.preset,
  });
  state.project = data.project;
}

async function generateTts() {
  ensureProject();
  await run("Generating TTS audio and timing", async () => {
    await savePreset();
    await api(`/api/videodesign/projects/${state.projectId}/tts/generate`, {
      method: "POST",
      body: {
        provider: state.preset.voiceover.provider,
        voice_id: state.preset.voiceover.voice_id,
      },
    });
    await loadReview();
    setStatus("TTS generated. Review timing, then continue to Materials.", "idle");
  });
}

async function loadReview() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/review`);
  state.rows = data.rows;
  if (!state.selectedSceneId || !state.rows.some((row) => row.scene.scene_id === state.selectedSceneId)) {
    selectFirstScene();
  }
  renderAll();
}

async function loadTimeline() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline`);
  state.timeline = data.timeline;
  if (state.timeline && !state.selectedItemId) {
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
  }
  renderAll();
}

async function saveSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Saving scene", async () => {
    await saveSceneDraft(row);
    await loadReview();
  });
}

async function generateSelectedSceneKeywords() {
  const row = selectedRow();
  if (!row) return;
  await run("Generating scene keywords", async () => {
    await saveSceneDraft(row);
    await api(`/api/videodesign/projects/${state.projectId}/keywords/generate`, {
      method: "POST",
      body: { scene_ids: [row.scene.scene_id] },
    });
    await loadReview();
    state.selectedSceneId = row.scene.scene_id;
  });
}

async function generateAllSceneKeywords() {
  ensureProject();
  await run("Generating all scene keywords", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/keywords/generate`, {
      method: "POST",
      body: { scene_ids: null },
    });
    await loadReview();
  });
}

async function saveSceneDraft(row) {
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
    method: "PATCH",
    body: sceneEditorPatch(),
  });
}

function sceneEditorPatch() {
  const voiceover = inputValue("scene-voiceover").trim();
  return {
    voiceover_text: voiceover,
    tts_text: voiceover,
    caption_text: voiceover,
    on_screen_text: inputValue("scene-onscreen").trim(),
    visual_brief: inputValue("scene-visual").trim(),
    matching_keywords: inputValue("scene-keywords").split(",").map((item) => item.trim()).filter(Boolean),
  };
}

async function splitSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Splitting scene", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/split`, { method: "POST" });
    await loadReview();
  });
}

async function mergePreviousScene() {
  const row = selectedRow();
  const index = state.rows.findIndex((item) => item.scene.scene_id === row?.scene.scene_id);
  if (!row || index <= 0) return;
  await run("Merging scenes", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/merge`, {
      method: "POST",
      body: { scene_ids: [state.rows[index - 1].scene.scene_id, row.scene.scene_id] },
    });
    await loadReview();
  });
}

async function saveMaterialKeywords() {
  const row = selectedRow();
  if (!row) return;
  await run("Saving material keywords", async () => {
    await saveMaterialKeywordsDraft(row);
    await loadReview();
  });
}

async function saveMaterialKeywordsDraft(row) {
  const keywords = keywordsFromText(inputValue("materials-keywords"));
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
    method: "PATCH",
    body: { matching_keywords: keywords },
  });
}

async function runMaterialHealth() {
  const keyword = keywordsFromText(inputValue("materials-keywords"))[0] || selectedRow()?.scene.matching_keywords?.[0] || "cat";
  state.materialHealth = { running: true, keyword, sources: [] };
  renderMaterialHealth();
  await run("Checking Douyin and Pinterest health", async () => {
    state.materialHealth = await api("/api/videodesign/materials/preflight", {
      method: "POST",
      body: { keyword },
    });
    renderMaterialHealth();
  });
}

async function searchSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Searching selected scene", async () => {
    await saveMaterialKeywordsDraft(row);
    const body = materialSearchBody([row.scene.scene_id]);
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/materials/search`, {
      method: "POST",
      body,
    });
    await loadReview();
  });
}

async function searchAllScenes() {
  ensureProject();
  await run("Searching all scenes", async () => {
    const row = selectedRow();
    if (row) await saveMaterialKeywordsDraft(row);
    startProgressPolling();
    try {
      await api(`/api/videodesign/projects/${state.projectId}/materials/search`, {
        method: "POST",
        body: materialSearchBody(),
      });
    } finally {
      stopProgressPolling();
    }
    await loadReview();
  });
}

async function approveCandidate(sceneId, candidateId) {
  await run("Approving candidate", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "approve", candidate_id: candidateId },
    });
    await loadReview();
  });
}

async function deleteCandidate(sceneId, candidateId) {
  await run("Deleting candidate", async () => {
    await rejectCandidate(sceneId, candidateId);
    if (state.previewCandidateId === candidateId) state.previewCandidateId = "";
    await loadReview();
  });
}

async function clearSelectedSceneCandidates() {
  const row = selectedRow();
  if (!row) {
    setStatus("Select a scene first.", "error");
    return;
  }
  if (!row.candidates.length) {
    setStatus("This scene has no videos to clear.", "idle");
    return;
  }
  if (!window.confirm(`Clear ${row.candidates.length} videos from Scene ${row.scene.order}?`)) return;
  await run("Clearing scene videos", async () => {
    for (const candidate of row.candidates) {
      await rejectCandidate(row.scene.scene_id, candidate.candidate_id);
    }
    state.previewCandidateId = "";
    await loadReview();
  });
}

async function clearAllCandidates() {
  const candidates = state.rows.flatMap((row) => row.candidates.map((candidate) => ({ ...candidate, scene_id: row.scene.scene_id })));
  if (!candidates.length) {
    setStatus("There are no videos to clear.", "idle");
    return;
  }
  if (!window.confirm(`Clear all ${candidates.length} material videos from this project?`)) return;
  await run("Clearing all material videos", async () => {
    for (const candidate of candidates) {
      await rejectCandidate(candidate.scene_id, candidate.candidate_id);
    }
    state.previewCandidateId = "";
    await loadReview();
  });
}

async function rejectCandidate(sceneId, candidateId) {
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
    method: "PATCH",
    body: { action: "reject", candidate_id: candidateId },
  });
}

async function allowPlaceholder(sceneId) {
  await run("Allowing placeholder", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "placeholder" },
    });
    await loadReview();
  });
}

async function downloadApproved() {
  ensureProject();
  await run("Downloading approved videos", async () => {
    const sceneIds = state.rows
      .filter((row) => row.scene.selected_candidate_id && !row.scene.material_asset_id)
      .map((row) => row.scene.scene_id);
    if (!sceneIds.length) throw new Error("No approved scenes are waiting for download.");
    await api(`/api/videodesign/projects/${state.projectId}/materials/download`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    await loadReview();
  });
}

async function createTimeline() {
  ensureProject();
  await run("Creating Studio timeline", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/studio`, { method: "POST" });
    state.timeline = data.timeline;
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
    renderStudio();
  });
}

function materialSearchBody(sceneIds = null) {
  const douyinMin = Number(inputValue("douyin-min-count", state.preset.scene_media.candidate_count || 0));
  const pinterestMin = Number(inputValue("pinterest-min-count", state.preset.scene_media.pinterest_candidate_count || 0));
  const queryCount = clamp(Number(inputValue("queries-per-scene", 2)) || 2, 1, 3);
  return {
    scene_ids: sceneIds,
    candidates_per_scene: Math.max(douyinMin, 1),
    douyin_min_per_scene: douyinMin,
    pinterest_min_per_scene: pinterestMin,
    queries_per_scene: queryCount,
    translate_to_chinese: inputChecked("translate-query", true),
    use_smart_keywords: inputChecked("smart-keywords", false),
  };
}

function navigate(view) {
  if (!view) return;
  if (view !== "start" && !state.projectId) {
    setStatus("Create or load a project first.", "error");
    view = "start";
  }
  state.activeView = view;
  document.body.dataset.vdView = view;
  document.querySelectorAll(".vd-view").forEach((section) => {
    section.dataset.active = section.dataset.view === view ? "true" : "false";
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.dataset.active = button.dataset.viewTarget === view ? "true" : "false";
  });
  document.getElementById("view-title").textContent = viewTitles[view] || "VideoDesign";
  renderAll();
}

function renderAll() {
  renderProjectChip();
  renderTemplateSelections();
  renderSummaryRails();
  renderSceneRails();
  renderSceneEditor();
  renderTtsStatus();
  renderCandidateBoard();
  renderStudio();
  updateScriptMetrics();
}

function renderProjectChip() {
  const chip = document.getElementById("vd-project-chip");
  chip.textContent = state.projectId ? state.projectId : "No project";
}

function renderSummaryRails() {
  const html = `
    <h3>Your video</h3>
    ${summaryRow("Format", state.preset.format.aspect_ratio)}
    ${summaryRow("Text style", captionLabel(state.preset.captions.style_id))}
    ${summaryRow("Transition", transitionLabel(state.preset.extras.transition_pack_id))}
    ${summaryRow("Overlay", overlayLabel(state.preset.extras.overlay_pack_id))}
    ${summaryRow("Voiceover", `${state.preset.voiceover.provider} - ${state.preset.voiceover.voice_id}`)}
    <button class="vd-primary" data-summary-action="save-template" type="button">Save preset and continue</button>
  `;
  document.querySelectorAll(".vd-summary-rail").forEach((rail) => {
    rail.innerHTML = html;
    rail.querySelector("[data-summary-action='save-template']").addEventListener("click", async () => {
      await run("Saving preset", async () => {
        await savePreset();
        if (!state.rows.length) await createScenePlan();
        else navigate("plan");
      });
    });
  });
}

function summaryRow(label, value) {
  return `<div class="vd-summary-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not set")}</strong></div>`;
}

function renderTemplateSelections() {
  document.querySelectorAll("[data-preset-path]").forEach((button) => {
    const value = getByPath(state.preset, button.dataset.presetPath);
    button.classList.toggle("is-selected", value === button.dataset.presetValue);
  });
  document.querySelectorAll("[data-caption-style]").forEach((button) => {
    button.classList.toggle("is-selected", state.preset.captions.style_id === button.dataset.captionStyle);
  });
}

function renderSceneRails() {
  const html = state.rows.length ? state.rows.map((row) => sceneRailButton(row)).join("") : `<div class="vd-empty">No scenes yet. Parse the script first.</div>`;
  document.getElementById("plan-scene-rail").innerHTML = html;
  document.getElementById("materials-scene-rail").innerHTML = html;
  document.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      renderAll();
    });
  });
}

function sceneRailButton(row) {
  const active = row.scene.scene_id === state.selectedSceneId ? "true" : "false";
  return `
    <button class="vd-scene-pill" data-scene-id="${row.scene.scene_id}" data-active="${active}" type="button">
      <span>Scene ${row.scene.order}</span>
      <strong>${escapeHtml(row.scene.on_screen_text || row.scene.voiceover_text || "Untitled")}</strong>
      <em>${escapeHtml(row.scene.approval_state)} / ${row.candidates.length} candidates</em>
    </button>
  `;
}

function renderSceneEditor() {
  const row = selectedRow();
  document.getElementById("plan-scene-title").textContent = row ? `Scene ${row.scene.order}` : "Select a scene";
  setInputValue("scene-voiceover", row?.scene.voiceover_text || "");
  setInputValue("scene-onscreen", row?.scene.on_screen_text || "");
  setInputValue("scene-visual", row?.scene.visual_brief || "");
  setInputValue("scene-keywords", row?.scene.matching_keywords?.join(", ") || "");
}

function renderTtsStatus() {
  const panel = document.getElementById("tts-status-panel");
  if (!panel) return;
  const rows = state.rows || [];
  const row = selectedRow();
  const synced = rows.filter((row) => row.scene.tts?.sync_state === "synced").length;
  const audioUrl = row?.scene.tts?.audio_url || "";
  panel.innerHTML = `
    <h3>TTS status</h3>
    <p class="vd-muted">${synced}/${rows.length} scenes have audio timing.</p>
    <div class="vd-audio-preview">
      <strong>${row ? `Scene ${row.scene.order} voice` : "Voice preview"}</strong>
      ${audioUrl ? `<audio controls preload="none" src="${audioUrl}"></audio>` : `<p class="vd-muted">Generate TTS to preview the selected scene voice.</p>`}
    </div>
    <div class="vd-tts-list">
      ${rows.length ? rows.map((row) => `
        <button class="vd-tts-row" data-scene-id="${row.scene.scene_id}" data-active="${row.scene.scene_id === state.selectedSceneId}" type="button">
          <span>Scene ${row.scene.order}</span>
          <strong>${escapeHtml(row.scene.tts?.sync_state === "synced" ? "Synced" : "Pending")}</strong>
          <em>${formatDuration(row.scene.duration_seconds || 0)} / ${escapeHtml(row.scene.tts?.provider || state.preset.voiceover.provider)}</em>
        </button>
      `).join("") : `<div class="vd-empty">Parse scenes before generating TTS.</div>`}
    </div>
    <button id="tts-continue-materials" class="vd-primary" type="button">Continue to Materials</button>
  `;
  panel.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      renderAll();
    });
  });
  panel.querySelector("#tts-continue-materials")?.addEventListener("click", () => navigate("materials"));
}

function renderCandidateBoard() {
  const row = selectedRow();
  const board = document.getElementById("candidate-board");
  document.getElementById("materials-scene-title").textContent = row ? `Scene ${row.scene.order}: ${row.scene.approval_state}` : "Select a scene";
  renderMaterialControls(row);
  if (!row) {
    board.innerHTML = `<div class="vd-empty">Select a scene to review candidates.</div>`;
    return;
  }
  if (!row.candidates.length) {
    board.innerHTML = `
      <div class="vd-empty">
        <h3>No candidates yet</h3>
        <p>Search this scene or allow a placeholder before Studio.</p>
        <button data-placeholder-scene="${row.scene.scene_id}" type="button">Allow placeholder</button>
      </div>
    `;
  } else {
    const bySource = {
      douyinsearch: row.candidates.filter((candidate) => candidate.source !== "pinterestsearch"),
      pinterestsearch: row.candidates.filter((candidate) => candidate.source === "pinterestsearch"),
    };
    board.innerHTML = `
      <section class="vd-source-section">
        <h3>Douyin <span>${bySource.douyinsearch.length}</span></h3>
        <div class="vd-source-grid">${candidateCards(bySource.douyinsearch, row, "douyinsearch")}</div>
      </section>
      <section class="vd-source-section">
        <h3>Pinterest <span>${bySource.pinterestsearch.length}</span></h3>
        <div class="vd-source-grid">${candidateCards(bySource.pinterestsearch, row, "pinterestsearch")}</div>
      </section>
    `;
  }
  board.querySelectorAll("[data-approve-candidate]").forEach((button) => {
    button.addEventListener("click", () => approveCandidate(button.dataset.approveScene, button.dataset.approveCandidate));
  });
  board.querySelectorAll("[data-placeholder-scene]").forEach((button) => {
    button.addEventListener("click", () => allowPlaceholder(button.dataset.placeholderScene));
  });
  board.querySelectorAll("[data-preview-candidate]").forEach((button) => {
    button.addEventListener("click", () => previewCandidate(button.dataset.previewCandidate));
  });
  board.querySelectorAll("[data-delete-candidate]").forEach((button) => {
    button.addEventListener("click", () => deleteCandidate(button.dataset.deleteScene, button.dataset.deleteCandidate));
  });
}

function candidateCards(candidates, row, source) {
  if (!candidates.length) return `<div class="vd-empty">No ${escapeHtml(sourceLabel(source))} candidates yet.</div>`;
  return candidates.map((candidate) => `
    <article class="vd-candidate ${candidate.status === "approved" ? "is-approved" : ""}">
      <img src="${candidate.cover_url}" alt="">
      <div>
        <span class="vd-source-badge">${escapeHtml(sourceLabel(candidate.source))}</span>
        <h3>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</h3>
        <p>${escapeHtml(candidate.match_reason)}</p>
        <p>${formatDuration(candidate.duration)} / ${escapeHtml(candidate.source_item_id || candidate.douyin_aweme_id)}</p>
        <div class="vd-button-row">
          <button data-approve-candidate="${candidate.candidate_id}" data-approve-scene="${row.scene.scene_id}" type="button">${candidate.status === "approved" ? "Approved" : "Approve"}</button>
          <button data-preview-candidate="${candidate.candidate_id}" type="button">Preview</button>
          <button data-delete-candidate="${candidate.candidate_id}" data-delete-scene="${row.scene.scene_id}" class="vd-danger" type="button">Delete</button>
        </div>
      </div>
    </article>
  `).join("");
}

function renderMaterialControls(row) {
  const keywords = row?.scene.matching_keywords || [];
  const chips = document.getElementById("materials-keyword-chips");
  if (chips) {
    chips.innerHTML = keywords.length
      ? keywords.map((keyword) => `<button data-keyword-chip="${escapeHtml(keyword)}" type="button">${escapeHtml(keyword)}</button>`).join("")
      : `<span class="vd-muted">No keywords yet.</span>`;
    chips.querySelectorAll("[data-keyword-chip]").forEach((button) => {
      button.addEventListener("click", () => setInputValue("materials-keywords", button.dataset.keywordChip || ""));
    });
  }
  setInputValue("materials-keywords", keywords.join(", "));
  renderSearchErrors(row);
  renderMaterialHealth();
  renderMaterialPreview(row);
}

function renderSearchErrors(row) {
  const panel = document.getElementById("materials-search-errors");
  if (!panel) return;
  const errors = (row?.search_errors || []).slice(-6);
  panel.innerHTML = errors.length
    ? `
      <h4>Search issues</h4>
      ${errors.map((error) => `
        <div class="vd-search-error">
          <strong>${escapeHtml(sourceLabel(error.source))} / ${escapeHtml(error.keyword)}</strong>
          <span>${escapeHtml(error.code)}</span>
        </div>
      `).join("")}
    `
    : "";
}

function renderMaterialPreview(row) {
  const panel = document.getElementById("materials-preview");
  if (!panel) return;
  const candidate = row?.candidates.find((item) => item.candidate_id === state.previewCandidateId);
  if (!candidate) {
    panel.innerHTML = `<div class="vd-empty">Choose a candidate to preview here.</div>`;
    return;
  }
  panel.innerHTML = `
    <h4>${escapeHtml(sourceLabel(candidate.source))} preview</h4>
    <video controls playsinline preload="metadata" poster="${candidate.cover_url}" src="${candidate.stream_url}"></video>
    <strong>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</strong>
    <p>${escapeHtml(candidate.search_keyword || candidate.match_reason || "")}</p>
  `;
}

function renderMaterialHealth() {
  const panel = document.getElementById("material-health-panel");
  if (!panel) return;
  const health = state.materialHealth;
  if (!health) {
    panel.innerHTML = `<div class="vd-muted">Run health check before searching if Douyin or Pinterest feels unstable.</div>`;
    return;
  }
  if (health.running) {
    panel.innerHTML = `<div class="vd-health-running">Checking cookie, anti-bot, page load, input search, and network for "${escapeHtml(health.keyword)}"...</div>`;
    return;
  }
  panel.innerHTML = `
    <h4>Search health: ${health.healthy ? "Ready" : "Needs attention"}</h4>
    ${(health.sources || []).map((source) => `
      <section class="vd-health-source" data-ok="${source.success ? "true" : "false"}">
        <strong>${escapeHtml(sourceLabel(source.source))}</strong>
        ${(source.checks || []).map((check) => `
          <div class="vd-health-check" data-ok="${check.ok ? "true" : "false"}">
            <span>${check.ok ? "OK" : "FAIL"}</span>
            <p><b>${escapeHtml(check.name)}</b> ${escapeHtml(check.message)}</p>
          </div>
        `).join("")}
      </section>
    `).join("")}
  `;
}

function previewCandidate(candidateId) {
  state.previewCandidateId = candidateId;
  renderCandidateBoard();
}

function renderStudio() {
  renderStudioToolPanel();
  renderStudioStage();
  renderStudioInspector();
  renderTimeline();
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}

function renderStudioToolPanel() {
  const panel = document.getElementById("studio-tool-panel");
  const row = selectedRow();
  if (state.selectedTool === "script") {
    panel.innerHTML = `<h3>Script</h3>${state.rows.map((item) => `
      <button class="vd-script-scene" data-scene-id="${item.scene.scene_id}" data-active="${item.scene.scene_id === state.selectedSceneId}" type="button">
        <span>Scene ${item.scene.order}</span>
        <strong>${escapeHtml(item.scene.on_screen_text || item.scene.voiceover_text)}</strong>
      </button>
    `).join("") || `<div class="vd-empty">No scenes.</div>`}`;
  } else if (state.selectedTool === "text") {
    const item = selectedItem();
    panel.innerHTML = `
      <h3>Text overlay</h3>
      <label>Text <input id="studio-text-input" value="${escapeHtml(textForItem(item))}"></label>
      <p class="vd-muted">Drag the text directly on the preview canvas.</p>
      <button id="save-studio-text" type="button">Save text</button>
    `;
    panel.querySelector("#save-studio-text")?.addEventListener("click", () => saveStudioText());
  } else if (state.selectedTool === "media") {
    panel.innerHTML = `<h3>Media</h3><p>${row ? `Scene ${row.scene.order}` : "Select a scene"}</p><button data-view-target="materials" type="button">Return to materials</button>`;
    panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigate("materials"));
  } else {
    panel.innerHTML = `<h3>${escapeHtml(titleCase(state.selectedTool))}</h3><p class="vd-muted">Controls for this tool will build on the selected timeline item.</p>`;
  }
  panel.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      selectFirstItemForScene(button.dataset.sceneId);
      renderStudio();
    });
  });
}

function renderStudioStage() {
  const row = selectedRow();
  const media = timelineItems().find((item) => item.type === "media" && item.scene_id === row?.scene.scene_id);
  const text = timelineItems().find((item) => item.type === "text" && item.scene_id === row?.scene.scene_id);
  const caption = timelineItems().find((item) => item.type === "caption" && item.scene_id === row?.scene.scene_id);
  const video = document.getElementById("studio-video");
  const captionEl = document.getElementById("studio-caption");
  const textEl = document.getElementById("studio-text");
  const stage = document.getElementById("studio-stage");
  const sceneLabel = document.getElementById("studio-scene-label");
  const mediaState = document.getElementById("studio-media-state");

  video.muted = true;
  if (media?.source_ref?.media_url && video.getAttribute("src") !== media.source_ref.media_url) {
    video.src = media.source_ref.media_url;
    video.load();
  }
  if (!media?.source_ref?.media_url) video.removeAttribute("src");

  sceneLabel.textContent = row ? `Scene ${row.scene.order}` : "No scene selected";
  mediaState.textContent = media?.source_ref?.media_url ? "Stream ready" : "No media";
  stage.dataset.overlay = state.preset.extras.overlay_pack_id || "caption_shadow";
  stage.dataset.captionStyle = state.preset.captions.style_id || "bold_outline";
  const chunks = caption?.source_ref?.caption_chunks || row?.scene.caption_chunks || [];
  captionEl.textContent = chunks.map((chunk) => chunk.text).join(" ") || row?.scene.caption_text || "";
  textEl.textContent = textForItem(text) || row?.scene.on_screen_text || "";
  textEl.dataset.itemId = text?.item_id || "";
  const transform = text?.transform || { x: 50, y: 18 };
  textEl.style.left = `${Number(transform.x ?? 50)}%`;
  textEl.style.top = `${Number(transform.y ?? 18)}%`;
  updateStudioClock();
  updateStudioPlaybackButton();
}

function renderStudioInspector() {
  const panel = document.getElementById("studio-inspector");
  if (!panel) return;
  const item = selectedItem();
  const row = selectedRow();
  if (!state.timeline) {
    panel.innerHTML = `
      <h3>Inspector</h3>
      <p class="vd-muted">Create a timeline after approving and downloading scene videos.</p>
    `;
    return;
  }
  panel.innerHTML = `
    <h3>Inspector</h3>
    ${summaryRow("Scene", row ? `Scene ${row.scene.order}` : "None")}
    ${summaryRow("Selected", item ? itemLabel(item) : "None")}
    ${summaryRow("Start", item ? formatDuration(item.start_seconds) : "0:00")}
    ${summaryRow("End", item ? formatDuration(item.end_seconds) : "0:00")}
    ${item?.type === "media" ? summaryRow("Source trim", `${formatDuration(mediaTrimStart(item))} - ${formatDuration(mediaTrimEnd(item))}`) : ""}
    ${summaryRow("Text style", captionLabel(state.preset.captions.style_id))}
    ${summaryRow("Transition", transitionLabel(state.preset.extras.transition_pack_id))}
    ${summaryRow("Overlay", overlayLabel(state.preset.extras.overlay_pack_id))}
  `;
}

function renderTimeline() {
  const ruler = document.getElementById("timeline-ruler");
  const tracks = document.getElementById("timeline-tracks");
  const board = document.querySelector(".vd-timeline-board");
  const durationLabel = document.getElementById("timeline-duration-label");
  const zoomLabel = document.getElementById("timeline-zoom-label");
  if (!state.timeline) {
    ruler.innerHTML = "";
    tracks.innerHTML = `<div class="vd-empty">Create a Studio timeline after videos are downloaded.</div>`;
    if (durationLabel) durationLabel.textContent = "0:00";
    if (zoomLabel) zoomLabel.textContent = "Fit";
    updateTimelinePlayhead(0);
    updateTimelineZoomButtons();
    return;
  }
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const metrics = timelineMetrics(duration);
  if (board) {
    board.style.setProperty("--timeline-label-width", `${metrics.labelWidth}px`);
    board.style.setProperty("--timeline-lane-width", `${metrics.laneWidth}px`);
  }
  if (durationLabel) durationLabel.textContent = formatDuration(duration);
  if (zoomLabel) zoomLabel.textContent = state.timelineFit ? "Fit" : `${Math.round(metrics.pxPerSecond)} px/s`;
  ruler.innerHTML = timelineTicks(duration, metrics).map((tick) => `<span style="left:${tick.left}px">${formatDuration(tick.time)}</span>`).join("");
  tracks.innerHTML = state.timeline.layers.map((layer) => {
    const items = state.timeline.items.filter((item) => item.layer_id === layer);
    return `
      <div class="vd-track">
        <div class="vd-track-name">${escapeHtml(layer.replaceAll("_", " "))}</div>
        <div class="vd-track-lane" data-track-layer="${layer}">
          ${items.map((item) => timelineClip(item, metrics)).join("")}
        </div>
      </div>
    `;
  }).join("");

  tracks.querySelectorAll("[data-item-id]").forEach((clip) => {
    clip.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedItemId = clip.dataset.itemId;
      const item = selectedItem();
      if (item) state.selectedSceneId = item.scene_id;
      if (item?.type === "text") state.selectedTool = "text";
      renderStudio();
    });
    clip.addEventListener("pointerdown", startTimelineDrag);
  });
  updateTimelineZoomButtons();
  updateStudioClock();
}

function timelineClip(item, metrics) {
  const left = Math.max(0, item.start_seconds * metrics.pxPerSecond);
  const width = Math.max(12, (item.end_seconds - item.start_seconds) * metrics.pxPerSecond);
  const active = item.item_id === state.selectedItemId ? "true" : "false";
  const editable = editableTimelineItem(item) ? "true" : "false";
  return `
    <button class="vd-timeline-clip" data-item-id="${item.item_id}" data-type="${item.type}" data-active="${active}" data-editable="${editable}" style="left:${left}px;width:${width}px;" type="button">
      <span class="vd-resize-handle" data-edge="left"></span>
      <strong>${escapeHtml(itemLabel(item))}</strong>
      <span class="vd-resize-handle" data-edge="right"></span>
    </button>
  `;
}

function timelineMetrics(duration = Math.max(1, state.timeline?.duration_seconds || 1)) {
  const board = document.querySelector(".vd-timeline-board");
  const labelWidth = window.matchMedia("(max-width: 1120px)").matches ? TIMELINE_LABEL_WIDTH_COMPACT : TIMELINE_LABEL_WIDTH;
  const boardWidth = board?.clientWidth || 900;
  const fitLaneWidth = Math.max(320, boardWidth - labelWidth);
  const zoomLaneWidth = Math.max(320, duration * state.timelinePixelsPerSecond);
  const laneWidth = state.timelineFit ? fitLaneWidth : Math.max(fitLaneWidth, zoomLaneWidth);
  return {
    duration,
    labelWidth,
    laneWidth,
    pxPerSecond: laneWidth / duration,
  };
}

function timelineTicks(duration, metrics) {
  const targetPixels = 110;
  const rawStep = Math.max(0.5, targetPixels / metrics.pxPerSecond);
  const step = niceTimelineStep(rawStep);
  const ticks = [];
  for (let time = 0; time <= duration + 0.001; time += step) {
    ticks.push({ time: Math.min(duration, Number(time.toFixed(2))), left: time * metrics.pxPerSecond });
  }
  if (!ticks.length || ticks.at(-1).time < duration) {
    ticks.push({ time: duration, left: duration * metrics.pxPerSecond });
  }
  return ticks;
}

function niceTimelineStep(rawStep) {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60];
  return steps.find((step) => step >= rawStep) || 120;
}

function editableTimelineItem(item) {
  return ["media", "text", "caption", "overlay"].includes(item?.type);
}

function fitTimeline() {
  state.timelineFit = true;
  renderTimeline();
}

function zoomTimeline(direction) {
  state.timelineFit = false;
  const factor = direction > 0 ? 1.25 : 0.8;
  state.timelinePixelsPerSecond = clamp(state.timelinePixelsPerSecond * factor, TIMELINE_MIN_ZOOM, TIMELINE_MAX_ZOOM);
  renderTimeline();
}

function updateTimelineZoomButtons() {
  const fit = document.getElementById("timeline-fit");
  const zoomOut = document.getElementById("timeline-zoom-out");
  const zoomIn = document.getElementById("timeline-zoom-in");
  if (fit) fit.dataset.active = state.timelineFit ? "true" : "false";
  if (zoomOut) zoomOut.disabled = !state.timeline || (!state.timelineFit && state.timelinePixelsPerSecond <= TIMELINE_MIN_ZOOM);
  if (zoomIn) zoomIn.disabled = !state.timeline || (!state.timelineFit && state.timelinePixelsPerSecond >= TIMELINE_MAX_ZOOM);
}

function seekTimelineFromPointer(event) {
  if (!state.timeline || event.button !== 0 || event.target.closest("[data-item-id]")) return;
  const fromRuler = event.currentTarget?.id === "timeline-ruler";
  if (!fromRuler && !event.target.closest(".vd-track-lane")) return;
  const board = document.querySelector(".vd-timeline-board");
  if (!board) return;
  const metrics = timelineMetrics();
  const rect = board.getBoundingClientRect();
  const x = event.clientX - rect.left + board.scrollLeft - metrics.labelWidth;
  seekTimeline(clamp(x / metrics.pxPerSecond, 0, metrics.duration), { autoplay: state.timelinePlaying });
}

function seekTimeline(globalTime, options = {}) {
  if (!state.timeline) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const time = clamp(Number(globalTime || 0), 0, duration);
  state.timelinePlayheadSeconds = time;
  const media = mediaItemAtTime(time);
  if (media) {
    state.selectedSceneId = media.scene_id;
    if (!selectedItem() || selectedItem()?.scene_id !== media.scene_id) {
      state.selectedItemId = media.item_id;
    }
    renderStudio();
    syncStudioVideoToTimeline(time, options);
    return;
  }
  updateStudioClock(time);
}

function mediaItemAtTime(time) {
  const mediaItems = timelineItems().filter((item) => item.type === "media");
  return mediaItems.find((item) => time >= item.start_seconds && time <= item.end_seconds)
    || mediaItems.find((item) => time < item.start_seconds)
    || mediaItems.at(-1)
    || null;
}

function syncStudioVideoToTimeline(globalTime, options = {}) {
  const video = document.getElementById("studio-video");
  const media = currentMediaItem();
  if (!video || !media) return;
  const localTime = mediaTrimStart(media) + clamp(globalTime - media.start_seconds, 0, Math.max(0, media.end_seconds - media.start_seconds));
  const targetVideoTime = clamp(localTime, mediaTrimStart(media), mediaTrimEnd(media));
  const setTime = () => {
    try {
      video.currentTime = targetVideoTime;
    } catch {
      return;
    }
    updateStudioClock(globalTime);
    if (options.autoplay) playStudioVideo();
  };
  if (video.readyState > 0) setTime();
  else video.addEventListener("loadedmetadata", setTime, { once: true });
}

function playStudioVideo() {
  const video = document.getElementById("studio-video");
  if (!video?.src) {
    state.timelinePlaying = false;
    updateStudioPlaybackButton();
    return;
  }
  const promise = video.play();
  if (promise?.catch) {
    promise.catch(() => {
      state.timelinePlaying = false;
      updateStudioPlaybackButton();
    });
  }
}

function currentMediaItem() {
  return timelineItems().find((item) => item.type === "media" && item.scene_id === selectedRow()?.scene.scene_id) || null;
}

function globalTimeFromVideo(media = currentMediaItem(), video = document.getElementById("studio-video")) {
  if (!media) return state.timelinePlayheadSeconds || 0;
  const localElapsed = Math.max(0, Number(video?.currentTime || 0) - mediaTrimStart(media));
  return (media.start_seconds || 0) + localElapsed;
}

function mediaTrimStart(item) {
  return Number(item?.source_ref?.trim_start_seconds || 0);
}

function mediaTrimEnd(item) {
  const fallback = mediaTrimStart(item) + Math.max(0, (item?.end_seconds || 0) - (item?.start_seconds || 0));
  return Number(item?.source_ref?.trim_end_seconds || fallback);
}

function placeTimelineClip(clip, item) {
  if (!clip || !item) return;
  const metrics = timelineMetrics();
  clip.style.left = `${Math.max(0, item.start_seconds * metrics.pxPerSecond)}px`;
  clip.style.width = `${Math.max(12, (item.end_seconds - item.start_seconds) * metrics.pxPerSecond)}px`;
}

function updateTimelineClipActiveStates() {
  document.querySelectorAll(".vd-timeline-clip").forEach((clip) => {
    clip.dataset.active = clip.dataset.itemId === state.selectedItemId ? "true" : "false";
  });
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}

async function saveStudioText() {
  const item = selectedItem();
  if (!item || item.type !== "text") return;
  item.source_ref = { ...(item.source_ref || {}), text: document.getElementById("studio-text-input").value.trim() };
  await patchTimelineItem(item.item_id, { source_ref: item.source_ref });
}

function startCanvasTextDrag(event) {
  const item = selectedItem();
  if (!item || item.type !== "text") return;
  event.preventDefault();
  const rect = document.getElementById("studio-stage").getBoundingClientRect();
  dragState = {
    kind: "canvas-text",
    itemId: item.item_id,
    rect,
  };
}

function startTimelineDrag(event) {
  const item = state.timeline?.items.find((entry) => entry.item_id === event.currentTarget.dataset.itemId);
  if (!item || !editableTimelineItem(item)) return;
  event.preventDefault();
  event.stopPropagation();
  const lane = event.currentTarget.closest(".vd-track-lane");
  const metrics = timelineMetrics();
  state.selectedItemId = item.item_id;
  state.selectedSceneId = item.scene_id;
  if (item.type === "text") state.selectedTool = "text";
  updateTimelineClipActiveStates();
  renderStudioToolPanel();
  renderStudioStage();
  renderStudioInspector();
  dragState = {
    kind: "timeline",
    itemId: item.item_id,
    edge: event.target.dataset.edge || "move",
    startX: event.clientX,
    clipEl: event.currentTarget,
    laneWidth: lane.getBoundingClientRect().width,
    timelineDuration: metrics.duration,
    pxPerSecond: metrics.pxPerSecond,
    originalStart: item.start_seconds,
    originalEnd: item.end_seconds,
    moved: false,
  };
  event.currentTarget.dataset.dragging = "true";
}

function onPointerMove(event) {
  if (!dragState) return;
  if (dragState.kind === "canvas-text") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const x = clamp(((event.clientX - dragState.rect.left) / dragState.rect.width) * 100, 0, 100);
    const y = clamp(((event.clientY - dragState.rect.top) / dragState.rect.height) * 100, 0, 100);
    item.transform = { ...(item.transform || {}), x: Math.round(x), y: Math.round(y) };
    renderStudioStage();
  }
  if (dragState.kind === "timeline") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const deltaSeconds = (event.clientX - dragState.startX) / dragState.pxPerSecond;
    const maxDuration = Math.max(1, state.timeline.duration_seconds || 1);
    const snap = (value) => Math.round(value * 20) / 20;
    dragState.moved = dragState.moved || Math.abs(event.clientX - dragState.startX) > 2;
    if (dragState.edge === "left") {
      item.start_seconds = snap(clamp(dragState.originalStart + deltaSeconds, 0, item.end_seconds - TIMELINE_MIN_CLIP_SECONDS));
    } else if (dragState.edge === "right") {
      item.end_seconds = snap(clamp(dragState.originalEnd + deltaSeconds, item.start_seconds + TIMELINE_MIN_CLIP_SECONDS, maxDuration));
    } else {
      const duration = dragState.originalEnd - dragState.originalStart;
      const nextStart = snap(clamp(dragState.originalStart + deltaSeconds, 0, Math.max(0, maxDuration - duration)));
      item.start_seconds = nextStart;
      item.end_seconds = snap(Math.min(maxDuration, nextStart + duration));
    }
    placeTimelineClip(dragState.clipEl, item);
    renderStudioInspector();
    updateTimelinePlayhead(state.timelinePlayheadSeconds);
  }
}

async function endPointerDrag() {
  if (!dragState) return;
  const item = state.timeline?.items.find((entry) => entry.item_id === dragState.itemId);
  const shouldPatch = dragState.kind !== "timeline" || dragState.moved;
  const clipEl = dragState.clipEl;
  const patch = item ? { start_seconds: item.start_seconds, end_seconds: item.end_seconds, transform: item.transform } : null;
  dragState = null;
  if (clipEl) clipEl.dataset.dragging = "false";
  if (item && patch && shouldPatch) await patchTimelineItem(item.item_id, patch);
}

async function patchTimelineItem(itemId, patch) {
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, {
    method: "PATCH",
    body: patch,
  });
  const index = state.timeline.items.findIndex((item) => item.item_id === itemId);
  if (index >= 0) state.timeline.items[index] = data.item;
  renderStudio();
}

function setPresetChoice(button) {
  const peers = button.parentElement.querySelectorAll(`[data-preset-path="${button.dataset.presetPath}"]`);
  peers.forEach((peer) => peer.classList.remove("is-selected"));
  button.classList.add("is-selected");
  setByPath(state.preset, button.dataset.presetPath, button.dataset.presetValue);
  renderSummaryRails();
}

function setTemplateChoice(button) {
  document.querySelectorAll("[data-template-id]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.template.template_id = button.dataset.templateId;
  state.preset.template.template_category = "dynamic_template";
  renderSummaryRails();
}

function setCaptionStyle(button) {
  document.querySelectorAll("[data-caption-style]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.captions.style_id = button.dataset.captionStyle;
  state.preset.captions.animation_id = button.dataset.captionStyle;
  renderSummaryRails();
}

async function run(label, handler) {
  try {
    state.running = true;
    setStatus(label, "running");
    await handler();
    setStatus("Ready", "idle");
  } catch (error) {
    setStatus(error.message || String(error), "error");
  } finally {
    state.running = false;
    renderAll();
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json();
  if (!data.success) {
    throw new Error(`${data.error.code}: ${data.error.message}`);
  }
  return data;
}

function startProgressPolling() {
  stopProgressPolling();
  state.lastProgressMessage = "";
  progressTimer = window.setInterval(pollProgress, 2000);
  pollProgress();
}

function stopProgressPolling() {
  if (progressTimer) window.clearInterval(progressTimer);
  progressTimer = null;
}

async function pollProgress() {
  if (!state.projectId) return;
  try {
    const data = await api(`/api/videodesign/projects/${state.projectId}/progress`);
    const progress = data.progress;
    if (!progress?.message) return;
    document.getElementById("search-progress").textContent = `${progress.current}/${progress.total} ${progress.message}`;
    if (progress.message !== state.lastProgressMessage) {
      state.lastProgressMessage = progress.message;
      setStatus(progress.message, progress.stage === "idle" ? "idle" : "running");
    }
    if (progress.stage === "materials_search") {
      await loadReview();
    }
  } catch {
    return;
  }
}

function hydrateProjectFields(updateInputs = true) {
  if (!state.project || !updateInputs) return;
  setInputValue("script-idea", state.project.idea || "");
  setInputValue("script-editor", state.project.script || "");
  if (state.project.split_settings) {
    setInputValue("split-mode", state.project.split_settings.split_mode || "normal");
    setInputValue("max-words", state.project.split_settings.max_words_per_scene || 18);
    setInputValue("scene-seconds", state.project.split_settings.target_scene_duration_seconds || 4);
  }
  setInputValue("tts-provider", state.preset.voiceover.provider || "free_tts");
  setInputValue("voice-id", state.preset.voiceover.voice_id || "en-US-AriaNeural");
  setInputValue("preset-candidate-count", state.preset.scene_media.candidate_count || 4);
  setInputValue("preset-pinterest-count", state.preset.scene_media.pinterest_candidate_count || 4);
  setInputValue("douyin-min-count", state.preset.scene_media.candidate_count || 4);
  setInputValue("pinterest-min-count", state.preset.scene_media.pinterest_candidate_count || 4);
  setInputValue("queries-per-scene", 2);
  setInputChecked("preset-translate", Boolean(state.preset.scene_media.translate_to_chinese));
  setInputChecked("translate-query", Boolean(state.preset.scene_media.translate_to_chinese));
}

function updateDurationLabel() {
  const value = document.getElementById("start-duration").value;
  document.getElementById("start-duration-label").textContent = `${value} seconds`;
}

function updateScriptMetrics() {
  const text = document.getElementById("script-editor")?.value || "";
  const words = wordCount(text);
  const seconds = Math.max(2, Math.round(words / 2.6));
  const scenes = Math.max(0, sentenceCount(text));
  const metrics = document.getElementById("script-metrics");
  if (metrics) metrics.textContent = `${words} words / ${formatDuration(seconds)} / ${scenes} scenes`;
}

function selectFirstScene() {
  state.selectedSceneId = state.rows[0]?.scene.scene_id || "";
}

function selectFirstItemForScene(sceneId) {
  const item = timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === "text") || timelineItems().find((entry) => entry.scene_id === sceneId);
  state.selectedItemId = item?.item_id || "";
}

function selectedRow() {
  return state.rows.find((row) => row.scene.scene_id === state.selectedSceneId) || null;
}

function selectedItem() {
  return timelineItems().find((item) => item.item_id === state.selectedItemId) || null;
}

function timelineItems() {
  return state.timeline?.items || [];
}

function toggleStudioPlayback() {
  const video = document.getElementById("studio-video");
  if (!state.timeline) {
    if (!video.src) return;
    if (video.paused) video.play();
    else video.pause();
    return;
  }
  if (state.timelinePlaying) {
    state.timelinePlaying = false;
    video.pause();
    updateStudioPlaybackButton();
    return;
  }
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const startTime = state.timelinePlayheadSeconds >= duration ? 0 : state.timelinePlayheadSeconds;
  playTimelineFrom(startTime);
}

function playTimelineFrom(globalTime) {
  state.timelinePlaying = true;
  seekTimeline(globalTime, { autoplay: true });
  updateStudioPlaybackButton();
}

function onStudioVideoTimeUpdate() {
  updateStudioClock();
  if (!state.timelinePlaying) return;
  const media = currentMediaItem();
  if (!media) return;
  const video = document.getElementById("studio-video");
  const globalTime = globalTimeFromVideo(media, video);
  if (globalTime >= media.end_seconds - 0.05 || Number(video.currentTime || 0) >= mediaTrimEnd(media) - 0.05) {
    advanceTimelinePlayback(media.end_seconds + 0.001);
  }
}

function onStudioVideoEnded() {
  if (!state.timelinePlaying) return;
  const media = currentMediaItem();
  if (!media) return;
  advanceTimelinePlayback(media.end_seconds + 0.001);
}

function advanceTimelinePlayback(globalTime) {
  if (!state.timeline) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  if (globalTime >= duration - 0.01) {
    state.timelinePlaying = false;
    document.getElementById("studio-video").pause();
    seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  seekTimeline(globalTime, { autoplay: true });
}

function updateStudioClock(forcedGlobalTime = null) {
  const media = currentMediaItem();
  const hasForcedTime = typeof forcedGlobalTime === "number" && Number.isFinite(forcedGlobalTime);
  const globalTime = hasForcedTime ? forcedGlobalTime : globalTimeFromVideo(media);
  state.timelinePlayheadSeconds = clamp(globalTime, 0, Math.max(1, state.timeline?.duration_seconds || 1));
  const time = document.getElementById("studio-time");
  if (time) time.textContent = state.timeline ? `${formatDuration(state.timelinePlayheadSeconds)} / ${formatDuration(state.timeline.duration_seconds)}` : "0:00";
  updateTimelinePlayhead(state.timelinePlayheadSeconds);
}

function updateTimelinePlayhead(globalTime) {
  const playhead = document.getElementById("timeline-playhead");
  if (!playhead) return;
  const duration = Math.max(1, state.timeline?.duration_seconds || 1);
  const metrics = timelineMetrics(duration);
  const left = metrics.labelWidth + clamp(Number(globalTime || 0), 0, duration) * metrics.pxPerSecond;
  playhead.style.left = `${left}px`;
}

function updateStudioPlaybackButton() {
  const video = document.getElementById("studio-video");
  const button = document.getElementById("studio-play");
  if (!button || !video) return;
  button.textContent = state.timelinePlaying || !video.paused ? "Pause" : "Play";
}

function ensureProject() {
  if (!state.projectId) throw new Error("Create or load a project first.");
}

function setStatus(message, mode) {
  const status = document.getElementById("vd-status");
  status.textContent = message;
  status.dataset.mode = mode;
}

function defaultPreset() {
  return {
    format: { aspect_ratio: "9:16", platform: "tiktok", target_duration_seconds: 45 },
    template: { template_id: "short_form_editor", template_category: "timeline_template", scene_pacing: "normal" },
    scene_media: { media_source: "multi_source", candidate_count: 4, pinterest_candidate_count: 4, translate_to_chinese: true },
    voiceover: { provider: "free_tts", voice_id: "en-US-AriaNeural", language: "en" },
    captions: { enabled: true, style_id: "bold_outline", position: "bottom_safe", animation_id: "word_reveal" },
    extras: { transition_pack_id: "clean_cut", overlay_pack_id: "caption_shadow", icon_pack_id: "none" },
  };
}

function mergePreset(base, source) {
  const merged = structuredClone(base);
  for (const [key, value] of Object.entries(source || {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      merged[key] = { ...(merged[key] || {}), ...value };
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

function setByPath(target, path, value) {
  const parts = path.split(".");
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    cursor[part] = cursor[part] || {};
    cursor = cursor[part];
  }
  cursor[parts.at(-1)] = value;
}

function getByPath(target, path) {
  return path.split(".").reduce((cursor, part) => cursor?.[part], target);
}

function templateLabel(value) {
  return {
    short_form_editor: "Short-form editor",
    dynamic_short: "Legacy dynamic short",
    explainer_clean: "Legacy explainer",
    quote_motivation: "Legacy motivation",
  }[value] || value;
}

function captionLabel(value) {
  return {
    bold_outline: "Bold outline",
    word_reveal: "Word reveal",
    clean_lower: "Clean lower third",
  }[value] || String(value || "").replaceAll("_", " ");
}

function transitionLabel(value) {
  return {
    clean_cut: "Clean cut",
    push_slide: "Push slide",
    speed_zoom: "Speed zoom",
    fast_swipes: "Legacy fast swipes",
  }[value] || String(value || "").replaceAll("_", " ");
}

function overlayLabel(value) {
  return {
    caption_shadow: "Caption shadow",
    focus_frame: "Focus frame",
    soft_vignette: "Soft vignette",
    clean_shadow: "Legacy clean shadow",
  }[value] || String(value || "").replaceAll("_", " ");
}

function itemLabel(item) {
  if (!item) return "";
  return {
    media: "Video",
    caption: "Captions",
    text: "Text",
    audio: "Voice",
    transition: "Transition",
  }[item.type] || titleCase(item.type);
}

function mediaLabel(value) {
  return {
    douyin_stock: "Douyin stock",
    multi_source: "Douyin + Pinterest",
    uploads: "Uploads",
    placeholder: "Placeholder",
  }[value] || value;
}

function sourceLabel(value) {
  return {
    douyinsearch: "Douyin",
    pinterestsearch: "Pinterest",
  }[value] || "Source";
}

function textForItem(item) {
  return item?.source_ref?.text || "";
}

function titleCase(value) {
  return String(value).slice(0, 1).toUpperCase() + String(value).slice(1);
}

function wordCount(text) {
  return String(text || "").trim().split(/\s+/).filter(Boolean).length;
}

function sentenceCount(text) {
  return String(text || "").split(/[.!?]+/).map((part) => part.trim()).filter(Boolean).length;
}

function keywordsFromText(text) {
  return String(text || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  const mins = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function inputValue(id, fallback = "") {
  const input = document.getElementById(id);
  return input ? input.value : String(fallback ?? "");
}

function inputChecked(id, fallback = false) {
  const input = document.getElementById(id);
  return input ? Boolean(input.checked) : Boolean(fallback);
}

function setInputValue(id, value) {
  const input = document.getElementById(id);
  if (input) input.value = value;
}

function setInputChecked(id, value) {
  const input = document.getElementById(id);
  if (input) input.checked = Boolean(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}
