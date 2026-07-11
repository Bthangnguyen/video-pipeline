import { api } from "./api.js";
import {
  captionLabel,
  clamp,
  defaultPreset,
  defaultSmoothPreview,
  escapeHtml,
  formatDuration,
  formatProjectDate,
  getByPath,
  inputChecked,
  inputValue,
  itemLabel,
  keywordsFromText,
  mediaLabel,
  mergePreset,
  overlayLabel,
  projectStageLabel,
  rgbaFromHex,
  sentenceCount,
  setByPath,
  setInputChecked,
  setInputValue,
  sourceLabel,
  templateLabel,
  textForItem,
  titleCase,
  transitionLabel,
  uniqueValues,
  videoDefaultsLabel,
  voiceLabel,
  wordCount,
} from "./utils.js";

import {
  CAPTION_MODES,
  FONT_OPTIONS,
  ICON_OPTIONS,
  OVERLAY_OPTIONS,
  SAFE_REALTIME_TRANSITIONS,
  TIMELINE_LABEL_WIDTH,
  TIMELINE_LABEL_WIDTH_COMPACT,
  TIMELINE_MAX_ZOOM,
  TIMELINE_MIN_CLIP_SECONDS,
  TIMELINE_MIN_ZOOM,
  TRANSITION_OPTIONS,
  TRANSITION_PRELOAD_MARGIN,
  state,
  viewTitles,
} from "./state.js";

let progressTimer = null;
let timelineFrameRequest = null;
let dragState = null;

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  updateDurationLabel();
  navigate("start");
  restoreProject();
  loadProjectList();
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.viewTarget));
  });

  document.getElementById("start-duration").addEventListener("input", updateDurationLabel);
  document.getElementById("create-project").addEventListener("click", createProject);
  document.getElementById("refresh-projects").addEventListener("click", loadProjectList);
  document.getElementById("load-saved-project").addEventListener("click", () => {
    const projectId = localStorage.getItem("videodesignProjectId");
    if (projectId) loadProject(projectId, "script");
    else {
      loadProjectList();
      setStatus("Choose a project from the list.", "idle");
    }
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
  document.getElementById("voice-speed").addEventListener("input", () => {
    state.preset.voiceover.voice_speed = Number(document.getElementById("voice-speed").value || 1);
    updateVoiceSpeedLabel();
    renderSummaryRails();
  });
  document.getElementById("preview-voice").addEventListener("click", previewSelectedVoice);
  ["preset-video-flip", "preset-video-brightness", "preset-video-contrast", "preset-video-saturation"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      state.preset.video_defaults = {
        ...(state.preset.video_defaults || {}),
        flip_horizontal: inputChecked("preset-video-flip", false),
        brightness: Number(inputValue("preset-video-brightness", 1)),
        contrast: Number(inputValue("preset-video-contrast", 1.08)),
        saturation: Number(inputValue("preset-video-saturation", 1.08)),
      };
      renderSummaryRails();
    });
  });

  document.getElementById("generate-tts").addEventListener("click", generateTts);
  document.getElementById("save-scene").addEventListener("click", saveSelectedScene);
  document.getElementById("generate-scene-keywords").addEventListener("click", generateSelectedSceneKeywords);
  document.getElementById("generate-all-keywords").addEventListener("click", generateAllSceneKeywords);
  document.getElementById("split-scene").addEventListener("click", splitSelectedScene);
  document.getElementById("merge-prev-scene").addEventListener("click", mergePreviousScene);

  document.getElementById("search-current-scene").addEventListener("click", searchSelectedScene);
  document.getElementById("search-all-scenes").addEventListener("click", searchAllScenes);
  document.getElementById("generate-material-search-plan").addEventListener("click", generateAllSceneKeywords);
  document.getElementById("save-material-keywords").addEventListener("click", saveMaterialKeywords);
  document.getElementById("assign-scene-search-group").addEventListener("click", assignSelectedSceneToGroup);
  document.getElementById("run-material-health").addEventListener("click", runMaterialHealth);
  document.getElementById("clear-scene-candidates").addEventListener("click", clearSelectedSceneCandidates);
  document.getElementById("clear-all-candidates").addEventListener("click", clearAllCandidates);
  document.getElementById("keep-selected-candidates").addEventListener("click", keepSelectedCandidates);
  document.getElementById("download-approved").addEventListener("click", downloadApproved);

  document.getElementById("create-timeline").addEventListener("click", createTimeline);
  document.getElementById("clear-timeline").addEventListener("click", clearTimeline);
  document.getElementById("build-smooth-preview").addEventListener("click", buildSmoothPreview);
  document.getElementById("toggle-smooth-preview").addEventListener("click", toggleSmoothPreviewMode);
  document.getElementById("render-export").addEventListener("click", renderExportVideo);
  document.getElementById("download-export").addEventListener("click", downloadExportVideo);
  document.getElementById("studio-play").addEventListener("click", toggleStudioPlayback);
  bindStudioVideoEvents(document.getElementById("studio-video"));
  bindStudioVideoEvents(document.getElementById("studio-next-video"));
  document.getElementById("studio-audio").addEventListener("timeupdate", onStudioAudioTimeUpdate);
  document.getElementById("studio-audio").addEventListener("play", updateStudioPlaybackButton);
  document.getElementById("studio-audio").addEventListener("pause", updateStudioPlaybackButton);
  document.getElementById("studio-music").addEventListener("play", updateStudioPlaybackButton);
  document.getElementById("studio-music").addEventListener("pause", updateStudioPlaybackButton);
  document.getElementById("timeline-fit").addEventListener("click", fitTimeline);
  document.getElementById("timeline-zoom-out").addEventListener("click", () => zoomTimeline(-1));
  document.getElementById("timeline-zoom-in").addEventListener("click", () => zoomTimeline(1));
  document.getElementById("timeline-ruler").addEventListener("pointerdown", seekTimelineFromPointer);
  document.getElementById("timeline-tracks").addEventListener("pointerdown", seekTimelineFromPointer);
  document.getElementById("timeline-playhead").addEventListener("pointerdown", startPlayheadDrag);
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTool = button.dataset.studioTool;
      renderStudio();
    });
  });

  document.getElementById("studio-text").addEventListener("pointerdown", startCanvasTextDrag);
  document.getElementById("studio-caption").addEventListener("pointerdown", startCanvasCaptionDrag);
  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", endPointerDrag);
}

function bindStudioVideoEvents(video) {
  if (!video) return;
  video.addEventListener("timeupdate", onStudioVideoTimeUpdate);
  video.addEventListener("loadedmetadata", updateStudioClock);
  video.addEventListener("ended", onStudioVideoEnded);
  video.addEventListener("play", updateStudioPlaybackButton);
  video.addEventListener("pause", updateStudioPlaybackButton);
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
        target_platform: "short_vertical",
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
    await loadProjectList();
    navigate("script");
  });
}

async function loadProject(projectId, preferredView = null) {
  await run("Loading project", async () => {
    const data = await api(`/api/videodesign/projects/${projectId}`);
    state.project = data.project;
    state.projectId = data.project.project_id;
    state.preset = mergePreset(defaultPreset(), state.project.design_preset || {});
    state.smoothPreview = state.project.smooth_preview || defaultSmoothPreview();
    localStorage.setItem("videodesignProjectId", state.projectId);
    hydrateProjectFields();
    await loadReview();
    await loadTimeline();
    renderProjectList();
    navigate(preferredView || (state.timeline ? "studio" : "script"));
  });
}

async function loadProjectList() {
  try {
    const data = await api("/api/videodesign/projects");
    state.projects = data.projects || [];
    renderProjectList();
  } catch (error) {
    const library = document.getElementById("project-library");
    if (library) library.innerHTML = `<div class="vd-empty">Could not load projects.</div>`;
  }
}

function renderProjectList() {
  const library = document.getElementById("project-library");
  if (!library) return;
  if (!state.projects.length) {
    library.innerHTML = `<div class="vd-empty">No saved projects yet.</div>`;
    return;
  }
  library.innerHTML = state.projects.slice(0, 12).map((project) => `
    <button class="vd-project-card" data-open-project="${escapeHtml(project.project_id)}" data-active="${project.project_id === state.projectId ? "true" : "false"}" type="button">
      <strong>${escapeHtml(project.title || project.project_id)}</strong>
      <span>${escapeHtml(projectStageLabel(project.stage))} / ${escapeHtml(project.aspect_ratio || "9:16")}</span>
      <em>${project.scene_count || 0} scenes / ${project.downloaded_count || 0} media / ${formatDuration(project.timeline_duration_seconds || project.target_duration_seconds || 0)}</em>
      <small>${escapeHtml(formatProjectDate(project.created_at))}</small>
    </button>
  `).join("");
  library.querySelectorAll("[data-open-project]").forEach((button) => {
    button.addEventListener("click", () => loadProject(button.dataset.openProject));
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
  state.preset.voiceover.voice_speed = clamp(Number(inputValue("voice-speed", state.preset.voiceover.voice_speed || 1)), 0.8, 1.25);
  state.preset.video_defaults = {
    ...(state.preset.video_defaults || {}),
    flip_horizontal: inputChecked("preset-video-flip", false),
    brightness: Number(inputValue("preset-video-brightness", 1)),
    contrast: Number(inputValue("preset-video-contrast", 1.08)),
    saturation: Number(inputValue("preset-video-saturation", 1.08)),
  };
  const data = await api(`/api/videodesign/projects/${state.projectId}/preset`, {
    method: "PATCH",
    body: state.preset,
  });
  state.project = data.project;
}

function previewSelectedVoice() {
  const synth = window.speechSynthesis;
  if (!synth) {
    setStatus("Voice preview is not supported in this browser.", "error");
    return;
  }
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance("This is a short preview of the selected voice and reading speed.");
  utterance.lang = inputValue("voice-id", "en-US-AriaNeural").startsWith("en-GB") ? "en-GB" : "en-US";
  utterance.rate = clamp(Number(inputValue("voice-speed", 1)), 0.8, 1.25);
  const browserVoices = synth.getVoices();
  const preferred = browserVoices.find((voice) => voice.lang === utterance.lang) || browserVoices.find((voice) => voice.lang?.startsWith("en"));
  if (preferred) utterance.voice = preferred;
  synth.speak(utterance);
}

async function generateTts() {
  ensureProject();
  await run("Generating project voiceover and timing", async () => {
    await savePreset();
    const data = await api(`/api/videodesign/projects/${state.projectId}/tts/generate`, {
      method: "POST",
      body: {
        provider: state.preset.voiceover.provider,
        voice_id: state.preset.voiceover.voice_id,
        voice_speed: state.preset.voiceover.voice_speed || 1,
      },
    });
    state.project = data.project || state.project;
    if (data.voiceover_track && state.project) {
      state.project.voiceover_track = data.voiceover_track;
    }
    state.timeline = null;
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    await loadReview();
    setStatus("Project voiceover generated as one continuous track.", "idle");
  });
}

async function buildCombinedVoiceover(options = {}) {
  ensureProject();
  const data = await api(`/api/videodesign/projects/${state.projectId}/audio/combined`, { method: "POST" });
  state.project = {
    ...(state.project || {}),
    voiceover_track: data.voiceover_track,
  };
  if (options.refresh !== false) {
    await loadReview();
    if (state.timeline) await loadTimeline();
  }
  return data.voiceover_track;
}

async function clearGeneratedTts() {
  ensureProject();
  if (!window.confirm("Clear all generated TTS audio for this project? The Studio timeline will need to be created again.")) return;
  await run("Clearing generated TTS", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/tts`, { method: "DELETE" });
    state.project = data.project;
    state.timeline = null;
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    state.selectedItemId = "";
    await loadReview();
    setStatus(`Cleared generated TTS audio (${data.deleted_files || 0} file(s)).`, "idle");
  });
}

async function loadReview() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/review`);
  state.rows = data.rows;
  if (data.search_plan) {
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    const popularToggle = document.getElementById("popular-first");
    if (popularToggle) popularToggle.checked = data.search_plan.popular_first !== false;
  }
  if (!state.selectedSceneId || !state.rows.some((row) => row.scene.scene_id === state.selectedSceneId)) {
    selectFirstScene();
  }
  const groupIds = new Set(materialSearchGroups().map((group) => group.group_id));
  if (!groupIds.has(state.selectedSearchGroupId)) {
    state.selectedSearchGroupId = selectedRow()?.scene?.search_group_id || materialSearchGroups()[0]?.group_id || "";
  }
  renderAll();
}

async function loadTimeline() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline`);
  state.timeline = data.timeline;
  await loadSmoothPreview({ render: false });
  await loadSfxSuggestions({ render: false });
  if (state.timeline && !state.selectedItemId) {
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
  }
  renderAll();
}

async function loadSmoothPreview(options = {}) {
  if (!state.projectId) return defaultSmoothPreview();
  const data = await api(`/api/videodesign/projects/${state.projectId}/preview`);
  state.smoothPreview = data.preview || defaultSmoothPreview();
  if (!smoothPreviewUsable() && state.previewMode === "smooth") {
    state.previewMode = "realtime";
  }
  if (options.render !== false) renderStudio();
  return state.smoothPreview;
}

async function loadSfxCatalog(options = {}) {
  if (state.sfxCatalogLoading || (state.sfxCatalog.length && state.sfxTransitionPresets.length)) return state.sfxCatalog;
  state.sfxCatalogLoading = true;
  try {
    const data = await api("/api/videodesign/sfx/catalog");
    state.sfxCatalog = data.items || [];
    state.sfxTransitionPresets = data.transition_presets || [];
    if (options.render !== false) renderStudio();
  } finally {
    state.sfxCatalogLoading = false;
  }
  return state.sfxCatalog;
}

async function loadSfxSuggestions(options = {}) {
  if (!state.projectId) return [];
  const data = await api(`/api/videodesign/projects/${state.projectId}/sfx/suggestions`);
  state.sfxSuggestions = data.suggestions || [];
  if (options.render !== false) renderStudio();
  return state.sfxSuggestions;
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
  const douyinKeyword = inputValue("materials-douyin-keyword").trim();
  const pinterestKeyword = inputValue("materials-pinterest-keyword").trim();
  const group = selectedMaterialSearchGroup(row);
  if (group) {
    const plan = cloneMaterialSearchPlan();
    const editable = plan.groups.find((item) => item.group_id === group.group_id);
    if (!editable) return;
    editable.douyin_keyword = douyinKeyword;
    editable.pinterest_keyword = pinterestKeyword;
    const data = await api(`/api/videodesign/projects/${state.projectId}/search-plan`, {
      method: "PATCH",
      body: plan,
    });
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    return;
  }
  const keywords = uniqueValues([pinterestKeyword, douyinKeyword]);
  const visualPlan = {
    ...sceneVisualSearchPlan(row.scene),
    douyin_primary_keyword: douyinKeyword,
    pinterest_primary_keyword: pinterestKeyword,
  };
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
    method: "PATCH",
    body: { matching_keywords: keywords, visual_search_plan: visualPlan },
  });
}

async function assignSelectedSceneToGroup() {
  const row = selectedRow();
  const targetGroupId = inputValue("scene-search-group").trim();
  if (!row || !targetGroupId || row.scene.search_group_id === targetGroupId) return;
  await run("Moving scene to search pool", async () => {
    const plan = cloneMaterialSearchPlan();
    const current = plan.groups.find((group) => (group.scene_ids || []).includes(row.scene.scene_id));
    if (current?.role === "base" && current.scene_ids.length === 1) {
      throw new Error("The base pool must keep at least one scene.");
    }
    plan.groups.forEach((group) => {
      group.scene_ids = (group.scene_ids || []).filter((sceneId) => sceneId !== row.scene.scene_id);
    });
    const target = plan.groups.find((group) => group.group_id === targetGroupId);
    if (!target) throw new Error("Selected search group no longer exists.");
    target.scene_ids.push(row.scene.scene_id);
    plan.groups = plan.groups.filter((group) => group.scene_ids.length);
    const data = await api(`/api/videodesign/projects/${state.projectId}/search-plan`, {
      method: "PATCH",
      body: plan,
    });
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    state.selectedSearchGroupId = targetGroupId;
    await loadReview();
  });
}

async function runMaterialHealth() {
  const row = selectedRow();
  const keyword = inputValue("materials-douyin-keyword").trim()
    || inputValue("materials-pinterest-keyword").trim()
    || materialKeywordsForScene(row?.scene).douyin
    || materialKeywordsForScene(row?.scene).pinterest
    || "cat";
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
  const group = selectedMaterialSearchGroup(row);
  if (!row || !group) {
    setStatus("Generate or select a search group first.", "error");
    return;
  }
  await run("Searching selected group", async () => {
    await saveMaterialKeywordsDraft(row);
    const body = materialSearchBody(null, [group.group_id]);
    await api(`/api/videodesign/projects/${state.projectId}/materials/search`, {
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

async function keepSelectedCandidates() {
  ensureProject();
  const sceneIds = state.rows.filter(rowHasApprovedCandidate).map((row) => row.scene.scene_id);
  if (!sceneIds.length) {
    setStatus("No selected candidates are ready to keep.", "idle");
    return;
  }
  if (!window.confirm(`Remove unselected candidate videos from ${sceneIds.length} selected scene(s)?`)) return;
  await run("Keeping selected videos", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/materials/prune`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    state.previewCandidateId = "";
    await loadReview();
    setStatus(`Kept ${data.kept} selected video(s), removed ${data.removed} extra candidate(s).`, "idle");
  });
}

async function downloadApproved() {
  ensureProject();
  await run("Downloading approved videos", async () => {
    const sceneIds = state.rows
      .filter((row) => rowHasApprovedCandidate(row) && !row.scene.material_asset_id)
      .map((row) => row.scene.scene_id);
    if (!sceneIds.length) throw new Error("No approved scenes are waiting for download.");
    const data = await api(`/api/videodesign/projects/${state.projectId}/materials/download`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    await loadReview();
    if (data.skipped?.length) {
      setStatus(`Downloaded ${data.assets.length} video(s), skipped ${data.skipped.length} scene(s) without approved candidates.`, "idle");
    }
  });
}

async function createTimeline() {
  ensureProject();
  await run("Creating Studio timeline", async () => {
    if (!combinedVoiceoverTrack() && state.rows.length && state.rows.every((row) => row.scene.tts?.sync_state === "synced")) {
      await buildCombinedVoiceover({ refresh: false });
    }
    const data = await api(`/api/videodesign/projects/${state.projectId}/studio`, { method: "POST" });
    state.timeline = data.timeline;
    await loadSmoothPreview({ render: false });
    await loadSfxSuggestions({ render: false });
    const firstMedia = state.timeline.items.find((item) => item.type === "media");
    state.selectedItemId = firstMedia?.item_id || state.timeline.items[0]?.item_id || "";
    if (firstMedia) {
      state.selectedSceneId = firstMedia.scene_id;
      state.selectedTool = "media";
    }
    renderStudio();
  });
}

async function clearTimeline() {
  ensureProject();
  if (!state.timeline && !window.confirm("No timeline is loaded. Clear the saved timeline state anyway?")) return;
  if (state.timeline && !window.confirm("Clear the current Studio timeline? Materials, TTS, and downloaded videos will stay available.")) return;
  await run("Clearing Studio timeline", async () => {
    state.timelinePlaying = false;
    pauseStudioMedia();
    await api(`/api/videodesign/projects/${state.projectId}/timeline`, { method: "DELETE" });
    state.timeline = null;
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    state.selectedItemId = "";
    state.timelinePlayheadSeconds = 0;
    renderStudio();
    setStatus("Timeline cleared. You can create it again from the current materials.", "idle");
  });
}

async function buildSmoothPreview() {
  ensureProject();
  if (!state.timeline) throw new Error("Create a Studio timeline first.");
  await run("Rendering smooth preview", async () => {
    state.timelinePlaying = false;
    pauseStudioMedia();
    state.smoothPreview = { ...(state.smoothPreview || defaultSmoothPreview()), status: "rendering", error: {} };
    renderSmoothPreviewControls();
    const data = await api(`/api/videodesign/projects/${state.projectId}/preview/render`, { method: "POST" });
    state.smoothPreview = data.preview || defaultSmoothPreview();
    state.previewMode = smoothPreviewUsable() ? "smooth" : "realtime";
    seekTimeline(state.timelinePlayheadSeconds || 0);
    setStatus("Smooth preview rendered.", "idle");
  });
}

async function renderExportVideo() {
  ensureProject();
  if (!state.timeline) throw new Error("Create a Studio timeline first.");
  await run("Rendering export MP4", async () => {
    state.timelinePlaying = false;
    pauseStudioMedia();
    state.smoothPreview = { ...(state.smoothPreview || defaultSmoothPreview()), status: "rendering", error: {} };
    renderSmoothPreviewControls();
    const data = await api(`/api/videodesign/projects/${state.projectId}/export/render`, { method: "POST" });
    state.smoothPreview = data.preview || defaultSmoothPreview();
    state.previewMode = smoothPreviewUsable() ? "smooth" : "realtime";
    await loadProjectList();
    seekTimeline(state.timelinePlayheadSeconds || 0);
    setStatus("Export MP4 is ready to download.", "idle");
  });
}

function downloadExportVideo() {
  ensureProject();
  if (state.smoothPreview?.status !== "ready" || !state.smoothPreview?.preview_url) {
    setStatus("Render export first.", "error");
    return;
  }
  window.location.href = `/api/videodesign/projects/${state.projectId}/export/file`;
}

function toggleSmoothPreviewMode() {
  if (state.previewMode === "smooth") {
    state.previewMode = "realtime";
    state.timelinePlaying = false;
    pauseStudioMedia();
    renderStudio();
    return;
  }
  if (!smoothPreviewUsable()) {
    setStatus("Build smooth preview first.", "error");
    return;
  }
  state.previewMode = "smooth";
  state.timelinePlaying = false;
  pauseStudioMedia();
  renderStudio();
}

function rowHasApprovedCandidate(row) {
  if (!row?.scene?.selected_candidate_id) return false;
  const selected = row.candidates?.find((candidate) => candidate.candidate_id === row.scene.selected_candidate_id);
  return selected?.status === "approved";
}

function materialSearchBody(sceneIds = null, groupIds = null) {
  const douyinMin = Number(inputValue("douyin-min-count", state.preset.scene_media.candidate_count || 0));
  const pinterestMin = Number(inputValue("pinterest-min-count", state.preset.scene_media.pinterest_candidate_count || 0));
  return {
    scene_ids: sceneIds,
    group_ids: groupIds,
    candidates_per_scene: Math.max(douyinMin, 1),
    douyin_min_per_scene: douyinMin,
    pinterest_min_per_scene: pinterestMin,
    queries_per_scene: 2,
    translate_to_chinese: true,
    use_smart_keywords: false,
    popular_first: inputChecked("popular-first", true),
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
  renderProjectList();
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
    ${summaryRow("Video defaults", videoDefaultsLabel(state.preset.video_defaults))}
    ${summaryRow("Voiceover", `${voiceLabel(state.preset.voiceover.voice_id)} - ${Number(state.preset.voiceover.voice_speed || 1).toFixed(2)}x`)}
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
      const row = state.rows.find((item) => item.scene.scene_id === state.selectedSceneId);
      state.selectedSearchGroupId = row?.scene?.search_group_id || state.selectedSearchGroupId;
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
  const voiceoverTrack = combinedVoiceoverTrack();
  const sceneUsesProjectVoice = !audioUrl && row?.scene.tts?.sync_state === "synced" && voiceoverTrack?.audio_url;
  panel.innerHTML = `
    <h3>TTS status</h3>
    <p class="vd-muted">${synced}/${rows.length} scenes have audio timing.</p>
    <div class="vd-audio-preview">
      <strong>Project voiceover</strong>
      ${voiceoverTrack?.audio_url ? `<audio controls preload="none" src="${voiceoverTrack.audio_url}"></audio><p class="vd-muted">${formatDuration(voiceoverTrack.duration_seconds || 0)} continuous timeline audio.</p>` : `<p class="vd-muted">Generate TTS to create one continuous Studio voiceover.</p>`}
      <button id="build-combined-voiceover" type="button" ${rows.length && synced === rows.length ? "" : "disabled"}>${voiceoverTrack?.audio_url ? "Refresh voiceover track" : "Build voiceover track"}</button>
      <button id="clear-generated-tts" class="vd-danger" type="button" ${synced || voiceoverTrack?.audio_url ? "" : "disabled"}>Clear generated TTS</button>
    </div>
    <div class="vd-audio-preview">
      <strong>${row ? `Scene ${row.scene.order} voice` : "Voice preview"}</strong>
      ${audioUrl ? `<audio controls preload="none" src="${audioUrl}"></audio>` : sceneUsesProjectVoice ? `<p class="vd-muted">This scene is timed inside the project voiceover track.</p>` : `<p class="vd-muted">Generate TTS to preview the selected scene voice.</p>`}
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
  panel.querySelector("#build-combined-voiceover")?.addEventListener("click", () => {
    run("Building combined voiceover", async () => {
      await buildCombinedVoiceover();
      setStatus("Combined voiceover is ready for Studio playback.", "idle");
    });
  });
  panel.querySelector("#clear-generated-tts")?.addEventListener("click", clearGeneratedTts);
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
  hydrateCandidateCoverImages(board);
}

function candidateCards(candidates, row, source) {
  if (!candidates.length) return `<div class="vd-empty">No ${escapeHtml(sourceLabel(source))} candidates yet.</div>`;
  return candidates.map((candidate) => {
    const coverSrc = candidateCoverSrc(candidate);
    const coverState = state.materialCoverCache[candidate.candidate_id]?.state || "loading";
    const orderLabel = candidateOrderLabel(candidate);
    const usedBy = candidateUsedByScene(candidate, row.scene.scene_id);
    const likes = Number(candidate.stats?.digg_count || 0);
    return `
      <article class="vd-candidate ${candidate.status === "approved" ? "is-approved" : ""}">
        <img src="${escapeHtml(coverSrc)}" alt="" loading="eager" decoding="async" data-cover-candidate-id="${escapeHtml(candidate.candidate_id)}" data-cover-url="${escapeHtml(candidate.cover_url || "")}" data-cover-state="${escapeHtml(coverState)}">
        <div>
          <div class="vd-candidate-badges">
            <span class="vd-source-badge">${escapeHtml(sourceLabel(candidate.source))}</span>
            <span class="vd-order-badge" data-applied="${candidate.popularity?.applied === true}">${escapeHtml(orderLabel)}</span>
          </div>
          <h3>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</h3>
          <p>${escapeHtml(candidate.match_reason)}</p>
          <p>${formatDuration(candidate.duration)}${likes ? ` / ${escapeHtml(formatCompactCount(likes))} likes` : ""}</p>
          ${usedBy ? `<p class="vd-used-note">Also selected in Scene ${usedBy.scene.order}</p>` : ""}
          <div class="vd-button-row">
            <button data-approve-candidate="${candidate.candidate_id}" data-approve-scene="${row.scene.scene_id}" type="button">${candidate.status === "approved" ? "Approved" : "Approve"}</button>
            <button data-preview-candidate="${candidate.candidate_id}" type="button">Preview</button>
            <button data-delete-candidate="${candidate.candidate_id}" data-delete-scene="${row.scene.scene_id}" class="vd-danger" type="button">Delete</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function candidateOrderLabel(candidate) {
  if (candidate.source === "pinterestsearch") return "Platform order";
  if (candidate.popularity?.applied) return "Popular";
  if (candidate.popularity?.requested) return "Popular unavailable";
  return "Relevance";
}

function candidateUsedByScene(candidate, currentSceneId) {
  const sourceId = candidate.source_result_id || candidate.source_item_id || candidate.douyin_aweme_id;
  if (!sourceId) return null;
  return state.rows.find((row) => {
    if (row.scene.scene_id === currentSceneId || !row.scene.selected_candidate_id) return false;
    const selected = row.candidates.find((item) => item.candidate_id === row.scene.selected_candidate_id);
    const selectedSourceId = selected?.source_result_id || selected?.source_item_id || selected?.douyin_aweme_id;
    return selected?.source === candidate.source && selectedSourceId === sourceId;
  }) || null;
}

function formatCompactCount(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(number >= 100_000 ? 0 : 1)}K`;
  return String(Math.round(number));
}

function candidateCoverSrc(candidate) {
  const cached = state.materialCoverCache[candidate.candidate_id];
  return cached?.objectUrl || cached?.url || candidate.cover_url || "";
}

function hydrateCandidateCoverImages(container) {
  container.querySelectorAll("[data-cover-candidate-id]").forEach((image) => {
    const candidateId = image.dataset.coverCandidateId;
    const coverUrl = image.dataset.coverUrl || "";
    if (!candidateId || !coverUrl) {
      image.dataset.coverState = "empty";
      return;
    }
    const cached = state.materialCoverCache[candidateId];
    if (cached?.objectUrl) {
      image.src = cached.objectUrl;
      image.dataset.coverState = "loaded";
      return;
    }
    image.addEventListener("load", () => {
      state.materialCoverCache[candidateId] = { ...(state.materialCoverCache[candidateId] || {}), url: coverUrl, state: "loaded" };
      image.dataset.coverState = "loaded";
    }, { once: true });
    image.addEventListener("error", () => {
      state.materialCoverCache[candidateId] = { ...(state.materialCoverCache[candidateId] || {}), url: coverUrl, state: "error" };
      image.dataset.coverState = "error";
    }, { once: true });
    if (cached?.fetching || cached?.state === "error") return;
    state.materialCoverCache[candidateId] = { url: coverUrl, state: "loading", fetching: true };
    fetch(coverUrl, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error("cover fetch failed");
        return response.blob();
      })
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        state.materialCoverCache[candidateId] = { url: coverUrl, objectUrl, state: "loaded" };
        if (document.body.contains(image)) {
          image.src = objectUrl;
          image.dataset.coverState = "loaded";
        }
      })
      .catch(() => {
        state.materialCoverCache[candidateId] = { url: coverUrl, state: "error" };
        if (document.body.contains(image)) image.dataset.coverState = "error";
      });
  });
}

function renderMaterialControls(row) {
  const group = selectedMaterialSearchGroup(row);
  const plan = sceneVisualSearchPlan(row?.scene);
  const keywords = group
    ? { douyin: group.douyin_keyword || "", pinterest: group.pinterest_keyword || "" }
    : materialKeywordsForScene(row?.scene);
  renderMaterialSearchGroups();
  const title = document.getElementById("materials-group-title");
  const role = document.getElementById("materials-group-role");
  if (title) title.textContent = group?.label || "Select a search group";
  if (role) {
    role.textContent = titleCase(group?.role || "base");
    role.dataset.role = group?.role || "base";
  }
  const chips = document.getElementById("materials-keyword-chips");
  if (chips) {
    chips.innerHTML = keywords.douyin || keywords.pinterest
      ? `
        ${keywords.douyin ? `<button data-keyword-source="douyin" type="button"><strong>Douyin</strong> ${escapeHtml(keywords.douyin)}</button>` : ""}
        ${keywords.pinterest ? `<button data-keyword-source="pinterest" type="button"><strong>Pinterest</strong> ${escapeHtml(keywords.pinterest)}</button>` : ""}
      `
      : `<span class="vd-muted">No visual search plan yet.</span>`;
    chips.querySelectorAll("[data-keyword-source]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.keywordSource === "douyin") setInputValue("materials-douyin-keyword", keywords.douyin || "");
        if (button.dataset.keywordSource === "pinterest") setInputValue("materials-pinterest-keyword", keywords.pinterest || "");
      });
    });
  }
  setInputValue("materials-douyin-keyword", keywords.douyin || "");
  setInputValue("materials-pinterest-keyword", keywords.pinterest || "");
  renderSceneSearchGroupSelect(row, group);
  renderVisualSearchNotes(plan, group);
  renderSearchErrors(row);
  renderMaterialHealth();
  renderMaterialPreview(row);
}

function renderMaterialSearchGroups() {
  const panel = document.getElementById("materials-search-groups");
  if (!panel) return;
  const groups = materialSearchGroups();
  if (!groups.length) {
    panel.innerHTML = `<div class="vd-empty vd-search-plan-empty">Generate a shared search plan before searching video.</div>`;
    return;
  }
  panel.innerHTML = groups.map((group) => {
    const rows = state.rows.filter((row) => (group.scene_ids || []).includes(row.scene.scene_id));
    const candidateCount = rows.reduce((maximum, row) => Math.max(maximum, row.candidates.length), 0);
    return `
      <button class="vd-search-group" data-search-group-id="${escapeHtml(group.group_id)}" data-active="${group.group_id === selectedMaterialSearchGroup()?.group_id}" type="button">
        <span class="vd-pool-badge" data-role="${escapeHtml(group.role)}">${escapeHtml(titleCase(group.role))}</span>
        <strong>${escapeHtml(group.label || group.pinterest_keyword || group.douyin_keyword)}</strong>
        <em>${rows.length} scene${rows.length === 1 ? "" : "s"} / ${candidateCount} candidates</em>
      </button>
    `;
  }).join("");
  panel.querySelectorAll("[data-search-group-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = groups.find((item) => item.group_id === button.dataset.searchGroupId);
      state.selectedSearchGroupId = group?.group_id || "";
      if (group?.scene_ids?.length) state.selectedSceneId = group.scene_ids[0];
      renderAll();
    });
  });
}

function renderSceneSearchGroupSelect(row, activeGroup) {
  const select = document.getElementById("scene-search-group");
  if (!select) return;
  const groups = materialSearchGroups();
  select.innerHTML = groups.length
    ? groups.map((group) => `<option value="${escapeHtml(group.group_id)}">${escapeHtml(titleCase(group.role))}: ${escapeHtml(group.label || group.pinterest_keyword)}</option>`).join("")
    : `<option value="">No search groups</option>`;
  select.value = row?.scene?.search_group_id || activeGroup?.group_id || "";
  select.disabled = !row || !groups.length;
  const button = document.getElementById("assign-scene-search-group");
  if (button) button.disabled = !row || groups.length < 2;
}

function renderVisualSearchNotes(plan, group = null) {
  const panel = document.getElementById("materials-visual-notes");
  if (!panel) return;
  if (!group && (!plan || !Object.keys(plan).length)) {
    panel.innerHTML = `<p class="vd-muted">Generate a shared search plan first.</p>`;
    return;
  }
  const douyinFallbacks = group?.douyin_fallback ? [group.douyin_fallback] : (plan.fallbacks?.douyin || []);
  const pinterestFallbacks = group?.pinterest_fallback ? [group.pinterest_fallback] : (plan.fallbacks?.pinterest || []);
  panel.innerHTML = `
    ${group ? `<p><strong>${group.scene_ids.length} assigned scene${group.scene_ids.length === 1 ? "" : "s"}</strong></p>` : ""}
    ${group?.exact_subject ? `<p><strong>Exact subject</strong> ${escapeHtml(group.exact_subject)}</p>` : ""}
    ${!group && plan.retention_role ? `<p><strong>Role</strong> ${escapeHtml(plan.retention_role)}</p>` : ""}
    ${!group && plan.content_anchor ? `<p><strong>Anchor</strong> ${escapeHtml(plan.content_anchor)}</p>` : ""}
    ${!group && plan.material_notes ? `<p>${escapeHtml(plan.material_notes)}</p>` : ""}
    ${douyinFallbacks.length || pinterestFallbacks.length ? `
      <p class="vd-muted">Fallbacks:
        ${douyinFallbacks.length ? `Douyin ${douyinFallbacks.map(escapeHtml).join(", ")}` : ""}
        ${pinterestFallbacks.length ? ` Pinterest ${pinterestFallbacks.map(escapeHtml).join(", ")}` : ""}
      </p>
    ` : ""}
  `;
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
  const sources = materialPreviewSources(candidate);
  panel.innerHTML = `
    <h4>${escapeHtml(sourceLabel(candidate.source))} preview</h4>
    <video data-material-preview-video controls playsinline preload="metadata" poster="${escapeHtml(candidate.cover_url || "")}"></video>
    <div class="vd-preview-status" data-material-preview-status>${sources.length ? "Loading preview..." : "No preview URL is available for this candidate."}</div>
    ${sources.length > 1 ? `
      <div class="vd-preview-sources">
        ${sources.map((source, index) => `<button data-preview-source-index="${index}" type="button">${escapeHtml(source.label)}</button>`).join("")}
      </div>
    ` : ""}
    <strong>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</strong>
    <p>${escapeHtml(candidate.search_keyword || candidate.match_reason || "")}</p>
  `;
  setupMaterialPreviewVideo(panel, sources);
}

function materialPreviewSources(candidate) {
  const sources = [];
  const add = (url, label) => {
    const value = String(url || "").trim();
    if (!value || sources.some((source) => source.url === value)) return;
    sources.push({ url: value, label });
  };
  if (candidate.source === "pinterestsearch") {
    add(candidate.media_url, "Media");
    add(candidate.stream_url, "Stream");
    add(candidate.download_url, "Download");
  } else {
    add(candidate.stream_url, "Stream");
    add(candidate.download_url, "Download");
  }
  return sources;
}

function setupMaterialPreviewVideo(panel, sources) {
  const video = panel.querySelector("[data-material-preview-video]");
  const status = panel.querySelector("[data-material-preview-status]");
  const buttons = Array.from(panel.querySelectorAll("[data-preview-source-index]"));
  if (!video || !sources.length) return;

  let activeIndex = 0;
  const setStatusText = (message) => {
    if (status) status.textContent = message;
  };
  const updateButtons = () => {
    buttons.forEach((button) => {
      button.dataset.active = Number(button.dataset.previewSourceIndex) === activeIndex ? "true" : "false";
    });
  };
  const setSource = (index, message = "") => {
    activeIndex = index;
    const source = sources[activeIndex];
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.src = source.url;
    video.load();
    setStatusText(message || `Loading ${source.label.toLowerCase()} preview...`);
    updateButtons();
  };

  video.addEventListener("loadedmetadata", () => setStatusText(`Preview ready via ${sources[activeIndex].label.toLowerCase()}.`));
  video.addEventListener("error", () => {
    const failed = sources[activeIndex];
    if (activeIndex < sources.length - 1) {
      const next = sources[activeIndex + 1];
      setSource(activeIndex + 1, `${failed.label} preview failed, trying ${next.label.toLowerCase()}...`);
      return;
    }
    setStatusText("Preview failed in browser. Try approving/downloading this candidate, or choose another result.");
  });
  buttons.forEach((button) => {
    button.addEventListener("click", () => setSource(Number(button.dataset.previewSourceIndex || 0)));
  });
  setSource(0);
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
  renderSmoothPreviewControls();
  renderStudioToolPanel();
  renderStudioStage();
  renderStudioInspector();
  renderTimeline();
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}

function smoothPreviewUsable() {
  return ["ready", "stale"].includes(state.smoothPreview?.status) && Boolean(state.smoothPreview?.preview_url);
}

function smoothPreviewActive() {
  return state.previewMode === "smooth" && smoothPreviewUsable();
}

function markSmoothPreviewStale() {
  if (!state.smoothPreview?.preview_url) {
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    return;
  }
  if (state.smoothPreview.status === "ready") {
    state.smoothPreview = { ...state.smoothPreview, status: "stale" };
  }
}

function renderSmoothPreviewControls() {
  const build = document.getElementById("build-smooth-preview");
  const toggle = document.getElementById("toggle-smooth-preview");
  const renderExport = document.getElementById("render-export");
  const downloadExport = document.getElementById("download-export");
  const label = document.getElementById("smooth-preview-status");
  const preview = state.smoothPreview || defaultSmoothPreview();
  if (build) {
    build.disabled = !state.timeline || preview.status === "rendering" || state.running;
    build.textContent = preview.status === "rendering" ? "Rendering..." : preview.status === "ready" ? "Rebuild smooth preview" : "Build smooth preview";
  }
  if (toggle) {
    toggle.disabled = !smoothPreviewUsable();
    toggle.dataset.active = smoothPreviewActive() ? "true" : "false";
    toggle.textContent = smoothPreviewActive() ? "Use realtime preview" : "Use smooth preview";
  }
  if (renderExport) {
    renderExport.disabled = !state.timeline || preview.status === "rendering" || state.running;
    renderExport.textContent = preview.status === "rendering" ? "Rendering..." : preview.status === "ready" ? "Re-render export" : "Render export";
  }
  if (downloadExport) {
    downloadExport.disabled = preview.status !== "ready" || !preview.preview_url || preview.status === "rendering";
  }
  if (label) {
    label.dataset.status = preview.status || "missing";
    label.textContent = smoothPreviewStatusLabel(preview);
  }
}

function smoothPreviewStatusLabel(preview) {
  const status = preview?.status || "missing";
  if (status === "ready") return `Smooth ready ${formatDuration(preview.duration_seconds || state.timeline?.duration_seconds || 0)}`;
  if (status === "stale") return "Smooth stale - rebuild";
  if (status === "rendering") return "Rendering smooth preview";
  if (status === "failed") return preview?.error?.message || "Smooth preview failed";
  return "Preview missing";
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
    renderTextStylePanel(panel, row);
  } else if (state.selectedTool === "media") {
    renderStudioMediaPanel(panel, row);
  } else if (state.selectedTool === "captions") {
    renderCaptionStylePanel(panel, row);
  } else if (state.selectedTool === "overlay") {
    renderOverlayPanel(panel, row);
  } else if (state.selectedTool === "transitions") {
    renderTransitionsPanel(panel, row);
  } else if (state.selectedTool === "icons") {
    renderIconsPanel(panel, row);
  } else if (state.selectedTool === "audio") {
    renderAudioPanel(panel);
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

function renderTextStylePanel(panel, row) {
  const item = selectedItem()?.type === "text" ? selectedItem() : itemForScene("text", row);
  if (!row || !item) {
    panel.innerHTML = `<h3>Text overlay</h3><p class="vd-muted">Select a scene with a text item.</p>`;
    return;
  }
  const style = textStyle(item);
  const transform = item.transform || {};
  panel.innerHTML = `
    <h3>Text overlay</h3>
    <label>Text <input id="studio-text-input" value="${escapeHtml(textForItem(item))}" placeholder="Optional text overlay"></label>
    <label>Font <select id="studio-text-font">${fontOptionsHtml(style.font_family)}</select></label>
    <div class="vd-control-grid">
      <label>Size <input id="studio-text-size" type="number" min="14" max="120" value="${Number(style.font_size || 42)}"></label>
      <label>Color <input id="studio-text-color" type="color" value="${escapeHtml(style.text_color || "#ffffff")}"></label>
    </div>
    <div class="vd-button-row">
      <label><input id="studio-text-bold" type="checkbox" ${Number(style.font_weight || 700) >= 700 ? "checked" : ""}> Bold</label>
      <label><input id="studio-text-italic" type="checkbox" ${style.italic ? "checked" : ""}> Italic</label>
      <label><input id="studio-text-shadow" type="checkbox" ${style.shadow !== false ? "checked" : ""}> Shadow</label>
    </div>
    <label>Scale <input id="studio-text-scale" type="range" min="0.5" max="2" step="0.05" value="${Number(transform.scale || 1)}"></label>
    <p class="vd-muted">Drag the text directly on the preview canvas.</p>
    <button id="save-studio-text" class="vd-primary" type="button">Save text style</button>
  `;
  panel.querySelectorAll("input, select").forEach((input) => input.addEventListener("input", () => applyTextDraftToStage(panel, item)));
  panel.querySelector("#save-studio-text")?.addEventListener("click", () => saveStudioText(panel, item));
  applyTextDraftToStage(panel, item);
}

function renderCaptionStylePanel(panel, row) {
  const item = itemForScene("caption", row);
  if (!row || !item) {
    panel.innerHTML = `<h3>Captions</h3><p class="vd-muted">Create a timeline with captions first.</p>`;
    return;
  }
  const style = captionStyle(item);
  panel.innerHTML = `
    <h3>Captions</h3>
    <label>Display mode <select id="caption-mode">${optionListHtml(CAPTION_MODES, style.caption_mode || "active_word_highlight", captionModeLabel)}</select></label>
    <label>Font <select id="caption-font">${fontOptionsHtml(style.font_family)}</select></label>
    <div class="vd-control-grid">
      <label>Size <input id="caption-size" type="number" min="14" max="120" value="${Number(style.font_size || 46)}"></label>
      <label>Text <input id="caption-color" type="color" value="${escapeHtml(style.text_color || "#ffffff")}"></label>
      <label>Active <input id="caption-active-color" type="color" value="${escapeHtml(style.active_word_color || "#3ce6ac")}"></label>
      <label>Outline <input id="caption-stroke-color" type="color" value="${escapeHtml(style.stroke_color || "#111111")}"></label>
    </div>
    <div class="vd-button-row">
      <label><input id="caption-bold" type="checkbox" ${Number(style.font_weight || 800) >= 700 ? "checked" : ""}> Bold</label>
      <label><input id="caption-italic" type="checkbox" ${style.italic ? "checked" : ""}> Italic</label>
      <label><input id="caption-shadow" type="checkbox" ${style.shadow !== false ? "checked" : ""}> Shadow</label>
      <label><input id="caption-glow" type="checkbox" ${style.glow !== false ? "checked" : ""}> Word glow</label>
    </div>
    <div class="vd-control-grid">
      <label>Glow color <input id="caption-glow-color" type="color" value="${escapeHtml(style.glow_color || style.active_word_color || "#3ce6ac")}"></label>
      <label>Glow blur <input id="caption-glow-blur" type="range" min="0" max="26" step="1" value="${Number(style.glow_blur ?? 14)}"></label>
      <label>Glow power <input id="caption-glow-intensity" type="range" min="0" max="1" step="0.05" value="${Number(style.glow_intensity ?? 0.75)}"></label>
    </div>
    <p class="vd-muted">Drag the caption directly on the preview canvas.</p>
    <div class="vd-button-row">
      <button id="save-caption-style" class="vd-primary" type="button">Save scene captions</button>
      <button id="apply-caption-all" type="button">Apply all scenes</button>
    </div>
  `;
  panel.querySelectorAll("input, select").forEach((input) => {
    const applyDraft = () => applyCaptionDraftToStage(panel, item);
    input.addEventListener("input", applyDraft);
    input.addEventListener("change", applyDraft);
  });
  panel.querySelector("#save-caption-style")?.addEventListener("click", () => saveCaptionStyle(panel, item));
  panel.querySelector("#apply-caption-all")?.addEventListener("click", () => applyCaptionStyleAll(panel, item));
  applyCaptionDraftToStage(panel, item);
}

function renderOverlayPanel(panel, row) {
  const item = itemForScene("overlay", row);
  const overlayId = overlayIdForItem(item);
  const opacity = Number(item?.style?.opacity ?? 0.35);
  panel.innerHTML = `
    <h3>Overlay</h3>
    <div class="vd-option-grid">
      ${OVERLAY_OPTIONS.map((id) => optionButtonHtml("overlay-option", id, overlayLabel(id), id === overlayId)).join("")}
    </div>
    <label>Opacity <input id="overlay-opacity" type="range" min="0" max="0.9" step="0.05" value="${opacity}"></label>
    <div class="vd-button-row">
      <button id="save-overlay" class="vd-primary" type="button">Apply scene</button>
      <button id="apply-overlay-all" type="button">Apply all scenes</button>
    </div>
  `;
  panel.querySelectorAll("[data-overlay-option]").forEach((button) => {
    button.addEventListener("click", () => {
      panel.querySelectorAll("[data-overlay-option]").forEach((peer) => peer.dataset.active = "false");
      button.dataset.active = "true";
      previewOverlay(button.dataset.overlayOption, Number(inputValue("overlay-opacity", opacity)));
    });
  });
  panel.querySelector("#overlay-opacity")?.addEventListener("input", () => previewOverlay(selectedOption(panel, "overlay-option"), Number(inputValue("overlay-opacity", opacity))));
  panel.querySelector("#save-overlay")?.addEventListener("click", () => saveOverlay(row?.scene.scene_id, selectedOption(panel, "overlay-option"), Number(inputValue("overlay-opacity", opacity))));
  panel.querySelector("#apply-overlay-all")?.addEventListener("click", () => applyOverlayAll(selectedOption(panel, "overlay-option"), Number(inputValue("overlay-opacity", opacity))));
  previewOverlay(overlayId, opacity);
}

function renderTransitionsPanel(panel, row) {
  const item = itemForScene("transition", row);
  const transitionId = transitionIdForItem(item);
  const duration = Number(item?.style?.duration_seconds || 0.35);
  const isLast = row && !_transitionHasNextScene(row.scene.scene_id);
  panel.innerHTML = `
    <h3>Transitions</h3>
    ${isLast ? `<p class="vd-muted">This is the last scene, so there is no next cut.</p>` : ""}
    <label>Type <select id="transition-id">${optionListHtml(TRANSITION_OPTIONS, transitionId, transitionLabel)}</select></label>
    <label>Duration <select id="transition-duration">${optionListHtml(["0.25", "0.35", "0.50", "0.75"], String(duration.toFixed(2)), (value) => `${value}s`)}</select></label>
    <div class="vd-button-row">
      <button id="apply-transition" class="vd-primary" type="button" ${isLast ? "disabled" : ""}>Apply selected cut</button>
      <button id="apply-transition-all" type="button">Apply all cuts</button>
      <button id="random-transition" type="button">Random mix</button>
      <button id="clear-transition-all" type="button">Clear all</button>
    </div>
  `;
  panel.querySelector("#apply-transition")?.addEventListener("click", () => saveSelectedTransition(row.scene.scene_id));
  panel.querySelector("#apply-transition-all")?.addEventListener("click", () => saveAllTransitions(inputValue("transition-id", "fade")));
  panel.querySelector("#random-transition")?.addEventListener("click", randomizeTransitions);
  panel.querySelector("#clear-transition-all")?.addEventListener("click", () => saveAllTransitions("none"));
}

function renderIconsPanel(panel, row) {
  const item = selectedItem()?.type === "icon" ? selectedItem() : itemForScene("icon", row);
  panel.innerHTML = `
    <h3>Icons</h3>
    <div class="vd-icon-picker">
      ${ICON_OPTIONS.map((id) => optionButtonHtml("icon-option", id, iconPreview(id), false)).join("")}
    </div>
    <button id="add-icon" class="vd-primary" type="button">Add icon</button>
    ${item ? `
      <hr>
      <label>Color <input id="icon-color" type="color" value="${escapeHtml(item.style?.color || "#ffffff")}"></label>
      <label>Size <input id="icon-scale" type="range" min="0.4" max="2.5" step="0.05" value="${Number(item.transform?.scale || 1)}"></label>
      <label>Rotation <input id="icon-rotation" type="range" min="-45" max="45" step="1" value="${Number(item.transform?.rotation || 0)}"></label>
      <div class="vd-button-row">
        <button id="save-icon" type="button">Save icon</button>
        <button id="delete-icon" class="vd-danger" type="button">Delete</button>
      </div>
      <p class="vd-muted">Drag the icon directly on the preview canvas.</p>
    ` : `<p class="vd-muted">Choose an icon and add it to the selected scene.</p>`}
  `;
  panel.querySelectorAll("[data-icon-option]").forEach((button) => {
    button.addEventListener("click", () => {
      panel.querySelectorAll("[data-icon-option]").forEach((peer) => peer.dataset.active = "false");
      button.dataset.active = "true";
    });
  });
  panel.querySelector("#add-icon")?.addEventListener("click", () => addIconToScene(row?.scene.scene_id, selectedOption(panel, "icon-option") || "arrow_right"));
  panel.querySelectorAll("#icon-color, #icon-scale, #icon-rotation").forEach((input) => {
    input.addEventListener("input", () => applyIconDraftToStage(panel, item));
  });
  panel.querySelector("#save-icon")?.addEventListener("click", () => saveIcon(panel, item));
  panel.querySelector("#delete-icon")?.addEventListener("click", () => deleteTimelineItem(item?.item_id));
}

function renderAudioPanel(panel) {
  if (!state.timeline) {
    panel.innerHTML = `<h3>Audio</h3><p class="vd-muted">Create a timeline before adding SFX.</p>`;
    return;
  }
  if (!state.sfxCatalog.length && !state.sfxCatalogLoading) {
    loadSfxCatalog({ render: true }).catch(() => {});
  }
  const sfxItems = timelineItems().filter((item) => item.type === "sfx");
  const musicItem = backgroundMusicItem();
  const proposed = state.sfxSuggestions.filter((item) => item.status === "proposed");
  const applied = state.sfxSuggestions.filter((item) => item.status === "applied");
  panel.innerHTML = `
    <h3>Audio</h3>
    <section class="vd-audio-section">
      <strong>Background Music</strong>
      <div class="vd-music-upload">
        <input id="music-file" type="file" accept="audio/*">
        <button id="upload-music" type="button">Upload music</button>
      </div>
      ${musicItem ? backgroundMusicControlsHtml(musicItem) : `<div class="vd-empty">No background music track.</div>`}
    </section>
    <section class="vd-audio-section">
      <strong>Event-driven SFX</strong>
      <p class="vd-muted">Suggestions come from transitions, text, icons, hook moments, and important caption words.</p>
      <div class="vd-button-row">
        <button id="generate-sfx" class="vd-primary" type="button">Generate SFX suggestions</button>
        <button id="apply-sfx" type="button" ${proposed.length ? "" : "disabled"}>Apply selected</button>
        <button id="clear-sfx" class="vd-danger" type="button" ${sfxItems.length ? "" : "disabled"}>Clear SFX</button>
      </div>
      <div class="vd-summary-row"><span>Timeline SFX</span><strong>${sfxItems.length}</strong></div>
      <div class="vd-summary-row"><span>Suggestions</span><strong>${proposed.length} proposed / ${applied.length} applied</strong></div>
    </section>
    <section class="vd-audio-section">
      <strong>Suggestions</strong>
      ${proposed.length ? proposed.map((suggestion) => sfxSuggestionRow(suggestion)).join("") : `<div class="vd-empty">Generate suggestions to place SFX automatically.</div>`}
    </section>
    <section class="vd-audio-section">
      <strong>Transition SFX rules</strong>
      ${state.sfxTransitionPresets.length ? transitionSfxRulesHtml() : `<div class="vd-muted">Loading transition SFX rules...</div>`}
    </section>
    <section class="vd-audio-section">
      <strong>SFX catalog</strong>
      ${state.sfxCatalog.length ? state.sfxCatalog.map((asset) => `
        <div class="vd-sfx-row">
          <div>
            <b>${escapeHtml(asset.name)}</b>
            <span>${escapeHtml(asset.category)} / ${formatDuration(asset.duration_seconds || 0)}</span>
          </div>
          <button data-preview-sfx="${asset.asset_id}" type="button">Play</button>
        </div>
      `).join("") : `<div class="vd-muted">Loading SFX catalog...</div>`}
    </section>
  `;
  panel.querySelector("#upload-music")?.addEventListener("click", uploadBackgroundMusic);
  panel.querySelector("#save-music")?.addEventListener("click", saveBackgroundMusic);
  panel.querySelector("#remove-music")?.addEventListener("click", () => {
    const item = backgroundMusicItem();
    if (item) deleteTimelineItem(item.item_id);
  });
  panel.querySelector("#music-volume")?.addEventListener("input", () => updateMusicSliderLabel("music-volume", "music-volume-label"));
  panel.querySelector("#music-ducking-volume")?.addEventListener("input", () => updateMusicSliderLabel("music-ducking-volume", "music-ducking-volume-label"));
  panel.querySelector("#music-trim-start")?.addEventListener("input", () => updateMusicTrimControls("start"));
  panel.querySelector("#music-trim-end")?.addEventListener("input", () => updateMusicTrimControls("end"));
  panel.querySelector("#music-trim-start-range")?.addEventListener("input", () => updateMusicTrimControls("start_range"));
  panel.querySelector("#music-trim-end-range")?.addEventListener("input", () => updateMusicTrimControls("end_range"));
  panel.querySelector("#generate-sfx")?.addEventListener("click", generateSfxSuggestions);
  panel.querySelector("#apply-sfx")?.addEventListener("click", applySelectedSfxSuggestions);
  panel.querySelector("#clear-sfx")?.addEventListener("click", clearTimelineSfx);
  panel.querySelectorAll("[data-preview-sfx]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      previewSfx(button.dataset.previewSfx, sfxPreviewVolume(button));
    });
  });
  panel.querySelectorAll("[data-sfx-volume]").forEach((input) => {
    input.addEventListener("input", () => {
      const label = panel.querySelector(`[data-sfx-volume-label="${CSS.escape(input.dataset.sfxVolume)}"]`);
      if (label) label.textContent = `${Math.round(Number(input.value || 0) * 100)}%`;
      const suggestion = state.sfxSuggestions.find((item) => item.suggestion_id === input.dataset.sfxVolume);
      if (suggestion) suggestion.volume = Number(input.value || suggestion.volume || 0.35);
    });
  });
}

function backgroundMusicControlsHtml(item) {
  const style = item.style || {};
  const volume = clamp(Number(style.volume ?? 0.16), 0, 1);
  const duckingVolume = clamp(Number(style.ducking_volume ?? 0.08), 0, 1);
  const sourceDuration = Math.max(0.05, Number(item.source_ref?.duration_seconds || 0.05));
  const trimStart = clamp(Number(item.source_ref?.trim_start_seconds || 0), 0, Math.max(0, sourceDuration - 0.05));
  const trimEnd = clamp(Number(item.source_ref?.trim_end_seconds || sourceDuration), trimStart + 0.05, sourceDuration);
  return `
    <div class="vd-music-card">
      <div>
        <b>${escapeHtml(item.source_ref?.name || "Background music")}</b>
        <span>${formatDuration(sourceDuration)} source / trim <b id="music-trim-label">${formatDuration(trimStart)}-${formatDuration(trimEnd)}</b> / timeline ${formatDuration(item.end_seconds - item.start_seconds)}</span>
      </div>
      <audio controls preload="none" src="${escapeHtml(item.source_ref?.audio_url || "")}"></audio>
      <label class="vd-music-control">Volume
        <input id="music-volume" type="range" min="0" max="100" step="1" value="${Math.round(volume * 100)}">
        <b id="music-volume-label">${Math.round(volume * 100)}%</b>
      </label>
      <label class="vd-music-control">Voice ducking
        <input id="music-ducking-volume" type="range" min="0" max="100" step="1" value="${Math.round(duckingVolume * 100)}">
        <b id="music-ducking-volume-label">${Math.round(duckingVolume * 100)}%</b>
      </label>
      <div class="vd-music-trim">
        <label>Trim start <input id="music-trim-start" type="number" min="0" max="${sourceDuration.toFixed(2)}" step="0.1" value="${trimStart.toFixed(2)}"></label>
        <label>Trim end <input id="music-trim-end" type="number" min="0.05" max="${sourceDuration.toFixed(2)}" step="0.1" value="${trimEnd.toFixed(2)}"></label>
        <input id="music-trim-start-range" type="range" min="0" max="${sourceDuration.toFixed(2)}" step="0.1" value="${trimStart.toFixed(2)}">
        <input id="music-trim-end-range" type="range" min="0.05" max="${sourceDuration.toFixed(2)}" step="0.1" value="${trimEnd.toFixed(2)}">
      </div>
      <div class="vd-form-grid">
        <label>Fade in <input id="music-fade-in" type="number" min="0" max="10" step="0.1" value="${Number(style.fade_in_seconds ?? 1)}"></label>
        <label>Fade out <input id="music-fade-out" type="number" min="0" max="10" step="0.1" value="${Number(style.fade_out_seconds ?? 1)}"></label>
      </div>
      <div class="vd-button-row">
        <label><input id="music-ducking" type="checkbox" ${style.ducking !== false ? "checked" : ""}> Duck under voice</label>
        <label><input id="music-loop" type="checkbox" ${style.loop !== false ? "checked" : ""}> Loop</label>
      </div>
      <div class="vd-button-row">
        <button id="save-music" type="button">Save music mix</button>
        <button id="remove-music" class="vd-danger" type="button">Remove music</button>
      </div>
    </div>
  `;
}

function sfxSuggestionRow(suggestion) {
  const asset = sfxAsset(suggestion.asset_id);
  const volume = clamp(Number(suggestion.volume ?? asset?.default_volume ?? 0.35), 0, 1);
  return `
    <div class="vd-sfx-row vd-sfx-suggestion">
      <input data-sfx-suggestion-id="${suggestion.suggestion_id}" type="checkbox" checked>
      <div>
        <b>${escapeHtml(suggestion.label)}</b>
        <span>${formatDuration(suggestion.time_seconds)} / ${escapeHtml(suggestion.event_type.replaceAll("_", " "))}</span>
        <em>${escapeHtml(suggestion.reason)}</em>
        <div class="vd-sfx-volume-row">
          <span>Volume</span>
          <input data-sfx-volume="${escapeHtml(suggestion.suggestion_id)}" type="range" min="0" max="1" step="0.01" value="${volume}">
          <b data-sfx-volume-label="${escapeHtml(suggestion.suggestion_id)}">${Math.round(volume * 100)}%</b>
        </div>
      </div>
      <button data-preview-sfx="${suggestion.asset_id}" data-preview-sfx-suggestion="${escapeHtml(suggestion.suggestion_id)}" type="button">${escapeHtml(asset?.name || suggestion.asset_id)}</button>
    </div>
  `;
}

function transitionSfxRulesHtml() {
  const order = ["fade", "dissolve", "slide_left", "slide_right", "slide_up", "whip_pan", "zoom_in", "zoom_out", "flash_cut", "none"];
  const presets = [...state.sfxTransitionPresets].sort((a, b) => {
    const ai = order.indexOf(a.transition_id);
    const bi = order.indexOf(b.transition_id);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
  return presets.map((preset) => `
    <div class="vd-sfx-rule">
      <span>${escapeHtml(transitionLabel(preset.transition_id))}</span>
      <b>${preset.enabled ? escapeHtml(preset.asset_name || preset.category) : "No SFX"}</b>
      <em>${preset.enabled ? `${Math.round(Number(preset.volume || 0) * 100)}% / ${formatDuration(preset.duration_seconds || 0)}` : "manual only"}</em>
    </div>
  `).join("");
}

function backgroundMusicItem() {
  return timelineItems().find((item) => item.type === "music") || null;
}

function updateMusicSliderLabel(inputId, labelId) {
  const input = document.getElementById(inputId);
  const label = document.getElementById(labelId);
  if (input && label) label.textContent = `${Math.round(Number(input.value || 0))}%`;
}

function updateMusicTrimControls(source) {
  const item = backgroundMusicItem();
  const duration = Math.max(0.05, Number(item?.source_ref?.duration_seconds || 0.05));
  const startInput = document.getElementById("music-trim-start");
  const endInput = document.getElementById("music-trim-end");
  const startRange = document.getElementById("music-trim-start-range");
  const endRange = document.getElementById("music-trim-end-range");
  if (!startInput || !endInput || !startRange || !endRange) return;
  if (source === "start_range") startInput.value = startRange.value;
  if (source === "end_range") endInput.value = endRange.value;
  let start = clamp(Number(startInput.value || 0), 0, Math.max(0, duration - 0.05));
  let end = clamp(Number(endInput.value || duration), 0.05, duration);
  if (source.startsWith("start") && start >= end - 0.05) end = clamp(start + 0.05, 0.05, duration);
  if (source.startsWith("end") && end <= start + 0.05) start = clamp(end - 0.05, 0, duration - 0.05);
  startInput.value = start.toFixed(2);
  endInput.value = end.toFixed(2);
  startRange.value = start.toFixed(2);
  endRange.value = end.toFixed(2);
  const label = document.getElementById("music-trim-label");
  if (label) label.textContent = `${formatDuration(start)}-${formatDuration(end)}`;
}

async function uploadBackgroundMusic() {
  const input = document.getElementById("music-file");
  const file = input?.files?.[0];
  if (!file) {
    setStatus("Choose an audio file first.", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  await run("Uploading background music", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/music/upload`, {
      method: "POST",
      formData,
    });
    state.timeline = data.timeline;
    markSmoothPreviewStale();
    setStatus("Background music added.", "idle");
  });
}

async function saveBackgroundMusic() {
  const item = backgroundMusicItem();
  if (!item) return;
  const sourceDuration = Math.max(0.05, Number(item.source_ref?.duration_seconds || 0.05));
  const trimStart = clamp(Number(inputValue("music-trim-start", 0)), 0, Math.max(0, sourceDuration - 0.05));
  const trimEnd = clamp(Number(inputValue("music-trim-end", sourceDuration)), trimStart + 0.05, sourceDuration);
  const style = {
    ...(item.style || {}),
    enabled: true,
    volume: clamp(Number(inputValue("music-volume", 16)) / 100, 0, 1),
    ducking: inputChecked("music-ducking", true),
    ducking_volume: clamp(Number(inputValue("music-ducking-volume", 8)) / 100, 0, 1),
    fade_in_seconds: clamp(Number(inputValue("music-fade-in", 1)), 0, 10),
    fade_out_seconds: clamp(Number(inputValue("music-fade-out", 1)), 0, 10),
    loop: inputChecked("music-loop", true),
  };
  const sourceRef = {
    ...(item.source_ref || {}),
    trim_start_seconds: Number(trimStart.toFixed(3)),
    trim_end_seconds: Number(trimEnd.toFixed(3)),
  };
  await run("Saving background music", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${item.item_id}`, {
      method: "PATCH",
      body: { style, source_ref: sourceRef },
    });
    replaceTimelineItem(data.item);
    markSmoothPreviewStale();
    setStatus("Background music mix saved.", "idle");
  });
}

async function generateSfxSuggestions() {
  await run("Generating SFX suggestions", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/sfx/suggest`, {
      method: "POST",
      body: {
        max_suggestions: 12,
        include_caption_words: true,
        include_transitions: true,
        include_icons: true,
        include_text: true,
        include_hook: true,
      },
    });
    state.sfxSuggestions = data.suggestions || [];
    await loadSfxCatalog({ render: false });
    setStatus(`Generated ${state.sfxSuggestions.length} SFX suggestion(s).`, "idle");
  });
}

async function applySelectedSfxSuggestions() {
  const ids = Array.from(document.querySelectorAll("[data-sfx-suggestion-id]:checked")).map((input) => input.dataset.sfxSuggestionId);
  if (!ids.length) {
    setStatus("Select at least one SFX suggestion.", "error");
    return;
  }
  await run("Applying SFX", async () => {
    const volumeOverrides = {};
    for (const id of ids) {
      const input = document.querySelector(`[data-sfx-volume="${CSS.escape(id)}"]`);
      if (input) volumeOverrides[id] = clamp(Number(input.value || 0.35), 0, 1);
    }
    const data = await api(`/api/videodesign/projects/${state.projectId}/sfx/apply`, {
      method: "POST",
      body: { suggestion_ids: ids, volume_overrides: volumeOverrides },
    });
    state.timeline = data.timeline;
    state.sfxSuggestions = data.suggestions || state.sfxSuggestions;
    markSmoothPreviewStale();
    setStatus(`Applied ${data.applied?.length || 0} SFX item(s).`, "idle");
  });
}

async function clearTimelineSfx() {
  const items = timelineItems().filter((item) => item.type === "sfx");
  if (!items.length) return;
  if (!window.confirm(`Remove ${items.length} SFX item(s) from the timeline?`)) return;
  await run("Clearing SFX", async () => {
    for (const item of items) {
      await deleteTimelineItem(item.item_id, false);
    }
    await loadTimeline();
    markSmoothPreviewStale();
  });
}

function sfxPreviewVolume(button) {
  const suggestionId = button.dataset.previewSfxSuggestion;
  if (!suggestionId) return undefined;
  const input = document.querySelector(`[data-sfx-volume="${CSS.escape(suggestionId)}"]`);
  return input ? clamp(Number(input.value || 0.35), 0, 1) : undefined;
}

function previewSfx(assetId, volumeOverride = undefined) {
  const asset = sfxAsset(assetId);
  const url = asset?.audio_url || `/api/videodesign/sfx/${assetId}/file`;
  const audio = new Audio(url);
  audio.volume = clamp(Number(volumeOverride ?? Math.min(0.8, Number(asset?.default_volume || 0.35) * 1.4)), 0, 1);
  const promise = audio.play();
  if (promise?.catch) promise.catch(() => setStatus("Browser blocked SFX preview. Try clicking Play again.", "error"));
}

function sfxAsset(assetId) {
  return state.sfxCatalog.find((asset) => asset.asset_id === assetId) || null;
}

function itemForScene(type, row = selectedRow()) {
  return timelineItems().find((item) => item.type === type && item.scene_id === row?.scene.scene_id) || null;
}

function itemsForScene(type, row = selectedRow()) {
  return timelineItems().filter((item) => item.type === type && item.scene_id === row?.scene.scene_id);
}

function fontOptionsHtml(selected) {
  return optionListHtml(FONT_OPTIONS, selected || "Montserrat", (value) => value);
}

function optionListHtml(values, selected, labeler) {
  return values.map((value) => `<option value="${escapeHtml(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(labeler(value))}</option>`).join("");
}

function optionButtonHtml(datasetName, value, label, active) {
  return `<button data-${datasetName}="${escapeHtml(value)}" data-active="${active ? "true" : "false"}" type="button">${label}</button>`;
}

function selectedOption(panel, datasetName) {
  return panel.querySelector(`[data-${datasetName}][data-active="true"]`)?.dataset[toDatasetKey(datasetName)] || "";
}

function toDatasetKey(name) {
  return name.replace(/-([a-z])/g, (_match, char) => char.toUpperCase());
}

function textStyle(item) {
  return {
    font_family: "Montserrat",
    font_size: 42,
    font_weight: 800,
    italic: false,
    text_color: "#ffffff",
    shadow: true,
    ...(item?.style || {}),
  };
}

function captionStyle(item) {
  return {
    caption_mode: "one_word",
    font_family: "Montserrat",
    font_size: 46,
    font_weight: 800,
    italic: false,
    text_color: "#ffffff",
    active_word_color: "#3ce6ac",
    stroke_color: "#111111",
    shadow: true,
    glow: true,
    glow_color: "#3ce6ac",
    glow_blur: 14,
    glow_intensity: 0.75,
    ...(item?.style || {}),
  };
}

function collectTextStyle(panel) {
  return {
    font_family: inputValue("studio-text-font", "Montserrat"),
    font_size: Number(inputValue("studio-text-size", 42)),
    font_weight: inputChecked("studio-text-bold", true) ? 800 : 400,
    italic: inputChecked("studio-text-italic", false),
    text_color: inputValue("studio-text-color", "#ffffff"),
    shadow: inputChecked("studio-text-shadow", true),
  };
}

function collectCaptionStyle(panel) {
  return {
    caption_mode: inputValue("caption-mode", "one_word"),
    font_family: inputValue("caption-font", "Montserrat"),
    font_size: Number(inputValue("caption-size", 46)),
    font_weight: inputChecked("caption-bold", true) ? 800 : 400,
    italic: inputChecked("caption-italic", false),
    text_color: inputValue("caption-color", "#ffffff"),
    active_word_color: inputValue("caption-active-color", "#3ce6ac"),
    stroke_color: inputValue("caption-stroke-color", "#111111"),
    shadow: inputChecked("caption-shadow", true),
    glow: inputChecked("caption-glow", true),
    glow_color: inputValue("caption-glow-color", inputValue("caption-active-color", "#3ce6ac")),
    glow_blur: Number(inputValue("caption-glow-blur", 14)),
    glow_intensity: Number(inputValue("caption-glow-intensity", 0.75)),
  };
}

function applyTextDraftToStage(panel, item) {
  if (!item) return;
  item.source_ref = { ...(item.source_ref || {}), text: inputValue("studio-text-input", textForItem(item)) };
  item.source_ref.user_text = true;
  item.style = collectTextStyle(panel);
  item.transform = { ...(item.transform || {}), scale: Number(inputValue("studio-text-scale", item.transform?.scale || 1)) };
  renderStudioText(item);
}

function applyCaptionDraftToStage(panel, item) {
  if (!item) return;
  item.style = collectCaptionStyle(panel);
  updateCaptionPreview(state.timelinePlayheadSeconds);
}

async function saveCaptionStyle(panel, item) {
  if (!item || item.type !== "caption") return;
  applyCaptionDraftToStage(panel, item);
  await patchTimelineItem(item.item_id, { style: item.style, transform: item.transform });
}

async function applyCaptionStyleAll(panel, item) {
  if (!item || item.type !== "caption") return;
  applyCaptionDraftToStage(panel, item);
  const style = { ...(item.style || {}) };
  const transform = { ...(item.transform || {}) };
  const captionItems = timelineItems().filter((entry) => entry.type === "caption");
  for (const captionItem of captionItems) {
    captionItem.style = { ...(captionItem.style || {}), ...style };
    captionItem.transform = { ...(captionItem.transform || {}), ...transform };
    await patchTimelineItem(captionItem.item_id, { style: captionItem.style, transform: captionItem.transform }, { render: false });
  }
  renderStudio();
}

function overlayIdForItem(item) {
  return item?.source_ref?.overlay_id || item?.source_ref?.overlay_pack_id || item?.style?.overlay_pack_id || "none";
}

function transitionIdForItem(item) {
  return item?.source_ref?.transition_id || item?.source_ref?.transition_pack_id || item?.style?.transition_id || item?.style?.transition_pack_id || "none";
}

function previewOverlay(overlayId, opacity = 0.35) {
  const stage = document.getElementById("studio-stage");
  if (!stage) return;
  stage.dataset.overlay = overlayId || "none";
  stage.style.setProperty("--scene-overlay-opacity", String(opacity));
}

async function saveOverlay(sceneId, overlayId, opacity) {
  if (!sceneId) return;
  await run("Saving overlay", async () => {
    await upsertOverlayForScene(sceneId, overlayId, opacity);
  });
}

async function applyOverlayAll(overlayId, opacity) {
  await run("Applying overlay", async () => {
    for (const row of state.rows) {
      await upsertOverlayForScene(row.scene.scene_id, overlayId, opacity);
    }
  });
}

async function upsertOverlayForScene(sceneId, overlayId, opacity) {
  const existing = timelineItems().find((item) => item.scene_id === sceneId && item.type === "overlay");
  if (overlayId === "none") {
    if (existing) await deleteTimelineItem(existing.item_id, false);
    return;
  }
  const patch = {
    source_ref: { overlay_id: overlayId, overlay_pack_id: overlayId },
    style: { overlay_id: overlayId, overlay_pack_id: overlayId, opacity },
  };
  if (existing) {
    const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${existing.item_id}`, {
      method: "PATCH",
      body: patch,
    });
    replaceTimelineItem(data.item);
    markSmoothPreviewStale();
    return;
  }
  const bounds = sceneBounds(sceneId);
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items`, {
    method: "POST",
    body: {
      scene_id: sceneId,
      type: "overlay",
      layer_id: "overlay_default",
      start_seconds: bounds.start,
      end_seconds: bounds.end,
      ...patch,
    },
  });
  state.timeline = data.timeline;
  markSmoothPreviewStale();
}

function _transitionHasNextScene(sceneId) {
  const media = timelineItems().filter((item) => item.type === "media").sort((a, b) => a.start_seconds - b.start_seconds);
  return media.findIndex((item) => item.scene_id === sceneId) >= 0 && media.findIndex((item) => item.scene_id === sceneId) < media.length - 1;
}

async function saveSelectedTransition(sceneId) {
  await run("Saving transition", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/transition`, {
      method: "POST",
      body: {
        transition_id: inputValue("transition-id", "fade"),
        duration_seconds: Number(inputValue("transition-duration", 0.35)),
      },
    });
    state.timeline = data.timeline;
    markSmoothPreviewStale();
  });
}

async function saveAllTransitions(transitionId) {
  await run("Applying transitions", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/transitions/apply-all`, {
      method: "POST",
      body: {
        transition_id: transitionId,
        duration_seconds: Number(inputValue("transition-duration", 0.35)),
      },
    });
    state.timeline = data.timeline;
    markSmoothPreviewStale();
  });
}

async function randomizeTransitions() {
  await run("Randomizing transitions", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/transitions/randomize`, { method: "POST" });
    state.timeline = data.timeline;
    markSmoothPreviewStale();
  });
}

async function addIconToScene(sceneId, iconId) {
  if (!sceneId) return;
  await run("Adding icon", async () => {
    const bounds = sceneBounds(sceneId);
    const start = clamp(state.timelinePlayheadSeconds || bounds.start, bounds.start, Math.max(bounds.start, bounds.end - 0.4));
    const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items`, {
      method: "POST",
      body: {
        scene_id: sceneId,
        type: "icon",
        layer_id: "icon",
        start_seconds: start,
        end_seconds: Math.min(bounds.end, start + 1.8),
        source_ref: { icon_id: iconId },
        transform: { x: 58, y: 42, scale: 1, rotation: 0 },
        style: { color: "#ffffff", shadow: true },
      },
    });
    state.timeline = data.timeline;
    markSmoothPreviewStale();
    state.selectedItemId = data.item.item_id;
    state.selectedTool = "icons";
  });
}

function applyIconDraftToStage(panel, item) {
  if (!item) return;
  item.style = { ...(item.style || {}), color: inputValue("icon-color", "#ffffff") };
  item.transform = {
    ...(item.transform || {}),
    scale: Number(inputValue("icon-scale", item.transform?.scale || 1)),
    rotation: Number(inputValue("icon-rotation", item.transform?.rotation || 0)),
  };
  renderStudioIcons();
}

async function saveIcon(panel, item) {
  if (!item || item.type !== "icon") return;
  applyIconDraftToStage(panel, item);
  await patchTimelineItem(item.item_id, { transform: item.transform, style: item.style });
}

async function deleteTimelineItem(itemId, rerender = true) {
  if (!itemId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, { method: "DELETE" });
  state.timeline = data.timeline;
  markSmoothPreviewStale();
  if (state.selectedItemId === itemId) state.selectedItemId = "";
  if (rerender) renderStudio();
}

function replaceTimelineItem(item) {
  const index = state.timeline?.items.findIndex((entry) => entry.item_id === item.item_id) ?? -1;
  if (index >= 0) state.timeline.items[index] = item;
}

function sceneBounds(sceneId) {
  const media = timelineItems().find((item) => item.scene_id === sceneId && item.type === "media");
  return { start: media?.start_seconds || 0, end: media?.end_seconds || 0 };
}

function captionModeLabel(value) {
  return {
    one_word: "One word",
    full_line: "Full line",
    word_reveal: "Word reveal",
    active_word_highlight: "Active word",
    typewriter: "Typewriter",
    two_line_karaoke: "Two-line karaoke",
  }[value] || String(value).replaceAll("_", " ");
}

function iconPreview(value) {
  return `<span class="vd-icon-sample">${iconGlyph(value)}</span><small>${escapeHtml(iconLabel(value))}</small>`;
}

function iconGlyph(value) {
  return {
    arrow_right: "->",
    circle: "O",
    rectangle: "▭",
    underline: "_",
    check: "✓",
    x_mark: "×",
    starburst: "✦",
    pointer: "⌖",
    question: "?",
    exclamation: "!",
  }[value] || "•";
}

function iconLabel(value) {
  return {
    arrow_right: "Arrow",
    x_mark: "X mark",
  }[value] || String(value).replaceAll("_", " ");
}

function renderStudioMediaPanel(panel, row) {
  const media = row ? timelineItems().find((item) => item.type === "media" && item.scene_id === row.scene.scene_id) : null;
  if (!row) {
    panel.innerHTML = `<h3>Media</h3><p class="vd-muted">Select a scene.</p>`;
    return;
  }
  if (!media?.source_ref?.media_url) {
    panel.innerHTML = `
      <h3>Media</h3>
      <p class="vd-muted">Scene ${row.scene.order} has no downloaded material in the timeline.</p>
      <button data-view-target="materials" type="button">Return to materials</button>
    `;
    panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigate("materials"));
    return;
  }

  const targetDuration = mediaSceneDuration(media, row);
  const knownAssetDuration = Number(media.source_ref.asset_duration_seconds || 0);
  const maxStart = Math.max(0, knownAssetDuration - targetDuration);
  const trimStart = knownAssetDuration ? clamp(mediaTrimStart(media), 0, maxStart) : mediaTrimStart(media);
  const transform = media.transform || {};
  const effects = media.source_ref.effects || {};
  panel.innerHTML = `
    <h3>Media</h3>
    <div class="vd-media-status">
      <strong>Scene ${row.scene.order}</strong>
      <span>${escapeHtml(trimStatusLabel(media))}</span>
    </div>
    <video id="studio-trim-video" class="vd-trim-video" controls playsinline preload="metadata" src="${escapeHtml(media.source_ref.media_url)}"></video>
    <div class="vd-trim-meta">
      <span>Voice duration <b>${formatDuration(targetDuration)}</b></span>
      <span id="studio-trim-asset-duration">Raw ${knownAssetDuration ? formatDuration(knownAssetDuration) : "loading"}</span>
    </div>
    <label>Segment start
      <input id="studio-trim-start" type="range" min="0" max="${maxStart.toFixed(2)}" step="0.05" value="${trimStart.toFixed(2)}">
    </label>
    <label>Start seconds
      <input id="studio-trim-start-number" type="number" min="0" max="${maxStart.toFixed(2)}" step="0.05" value="${trimStart.toFixed(2)}">
    </label>
    <div id="studio-trim-window-label" class="vd-muted"></div>
    <div class="vd-button-row">
      <button id="preview-trim-segment" type="button">Play segment</button>
      <button id="save-scene-trim" class="vd-primary" type="button">Confirm segment</button>
      <button id="auto-scene-trim" type="button">Use auto-start</button>
    </div>
    <div class="vd-media-adjustments">
      <label><input id="trim-flip-horizontal" type="checkbox" ${transform.flip_horizontal ? "checked" : ""}> Flip horizontal</label>
      <label>Contrast <input id="trim-contrast" type="range" min="0.75" max="1.35" step="0.01" value="${Number(effects.contrast || 1)}"></label>
      <label>Brightness <input id="trim-brightness" type="range" min="0.75" max="1.25" step="0.01" value="${Number(effects.brightness || 1)}"></label>
      <label>Saturation <input id="trim-saturation" type="range" min="0.5" max="1.4" step="0.01" value="${Number(effects.saturation || 1)}"></label>
    </div>
    <button data-view-target="materials" type="button">Return to materials</button>
  `;
  bindStudioMediaPanel(panel, media, row);
}

function bindStudioMediaPanel(panel, media, row) {
  const trimVideo = panel.querySelector("#studio-trim-video");
  const range = panel.querySelector("#studio-trim-start");
  const number = panel.querySelector("#studio-trim-start-number");
  const sync = (value = null, seek = true) => {
    const next = updateTrimControls(panel, media, row, value);
    if (seek && trimVideo?.readyState > 0) {
      try {
        trimVideo.currentTime = next;
      } catch {
        return;
      }
    }
  };
  trimVideo?.addEventListener("loadedmetadata", () => sync(mediaTrimStart(media), true));
  range?.addEventListener("input", () => sync(Number(range.value || 0)));
  number?.addEventListener("change", () => sync(Number(number.value || 0)));
  panel.querySelector("#preview-trim-segment")?.addEventListener("click", () => playTrimSegment(panel, media, row));
  panel.querySelector("#save-scene-trim")?.addEventListener("click", () => saveSceneClip(panel, media, row, "manual"));
  panel.querySelector("#auto-scene-trim")?.addEventListener("click", () => {
    if (range) range.value = "0";
    if (number) number.value = "0";
    saveSceneClip(panel, media, row, "auto_start");
  });
  panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigate("materials"));
  panel.querySelectorAll("#trim-flip-horizontal, #trim-contrast, #trim-brightness, #trim-saturation").forEach((input) => {
    input.addEventListener("input", () => applyTrimDraftToStage(panel));
  });
  sync(mediaTrimStart(media), true);
  applyTrimDraftToStage(panel);
}

function updateTrimControls(panel, media, row, value = null) {
  const range = panel.querySelector("#studio-trim-start");
  const number = panel.querySelector("#studio-trim-start-number");
  const trimVideo = panel.querySelector("#studio-trim-video");
  const targetDuration = mediaSceneDuration(media, row);
  const assetDuration = assetDurationFromMedia(media, trimVideo);
  const maxStart = Math.max(0, assetDuration - targetDuration);
  const start = clamp(Number(value ?? range?.value ?? mediaTrimStart(media)) || 0, 0, maxStart);
  const end = assetDuration ? Math.min(assetDuration, start + targetDuration) : start + targetDuration;
  if (range) {
    range.max = maxStart.toFixed(2);
    range.value = start.toFixed(2);
  }
  if (number) {
    number.max = maxStart.toFixed(2);
    number.value = start.toFixed(2);
  }
  const assetLabel = panel.querySelector("#studio-trim-asset-duration");
  if (assetLabel) assetLabel.innerHTML = `Raw <b>${assetDuration ? formatDuration(assetDuration) : "loading"}</b>`;
  const windowLabel = panel.querySelector("#studio-trim-window-label");
  if (windowLabel) {
    const short = assetDuration && assetDuration < targetDuration ? " / short clip will loop" : "";
    windowLabel.textContent = `Selected ${formatDuration(start)} - ${formatDuration(end)}${short}`;
  }
  return start;
}

function playTrimSegment(panel, media, row) {
  const video = panel.querySelector("#studio-trim-video");
  if (!video) return;
  const start = updateTrimControls(panel, media, row);
  const stop = Math.min(assetDurationFromMedia(media, video) || start + mediaSceneDuration(media, row), start + mediaSceneDuration(media, row));
  const handler = () => {
    if (Number(video.currentTime || 0) >= stop - 0.04) {
      video.pause();
      video.removeEventListener("timeupdate", handler);
    }
  };
  if (video._vdTrimHandler) video.removeEventListener("timeupdate", video._vdTrimHandler);
  video._vdTrimHandler = handler;
  video.addEventListener("timeupdate", handler);
  try {
    video.currentTime = start;
  } catch {
    return;
  }
  const promise = video.play();
  if (promise?.catch) promise.catch(() => {});
}

async function saveSceneClip(panel, media, row, trimSource) {
  await run("Saving scene segment", async () => {
    const trimVideo = panel.querySelector("#studio-trim-video");
    const start = trimSource === "auto_start" ? 0 : updateTrimControls(panel, media, row);
    const data = await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/clip`, {
      method: "PATCH",
      body: {
        material_asset_id: media.source_ref.asset_id,
        trim_source: trimSource,
        trim_start_seconds: start,
        asset_duration_seconds: assetDurationFromMedia(media, trimVideo) || null,
        transform: trimTransformFromPanel(panel),
        effects: trimEffectsFromPanel(panel),
      },
    });
    replaceScene(data.scene);
    if (data.timeline) {
      state.timeline = data.timeline;
      markSmoothPreviewStale();
    }
  });
}

function trimTransformFromPanel(panel) {
  return {
    flip_horizontal: Boolean(panel.querySelector("#trim-flip-horizontal")?.checked),
  };
}

function trimEffectsFromPanel(panel) {
  return {
    contrast: Number(panel.querySelector("#trim-contrast")?.value || 1),
    brightness: Number(panel.querySelector("#trim-brightness")?.value || 1),
    saturation: Number(panel.querySelector("#trim-saturation")?.value || 1),
  };
}

function applyTrimDraftToStage(panel) {
  const media = currentMediaItem();
  if (!media) return;
  media.transform = { ...(media.transform || {}), ...trimTransformFromPanel(panel) };
  media.source_ref = { ...(media.source_ref || {}), effects: trimEffectsFromPanel(panel) };
  applyStudioMediaEffects(document.getElementById("studio-video"), media);
}

function setPlaybackElementSource(element, url) {
  if (!element) return false;
  const nextUrl = String(url || "");
  const currentUrl = element.getAttribute("src") || "";
  if (!nextUrl) {
    if (currentUrl) {
      element.pause();
      element.removeAttribute("src");
      element.load();
      return true;
    }
    return false;
  }
  if (currentUrl === nextUrl) return false;
  element.pause();
  element.src = nextUrl;
  element.load();
  return true;
}

function renderStudioStage() {
  const row = selectedRow();
  const media = timelineItems().find((item) => item.type === "media" && item.scene_id === row?.scene.scene_id);
  const audioItem = timelineItems().find((item) => item.type === "audio" && item.scene_id === row?.scene.scene_id);
  const musicItem = backgroundMusicItem();
  const text = timelineItems().find((item) => item.type === "text" && item.scene_id === row?.scene.scene_id);
  const caption = timelineItems().find((item) => item.type === "caption" && item.scene_id === row?.scene.scene_id);
  const overlay = timelineItems().find((item) => item.type === "overlay" && item.scene_id === row?.scene.scene_id);
  const video = document.getElementById("studio-video");
  const nextVideo = document.getElementById("studio-next-video");
  const audio = document.getElementById("studio-audio");
  const music = document.getElementById("studio-music");
  const captionEl = document.getElementById("studio-caption");
  const textEl = document.getElementById("studio-text");
  const stage = document.getElementById("studio-stage");
  const sceneLabel = document.getElementById("studio-scene-label");
  const mediaState = document.getElementById("studio-media-state");
  const useSmoothPreview = smoothPreviewActive();

  video.muted = !useSmoothPreview;
  if (nextVideo) nextVideo.muted = true;
  if (audio) audio.muted = false;
  const voiceoverTrack = combinedVoiceoverTrack();
  if (useSmoothPreview) {
    const previewChanged = setPlaybackElementSource(video, state.smoothPreview.preview_url || "");
    if (nextVideo) {
      nextVideo.pause();
      nextVideo.style.opacity = "0";
      nextVideo.removeAttribute("src");
      nextVideo.load();
    }
    setPlaybackElementSource(audio, "");
    setPlaybackElementSource(music, "");
    video.dataset.baseTransform = "";
    video.dataset.transitionTransform = "";
    video.style.transform = "";
    video.style.filter = "";
    video.style.opacity = "";
    if (previewChanged && !state.timelinePlaying) {
      const seekSmoothPreview = () => {
        try {
          video.currentTime = state.timelinePlayheadSeconds || 0;
        } catch {
          return;
        }
        updateStudioClock(state.timelinePlayheadSeconds || 0);
      };
      if (video.readyState > 0) seekSmoothPreview();
      else video.addEventListener("loadedmetadata", seekSmoothPreview, { once: true });
    }
  } else {
    const mediaChanged = setPlaybackElementSource(video, media?.source_ref?.media_url || "");
    const audioChanged = setPlaybackElementSource(audio, voiceoverTrack?.audio_url || audioItem?.source_ref?.audio_url || "");
    const musicChanged = setPlaybackElementSource(music, musicItem?.style?.enabled === false ? "" : (musicItem?.source_ref?.audio_url || ""));
    if (music) {
      music.loop = Boolean(musicItem?.style?.loop !== false);
      music.volume = musicPreviewVolume(musicItem);
    }
    applyStudioMediaEffects(video, media);
    if (mediaChanged && media && !state.timelinePlaying) {
      const setInitialCutTime = () => {
        try {
          video.currentTime = mediaTrimStart(media);
        } catch {
          return;
        }
        updateStudioClock(media.start_seconds);
      };
      if (video.readyState > 0) setInitialCutTime();
      else video.addEventListener("loadedmetadata", setInitialCutTime, { once: true });
    }
    if (audioChanged && audio && !state.timelinePlaying) {
      const resetAudio = () => {
        try {
          audio.currentTime = voiceoverTrack ? Number(media?.start_seconds || 0) : 0;
        } catch {
          return;
        }
      };
      if (audio.readyState > 0) resetAudio();
      else audio.addEventListener("loadedmetadata", resetAudio, { once: true });
    }
    if (musicChanged && music && musicItem && !state.timelinePlaying) {
      const resetMusic = () => {
        try {
          music.currentTime = musicLocalTime(state.timelinePlayheadSeconds || media?.start_seconds || 0, musicItem);
        } catch {
          return;
        }
      };
      if (music.readyState > 0) resetMusic();
      else music.addEventListener("loadedmetadata", resetMusic, { once: true });
    }
  }

  sceneLabel.textContent = row ? `Scene ${row.scene.order}` : "No scene selected";
  mediaState.textContent = useSmoothPreview ? smoothPreviewStatusLabel(state.smoothPreview) : studioMediaStateLabel(media, audioItem, voiceoverTrack, musicItem);
  stage.dataset.overlay = overlayIdForItem(overlay);
  stage.style.setProperty("--scene-overlay-opacity", String(Number(overlay?.style?.opacity ?? 0.35)));
  stage.dataset.captionStyle = caption?.style?.caption_style_id || state.preset.captions.style_id || "bold_outline";
  captionEl.dataset.itemId = caption?.item_id || "";
  applyCaptionTransformToElement(captionEl, caption);
  textEl.textContent = textForItem(text) || row?.scene.on_screen_text || "";
  textEl.dataset.itemId = text?.item_id || "";
  renderStudioText(text);
  renderStudioIcons();
  if (!state.timelinePlaying && media) updateStudioClock(useSmoothPreview ? state.timelinePlayheadSeconds : media.start_seconds);
  else updateStudioClock();
  updateStudioPlaybackButton();
}

function renderStudioText(item) {
  const textEl = document.getElementById("studio-text");
  if (!textEl) return;
  if (!item) {
    textEl.textContent = "";
    textEl.dataset.itemId = "";
    return;
  }
  const style = textStyle(item);
  const transform = item.transform || { x: 50, y: 18, scale: 1, rotation: 0 };
  const text = visibleTextForItem(item);
  textEl.textContent = text;
  textEl.dataset.itemId = item.item_id;
  textEl.style.left = `${Number(transform.x ?? 50)}%`;
  textEl.style.top = `${Number(transform.y ?? 18)}%`;
  textEl.style.transform = `translate(-50%, -50%) scale(${Number(transform.scale || 1)}) rotate(${Number(transform.rotation || 0)}deg)`;
  textEl.style.fontFamily = style.font_family || "Montserrat";
  textEl.style.fontSize = `${Number(style.font_size || 42)}px`;
  textEl.style.fontWeight = String(style.font_weight || 800);
  textEl.style.fontStyle = style.italic ? "italic" : "normal";
  textEl.style.color = style.text_color || "#ffffff";
  textEl.style.textShadow = style.shadow === false ? "none" : "0 2px 12px rgba(0,0,0,0.78)";
}

function visibleTextForItem(item) {
  const text = textForItem(item);
  const row = selectedRow();
  if (!text) return "";
  const isDefaultSceneText = row && [row.scene.on_screen_text, row.scene.voiceover_text, row.scene.caption_text]
    .filter(Boolean)
    .some((value) => String(value).trim() === String(text).trim());
  if (isDefaultSceneText && !item?.source_ref?.user_text) return "";
  return text;
}

function updateCaptionPreview(globalTime = state.timelinePlayheadSeconds) {
  const row = selectedRow();
  const item = itemForScene("caption", row);
  const captionEl = document.getElementById("studio-caption");
  if (!captionEl) return;
  const chunks = item?.source_ref?.caption_chunks || row?.scene.caption_chunks || [];
  const style = captionStyle(item);
  applyCaptionStyleToElement(captionEl, style);
  applyCaptionTransformToElement(captionEl, item);
  captionEl.innerHTML = captionHtmlForTime(chunks, row, item, globalTime, style);
}

function applyCaptionStyleToElement(element, style) {
  element.style.fontFamily = style.font_family || "Montserrat";
  element.style.fontSize = `${Number(style.font_size || 46)}px`;
  element.style.fontWeight = String(style.font_weight || 800);
  element.style.fontStyle = style.italic ? "italic" : "normal";
  element.style.color = style.text_color || "#ffffff";
  element.style.textShadow = style.shadow === false ? "none" : `0 2px 10px ${style.stroke_color || "#111111"}`;
  element.style.setProperty("--caption-active-glow", style.glow === false ? "none" : activeWordGlow(style));
}

function applyCaptionTransformToElement(element, item) {
  if (!element) return;
  const transform = item?.transform || { x: 50, y: 78, scale: 1, rotation: 0 };
  element.style.left = `${Number(transform.x ?? 50)}%`;
  element.style.top = `${Number(transform.y ?? 78)}%`;
  element.style.bottom = "auto";
  element.style.transform = `translate(-50%, -50%) scale(${Number(transform.scale || 1)}) rotate(${Number(transform.rotation || 0)}deg)`;
}

function activeWordGlow(style) {
  const color = style.glow_color || style.active_word_color || "#3ce6ac";
  const blur = Math.max(0, Number(style.glow_blur ?? 14));
  const intensity = clamp(Number(style.glow_intensity ?? 0.75), 0, 1);
  if (!blur || !intensity) return "none";
  return `0 0 ${blur}px ${rgbaFromHex(color, intensity)}, 0 0 ${Math.round(blur * 0.45)}px ${color}`;
}

function captionHtmlForTime(chunks, row, item, globalTime, style) {
  const text = chunks.map((chunk) => chunk.text).join(" ") || row?.scene.caption_text || row?.scene.voiceover_text || "";
  if (!text) return "";
  const media = timelineItems().find((entry) => entry.scene_id === row?.scene.scene_id && entry.type === "media");
  const local = Math.max(0, Number(globalTime || 0) - Number(media?.start_seconds || 0));
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return escapeHtml(text);
  const duration = Math.max(0.25, row?.scene.duration_seconds || item?.end_seconds - item?.start_seconds || words.length * 0.35);
  const activeIndex = clamp(Math.floor((local / duration) * words.length), 0, words.length - 1);
  const mode = style.caption_mode || "active_word_highlight";
  if (mode === "one_word") {
    return `<span class="is-active" style="color:${escapeHtml(style.active_word_color || "#3ce6ac")};text-shadow:var(--caption-active-glow, none);">${escapeHtml(words[activeIndex] || "")}</span>`;
  }
  if (mode === "full_line") return escapeHtml(text);
  if (mode === "word_reveal" || mode === "typewriter") return escapeHtml(words.slice(0, activeIndex + 1).join(" "));
  if (mode === "two_line_karaoke") {
    const start = Math.max(0, activeIndex - 3);
    const shown = words.slice(start, Math.min(words.length, activeIndex + 4));
    return shown.map((word, index) => {
      const realIndex = start + index;
      const active = realIndex === activeIndex;
      return `<span ${active ? `class="is-active" style="color:${escapeHtml(style.active_word_color || "#3ce6ac")}"` : ""}>${escapeHtml(word)}</span>`;
    }).join(" ");
  }
  return words.map((word, index) => {
    const active = index === activeIndex;
    return `<span ${active ? `class="is-active" style="color:${escapeHtml(style.active_word_color || "#3ce6ac")};text-shadow:var(--caption-active-glow, none);"` : ""}>${escapeHtml(word)}</span>`;
  }).join(" ");
}

function renderStudioIcons() {
  const layer = document.getElementById("studio-icon-layer");
  if (!layer) return;
  const row = selectedRow();
  const icons = itemsForScene("icon", row);
  layer.innerHTML = icons.map((item) => {
    const transform = item.transform || {};
    const style = item.style || {};
    return `
      <button class="vd-canvas-icon" data-icon-item-id="${item.item_id}" data-active="${item.item_id === state.selectedItemId}" type="button"
        style="left:${Number(transform.x ?? 50)}%;top:${Number(transform.y ?? 50)}%;transform:translate(-50%, -50%) scale(${Number(transform.scale || 1)}) rotate(${Number(transform.rotation || 0)}deg);color:${escapeHtml(style.color || "#ffffff")}">
        ${escapeHtml(iconGlyph(item.source_ref?.icon_id || "arrow_right"))}
      </button>
    `;
  }).join("");
  layer.querySelectorAll("[data-icon-item-id]").forEach((button) => {
    button.addEventListener("pointerdown", startCanvasIconDrag);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedItemId = button.dataset.iconItemId;
      state.selectedTool = "icons";
      renderStudio();
    });
  });
}

function studioMediaStateLabel(media, audioItem, voiceoverTrack = combinedVoiceoverTrack(), musicItem = backgroundMusicItem()) {
  if (!media?.source_ref?.media_url) return "No media";
  const cutLabel = `Cut ${formatDuration(mediaTrimStart(media))}-${formatDuration(mediaTrimEnd(media))}`;
  const voice = voiceoverTrack?.audio_url || audioItem?.source_ref?.audio_url ? " + voice" : " / no voice";
  const music = musicItem?.source_ref?.audio_url && musicItem.style?.enabled !== false ? " + music" : "";
  if (voiceoverTrack?.audio_url) return `${trimStatusLabel(media)} / ${cutLabel} + project voice${music}`;
  return `${trimStatusLabel(media)} / ${cutLabel}${voice}${music}`;
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
      const tool = studioToolForItem(item);
      if (tool) state.selectedTool = tool;
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
      <strong>${escapeHtml(timelineClipLabel(item))}</strong>
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
  return ["media", "text", "caption", "overlay", "icon", "transition", "music", "sfx"].includes(item?.type);
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
  if (event.target.closest("#timeline-playhead")) return;
  const fromRuler = event.currentTarget?.id === "timeline-ruler";
  if (!fromRuler && !event.target.closest(".vd-track-lane")) return;
  const time = timeFromTimelinePointer(event);
  if (time !== null) seekTimeline(time, { autoplay: state.timelinePlaying });
}

function seekTimeline(globalTime, options = {}) {
  if (!state.timeline) return;
  if (!options.autoplay) state.playedSfxIds.clear();
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
    if (smoothPreviewActive()) {
      syncSmoothPreviewToTimeline(time, options);
      return;
    }
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

function syncSmoothPreviewToTimeline(globalTime, options = {}) {
  const video = document.getElementById("studio-video");
  if (!video || !smoothPreviewActive()) return;
  const targetTime = clamp(globalTime, 0, Math.max(0, Number(state.timeline?.duration_seconds || globalTime || 0)));
  const setTime = () => {
    const drift = Math.abs(Number(video.currentTime || 0) - targetTime);
    if (!options.tolerateDrift || drift > 0.2 || video.paused) {
      try {
        video.currentTime = targetTime;
      } catch {
        return;
      }
    }
    updateStudioClock(targetTime);
    if (options.autoplay && video.paused) playStudioVideo();
  };
  if (video.readyState > 0) setTime();
  else video.addEventListener("loadedmetadata", setTime, { once: true });
}

function syncStudioVideoToTimeline(globalTime, options = {}) {
  const video = document.getElementById("studio-video");
  const media = currentMediaItem();
  if (!video || !media) return;
  const localTime = mediaTrimStart(media) + clamp(globalTime - media.start_seconds, 0, Math.max(0, media.end_seconds - media.start_seconds));
  const targetVideoTime = clamp(localTime, mediaTrimStart(media), mediaTrimEnd(media));
  const setTime = () => {
    const drift = Math.abs(Number(video.currentTime || 0) - targetVideoTime);
    const driftLimit = Number(options.videoDriftThreshold ?? 0.18);
    const shouldSetTime = !options.tolerateDrift || drift > driftLimit || video.paused;
    if (shouldSetTime) {
      try {
        video.currentTime = targetVideoTime;
      } catch {
        return;
      }
    }
    updateStudioClock(globalTime);
    if (!options.skipAudioSync) {
      syncStudioAudioToTimeline(globalTime, options);
      syncStudioMusicToTimeline(globalTime, options);
    }
    if (options.autoplay && video.paused) playStudioVideo();
  };
  if (video.readyState > 0) setTime();
  else video.addEventListener("loadedmetadata", setTime, { once: true });
}

function combinedVoiceoverTrack() {
  const track = state.project?.voiceover_track;
  return track?.audio_url ? track : null;
}

function currentAudioItem() {
  return timelineItems().find((item) => item.type === "audio" && item.scene_id === selectedRow()?.scene.scene_id) || null;
}

function musicPreviewVolume(item = backgroundMusicItem()) {
  if (!item || item.style?.enabled === false) return 0;
  const hasVoice = Boolean(combinedVoiceoverTrack()?.audio_url || currentAudioItem()?.source_ref?.audio_url);
  if (hasVoice && item.style?.ducking !== false) {
    return clamp(Number(item.style?.ducking_volume ?? 0.08), 0, 1);
  }
  return clamp(Number(item.style?.volume ?? 0.16), 0, 1);
}

function musicLocalTime(globalTime, item = backgroundMusicItem()) {
  if (!item) return 0;
  const duration = Math.max(0.05, Number(item.source_ref?.duration_seconds || 0.05));
  const trimStart = clamp(Number(item.source_ref?.trim_start_seconds || 0), 0, Math.max(0, duration - 0.05));
  const trimEnd = clamp(Number(item.source_ref?.trim_end_seconds || duration), trimStart + 0.05, duration);
  const trimDuration = Math.max(0.05, trimEnd - trimStart);
  const local = Math.max(0, Number(globalTime || 0) - Number(item.start_seconds || 0));
  if (item.style?.loop !== false) return trimStart + (local % trimDuration);
  return trimStart + clamp(local, 0, trimDuration);
}

function syncStudioAudioToTimeline(globalTime, options = {}) {
  const audio = document.getElementById("studio-audio");
  const track = combinedVoiceoverTrack();
  if (track) {
    if (!audio || !audio.src) return;
    if (globalTime < 0 || globalTime > Number(track.duration_seconds || state.timeline?.duration_seconds || 0) + 0.05) {
      audio.pause();
      return;
    }
    const targetTime = clamp(globalTime, 0, Math.max(0, Number(track.duration_seconds || globalTime || 0)));
    syncAudioElementToTime(audio, targetTime, options);
    return;
  }
  const item = currentAudioItem();
  if (!audio || !item?.source_ref?.audio_url || !audio.src) return;
  if (globalTime < item.start_seconds || globalTime > item.end_seconds) {
    audio.pause();
    return;
  }
  const targetTime = clamp(globalTime - item.start_seconds, 0, Math.max(0, item.end_seconds - item.start_seconds));
  syncAudioElementToTime(audio, targetTime, options);
}

function syncStudioMusicToTimeline(globalTime, options = {}) {
  const music = document.getElementById("studio-music");
  const item = backgroundMusicItem();
  if (!music || !item?.source_ref?.audio_url || !music.src || item.style?.enabled === false) return;
  if (globalTime < item.start_seconds || globalTime > item.end_seconds) {
    music.pause();
    return;
  }
  music.volume = musicPreviewVolume(item);
  syncAudioElementToTime(music, musicLocalTime(globalTime, item), options);
}

function syncAudioElementToTime(audio, targetTime, options = {}) {
  const drift = Math.abs(Number(audio.currentTime || 0) - targetTime);
  const shouldSetTime = !options.tolerateDrift || drift > 0.28;
  const setAudioTime = () => {
    if (shouldSetTime) {
      try {
        audio.currentTime = targetTime;
      } catch {
        return;
      }
    }
    if (options.autoplay) playStudioAudio();
  };
  if (audio.readyState > 0) setAudioTime();
  else audio.addEventListener("loadedmetadata", setAudioTime, { once: true });
}

function playStudioAudio() {
  const audio = document.getElementById("studio-audio");
  const music = document.getElementById("studio-music");
  if (audio?.src) {
    const promise = audio.play();
    if (promise?.catch) promise.catch(() => {});
  }
  if (music?.src) {
    const promise = music.play();
    if (promise?.catch) promise.catch(() => {});
  }
}

function pauseStudioMedia() {
  document.getElementById("studio-video")?.pause();
  document.getElementById("studio-next-video")?.pause();
  document.getElementById("studio-audio")?.pause();
  document.getElementById("studio-music")?.pause();
  stopTimelineFrameTicker();
}

function playStudioVideo() {
  const video = document.getElementById("studio-video");
  if (!video?.src) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    updateStudioPlaybackButton();
    return;
  }
  const promise = video.play();
  startTimelineFrameTicker();
  if (promise?.catch) {
    promise.catch(() => {
      state.timelinePlaying = false;
      pauseStudioMedia();
      updateStudioPlaybackButton();
    });
  }
  if (!smoothPreviewActive()) playStudioAudio();
}

function currentMediaItem() {
  return timelineItems().find((item) => item.type === "media" && item.scene_id === selectedRow()?.scene.scene_id) || null;
}

function mediaSceneDuration(media, row = selectedRow()) {
  return Number(media?.source_ref?.timeline_duration_seconds || row?.scene?.duration_seconds || ((media?.end_seconds || 0) - (media?.start_seconds || 0)) || 0);
}

function assetDurationFromMedia(media, video = null) {
  const loadedDuration = Number(video?.duration || 0);
  if (Number.isFinite(loadedDuration) && loadedDuration > 0) return loadedDuration;
  return Number(media?.source_ref?.asset_duration_seconds || 0);
}

function globalTimeFromVideo(media = currentMediaItem(), video = document.getElementById("studio-video")) {
  if (smoothPreviewActive()) {
    return clamp(Number(video?.currentTime || 0), 0, Math.max(1, state.timeline?.duration_seconds || 1));
  }
  if (!media) return state.timelinePlayheadSeconds || 0;
  const localElapsed = Math.max(0, Number(video?.currentTime || 0) - mediaTrimStart(media));
  return (media.start_seconds || 0) + localElapsed;
}

function globalTimeFromAudio(track = combinedVoiceoverTrack(), audio = document.getElementById("studio-audio")) {
  if (!track || !audio?.src) return state.timelinePlayheadSeconds || 0;
  const duration = Math.max(0, Number(track.duration_seconds || state.timeline?.duration_seconds || 0));
  return clamp(Number(audio.currentTime || 0), 0, duration || Number(audio.currentTime || 0));
}

function mediaTrimStart(item) {
  return Number(item?.source_ref?.trim_start_seconds || 0);
}

function mediaTrimEnd(item) {
  const fallback = mediaTrimStart(item) + Math.max(0, (item?.end_seconds || 0) - (item?.start_seconds || 0));
  return Number(item?.source_ref?.trim_end_seconds || fallback);
}

function trimStatusLabel(item) {
  const status = item?.source_ref?.trim_status || "";
  if (status === "trim_manual") return "Manual trim";
  if (status === "trim_short_loop") return "Short clip loop";
  if (status === "trim_stale") return "Stale trim";
  return item?.source_ref?.trim_source === "manual" ? "Manual trim" : "Auto-start";
}

function timelineClipLabel(item) {
  if (item?.type === "media") return trimStatusLabel(item);
  if (item?.type === "icon") return iconLabel(item.source_ref?.icon_id || "icon");
  if (item?.type === "overlay") return overlayLabel(overlayIdForItem(item));
  if (item?.type === "music") return item.source_ref?.name || "Music";
  if (item?.type === "sfx") return item.source_ref?.label || sfxAsset(item.source_ref?.asset_id)?.name || "SFX";
  if (item?.type === "transition") return transitionLabel(transitionIdForItem(item));
  return itemLabel(item);
}

function applyStudioMediaEffects(video, media) {
  if (!video) return;
  if (!media) {
    video.style.transform = "";
    video.style.filter = "";
    video.style.opacity = "";
    video.dataset.baseTransform = "";
    video.dataset.transitionTransform = "";
    return;
  }
  const transform = media.transform || {};
  const effects = media.source_ref?.effects || {};
  const flip = transform.flip_horizontal ? "scaleX(-1)" : "scaleX(1)";
  const scale = Number(transform.scale || 1);
  video.dataset.baseTransform = `${flip} scale(${scale})`;
  setStudioVideoTransform(video);
  video.style.filter = [
    `brightness(${Number(effects.brightness || 1)})`,
    `contrast(${Number(effects.contrast || 1)})`,
    `saturate(${Number(effects.saturation || 1)})`,
  ].join(" ");
}

function setStudioVideoTransform(video = document.getElementById("studio-video")) {
  if (!video) return;
  video.style.transform = `${video.dataset.baseTransform || ""} ${video.dataset.transitionTransform || ""}`.trim();
}

function applyTransitionPreview(globalTime) {
  const stage = document.getElementById("studio-stage");
  const video = document.getElementById("studio-video");
  const nextVideo = document.getElementById("studio-next-video");
  if (!stage || !video || !nextVideo) return;
  if (smoothPreviewActive()) {
    stage.dataset.transitionPreview = "rendered";
    stage.style.setProperty("--transition-flash-opacity", "0");
    video.dataset.transitionTransform = "";
    video.style.opacity = "";
    nextVideo.dataset.transitionTransform = "";
    nextVideo.style.opacity = "0";
    setStudioVideoTransform(video);
    return;
  }
  const item = transitionItemAtTime(globalTime);
  if (!item) {
    stage.dataset.transitionPreview = "none";
    stage.style.setProperty("--transition-flash-opacity", "0");
    video.dataset.transitionTransform = "";
    video.style.opacity = "";
    nextVideo.dataset.transitionTransform = "";
    nextVideo.style.opacity = "0";
    const upcoming = upcomingTransitionItem(globalTime);
    const upcomingMedia = upcoming ? nextMediaForTransition(upcoming) : null;
    if (upcomingMedia) {
      syncTransitionNextVideo(nextVideo, upcomingMedia);
    } else if (nextVideo.getAttribute("src")) {
      nextVideo.pause();
      nextVideo.removeAttribute("src");
      nextVideo.load();
    }
    setStudioVideoTransform(video);
    setStudioVideoTransform(nextVideo);
    return;
  }
  const duration = Math.max(0.05, item.end_seconds - item.start_seconds);
  const rawProgress = clamp((globalTime - item.start_seconds) / duration, 0, 1);
  const progress = easeInOutCubic(rawProgress);
  const requestedId = normalizedTransitionId(transitionIdForItem(item));
  const id = SAFE_REALTIME_TRANSITIONS.has(requestedId) ? requestedId : "fade";
  const nextMedia = nextMediaForTransition(item);
  syncTransitionNextVideo(nextVideo, nextMedia, { preplay: state.timelinePlaying && rawProgress > 0.72 });
  const nextReady = Boolean(nextMedia?.source_ref?.media_url) && nextVideo.dataset.transitionReady === "true";
  let outOpacity = 1;
  let inOpacity = nextReady ? progress : 0;
  let outTransform = "";
  let inTransform = "";
  let flashOpacity = 0;
  if (!nextReady) {
    outOpacity = 1;
    inOpacity = 0;
  } else if (id === "none") {
    outOpacity = rawProgress < 0.96 ? 1 : 0;
    inOpacity = nextReady && rawProgress >= 0.96 ? 1 : 0;
  } else if (["fade", "dissolve"].includes(id)) {
    outOpacity = 1 - progress;
    inOpacity = nextReady ? progress : 0;
  } else if (id === "slide_left") {
    outTransform = `translateX(${-progress * 100}%)`;
    inTransform = `translateX(${(1 - progress) * 100}%)`;
    inOpacity = nextReady ? 1 : 0;
  } else if (id === "slide_right") {
    outTransform = `translateX(${progress * 100}%)`;
    inTransform = `translateX(${-(1 - progress) * 100}%)`;
    inOpacity = nextReady ? 1 : 0;
  } else if (id === "slide_up") {
    outTransform = `translateY(${-progress * 100}%)`;
    inTransform = `translateY(${(1 - progress) * 100}%)`;
    inOpacity = nextReady ? 1 : 0;
  } else if (id === "zoom_in") {
    outTransform = `scale(${1 + progress * 0.22})`;
    outOpacity = 1 - progress * 0.8;
    inTransform = `scale(${1.16 - progress * 0.16})`;
    inOpacity = nextReady ? progress : 0;
  } else if (id === "zoom_out") {
    outTransform = `scale(${1 - progress * 0.18})`;
    outOpacity = 1 - progress * 0.8;
    inTransform = `scale(${0.88 + progress * 0.12})`;
    inOpacity = nextReady ? progress : 0;
  } else {
    outOpacity = 1 - progress;
    inOpacity = nextReady ? progress : 0;
  }
  stage.dataset.transitionPreview = id || "none";
  stage.style.setProperty("--transition-flash-opacity", String(flashOpacity));
  video.dataset.transitionTransform = outTransform;
  nextVideo.dataset.transitionTransform = inTransform;
  video.style.opacity = String(outOpacity);
  nextVideo.style.opacity = nextMedia ? String(inOpacity) : "0";
  setStudioVideoTransform(video);
  setStudioVideoTransform(nextVideo);
}

function transitionItemAtTime(globalTime) {
  return timelineItems().find((item) => item.type === "transition" && globalTime >= item.start_seconds && globalTime <= item.end_seconds) || null;
}

function upcomingTransitionItem(globalTime) {
  return timelineItems()
    .filter((item) => item.type === "transition" && item.start_seconds > globalTime && item.start_seconds - globalTime <= TRANSITION_PRELOAD_MARGIN)
    .sort((a, b) => a.start_seconds - b.start_seconds)[0] || null;
}

function nextMediaForTransition(transitionItem) {
  const mediaItems = timelineItems().filter((item) => item.type === "media").sort((a, b) => a.start_seconds - b.start_seconds);
  const index = mediaItems.findIndex((item) => item.scene_id === transitionItem.scene_id);
  return index >= 0 ? mediaItems[index + 1] || null : null;
}

function normalizedTransitionId(id) {
  return {
    clean_cut: "fade",
    push_slide: "slide_left",
    speed_zoom: "zoom_in",
    fast_swipes: "whip_pan",
  }[id] || id || "fade";
}

function easeInOutCubic(value) {
  const p = clamp(Number(value || 0), 0, 1);
  return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
}

function syncTransitionNextVideo(nextVideo, nextMedia, options = {}) {
  if (!nextVideo) return;
  if (!nextMedia?.source_ref?.media_url) {
    nextVideo.dataset.transitionReady = "false";
    return;
  }
  const changed = setPlaybackElementSource(nextVideo, nextMedia.source_ref.media_url);
  if (changed) nextVideo.dataset.transitionReady = "false";
  else if (nextVideo.readyState >= 2) nextVideo.dataset.transitionReady = "true";
  applyStudioMediaEffects(nextVideo, nextMedia);
  const targetTime = mediaTrimStart(nextMedia);
  const setTime = () => {
    const drift = Math.abs(Number(nextVideo.currentTime || 0) - targetTime);
    const driftLimit = options.preplay ? 0.35 : 0.08;
    if (changed || drift > driftLimit || !state.timelinePlaying) {
      try {
        nextVideo.currentTime = targetTime;
      } catch {
        return;
      }
    }
    if (options.preplay && nextVideo.readyState >= 2) playBufferedVideo(nextVideo);
    else nextVideo.pause();
    nextVideo.dataset.transitionReady = nextVideo.readyState >= 2 ? "true" : "false";
  };
  if (nextVideo.readyState > 0) setTime();
  else nextVideo.addEventListener("loadedmetadata", setTime, { once: true });
  nextVideo.addEventListener("canplay", () => {
    nextVideo.dataset.transitionReady = "true";
    if (options.preplay) playBufferedVideo(nextVideo);
  }, { once: true });
}

function playBufferedVideo(video) {
  if (!video?.src || !video.paused) return;
  const promise = video.play();
  if (promise?.catch) promise.catch(() => {});
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

async function saveStudioText(panel = null, item = selectedItem()) {
  if (!item || item.type !== "text") return;
  if (panel) applyTextDraftToStage(panel, item);
  else item.source_ref = { ...(item.source_ref || {}), text: document.getElementById("studio-text-input")?.value.trim() || textForItem(item) };
  await patchTimelineItem(item.item_id, { source_ref: item.source_ref, style: item.style, transform: item.transform });
}

function startCanvasTextDrag(event) {
  const itemId = event.currentTarget.dataset.itemId;
  const item = timelineItems().find((entry) => entry.item_id === itemId) || selectedItem();
  if (!item || item.type !== "text") return;
  event.preventDefault();
  state.selectedItemId = item.item_id;
  state.selectedTool = "text";
  const rect = document.getElementById("studio-stage").getBoundingClientRect();
  dragState = {
    kind: "canvas-text",
    itemId: item.item_id,
    rect,
  };
}

function startCanvasCaptionDrag(event) {
  const itemId = event.currentTarget.dataset.itemId;
  const item = timelineItems().find((entry) => entry.item_id === itemId) || itemForScene("caption");
  if (!item || item.type !== "caption") return;
  event.preventDefault();
  event.stopPropagation();
  state.selectedItemId = item.item_id;
  state.selectedTool = "captions";
  const rect = document.getElementById("studio-stage").getBoundingClientRect();
  dragState = {
    kind: "canvas-caption",
    itemId: item.item_id,
    rect,
  };
}

function startCanvasIconDrag(event) {
  const item = timelineItems().find((entry) => entry.item_id === event.currentTarget.dataset.iconItemId);
  if (!item || item.type !== "icon") return;
  event.preventDefault();
  event.stopPropagation();
  state.selectedItemId = item.item_id;
  state.selectedTool = "icons";
  const rect = document.getElementById("studio-stage").getBoundingClientRect();
  dragState = {
    kind: "canvas-icon",
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
  const tool = studioToolForItem(item);
  if (tool) state.selectedTool = tool;
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

function startPlayheadDrag(event) {
  if (!state.timeline || event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const wasPlaying = state.timelinePlaying;
  state.timelinePlaying = false;
  pauseStudioMedia();
  dragState = {
    kind: "playhead",
    wasPlaying,
    moved: false,
  };
  scrubTimelineToPointer(event);
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
  if (dragState.kind === "canvas-caption") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const x = clamp(((event.clientX - dragState.rect.left) / dragState.rect.width) * 100, 0, 100);
    const y = clamp(((event.clientY - dragState.rect.top) / dragState.rect.height) * 100, 0, 100);
    item.transform = { ...(item.transform || {}), x: Math.round(x), y: Math.round(y) };
    updateCaptionPreview(state.timelinePlayheadSeconds);
  }
  if (dragState.kind === "canvas-icon") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const x = clamp(((event.clientX - dragState.rect.left) / dragState.rect.width) * 100, 0, 100);
    const y = clamp(((event.clientY - dragState.rect.top) / dragState.rect.height) * 100, 0, 100);
    item.transform = { ...(item.transform || {}), x: Math.round(x), y: Math.round(y) };
    renderStudioIcons();
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
  if (dragState.kind === "playhead") {
    dragState.moved = true;
    scrubTimelineToPointer(event);
  }
}

async function endPointerDrag() {
  if (!dragState) return;
  if (dragState.kind === "playhead") {
    const wasPlaying = dragState.wasPlaying;
    dragState = null;
    if (wasPlaying) playTimelineFrom(state.timelinePlayheadSeconds);
    else updateStudioPlaybackButton();
    return;
  }
  const item = state.timeline?.items.find((entry) => entry.item_id === dragState.itemId);
  const shouldPatch = dragState.kind !== "timeline" || dragState.moved;
  const clipEl = dragState.clipEl;
  const patch = item ? { start_seconds: item.start_seconds, end_seconds: item.end_seconds, transform: item.transform } : null;
  dragState = null;
  if (clipEl) clipEl.dataset.dragging = "false";
  if (item && patch && shouldPatch) await patchTimelineItem(item.item_id, patch);
}

function scrubTimelineToPointer(event) {
  const time = timeFromTimelinePointer(event);
  if (time === null) return;
  seekTimeline(time, { autoplay: false, tolerateDrift: false });
}

function timeFromTimelinePointer(event) {
  if (!state.timeline) return null;
  const board = document.querySelector(".vd-timeline-board");
  if (!board) return null;
  const metrics = timelineMetrics();
  const rect = board.getBoundingClientRect();
  const x = event.clientX - rect.left + board.scrollLeft - metrics.labelWidth;
  return clamp(x / metrics.pxPerSecond, 0, metrics.duration);
}

async function patchTimelineItem(itemId, patch, options = {}) {
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, {
    method: "PATCH",
    body: patch,
  });
  const index = state.timeline.items.findIndex((item) => item.item_id === itemId);
  if (index >= 0) state.timeline.items[index] = data.item;
  markSmoothPreviewStale();
  if (options.render !== false) renderStudio();
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
  setInputValue("voice-speed", state.preset.voiceover.voice_speed || 1);
  updateVoiceSpeedLabel();
  setInputChecked("preset-video-flip", Boolean(state.preset.video_defaults?.flip_horizontal));
  setInputValue("preset-video-brightness", state.preset.video_defaults?.brightness ?? 1);
  setInputValue("preset-video-contrast", state.preset.video_defaults?.contrast ?? 1.08);
  setInputValue("preset-video-saturation", state.preset.video_defaults?.saturation ?? 1.08);
  setInputValue("preset-candidate-count", state.preset.scene_media.candidate_count || 4);
  setInputValue("preset-pinterest-count", state.preset.scene_media.pinterest_candidate_count || 4);
  setInputValue("douyin-min-count", state.preset.scene_media.candidate_count || 4);
  setInputValue("pinterest-min-count", state.preset.scene_media.pinterest_candidate_count || 4);
  setInputValue("queries-per-scene", 1);
  setInputChecked("preset-translate", Boolean(state.preset.scene_media.translate_to_chinese));
  setInputChecked("translate-query", Boolean(state.preset.scene_media.translate_to_chinese));
}

function updateDurationLabel() {
  const value = document.getElementById("start-duration").value;
  document.getElementById("start-duration-label").textContent = `${value} seconds`;
}

function updateVoiceSpeedLabel() {
  const value = Number(inputValue("voice-speed", 1));
  const label = document.getElementById("voice-speed-label");
  if (label) label.textContent = `${value.toFixed(2)}x`;
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
  const preferredType = {
    media: "media",
    text: "text",
    captions: "caption",
    overlay: "overlay",
    transitions: "transition",
    icons: "icon",
    audio: "sfx",
  }[state.selectedTool] || "text";
  const item = timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === preferredType)
    || timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === "media")
    || timelineItems().find((entry) => entry.scene_id === sceneId);
  state.selectedItemId = item?.item_id || "";
}

function selectedRow() {
  return state.rows.find((row) => row.scene.scene_id === state.selectedSceneId) || null;
}

function replaceScene(scene) {
  if (!scene?.scene_id) return;
  const row = state.rows.find((entry) => entry.scene.scene_id === scene.scene_id);
  if (row) row.scene = scene;
  const projectIndex = state.project?.scenes?.findIndex((entry) => entry.scene_id === scene.scene_id) ?? -1;
  if (projectIndex >= 0) state.project.scenes[projectIndex] = scene;
}

function selectedItem() {
  return timelineItems().find((item) => item.item_id === state.selectedItemId) || null;
}

function timelineItems() {
  return state.timeline?.items || [];
}

function studioToolForItem(item) {
  return {
    media: "media",
    text: "text",
    caption: "captions",
    overlay: "overlay",
    transition: "transitions",
    icon: "icons",
    music: "audio",
    sfx: "audio",
  }[item?.type] || null;
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
    pauseStudioMedia();
    updateStudioPlaybackButton();
    return;
  }
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const startTime = state.timelinePlayheadSeconds >= duration ? 0 : state.timelinePlayheadSeconds;
  playTimelineFrom(startTime);
}

function playTimelineFrom(globalTime) {
  state.timelinePlaying = true;
  state.playedSfxIds.clear();
  seekTimeline(globalTime, { autoplay: true });
  startTimelineFrameTicker();
  updateStudioPlaybackButton();
}

function onStudioVideoTimeUpdate() {
  if (smoothPreviewActive()) {
    syncTimelineToSmoothPreview();
    return;
  }
  updateStudioClock();
  if (combinedVoiceoverTrack()) return;
  if (!state.timelinePlaying) return;
  const media = currentMediaItem();
  if (!media) return;
  const video = document.getElementById("studio-video");
  const globalTime = globalTimeFromVideo(media, video);
  syncStudioAudioToTimeline(globalTime, { autoplay: true, tolerateDrift: true });
  if (globalTime >= media.end_seconds - 0.05 || Number(video.currentTime || 0) >= mediaTrimEnd(media) - 0.05) {
    advanceTimelinePlayback(media.end_seconds + 0.001);
  }
}

function onStudioVideoEnded() {
  if (!state.timelinePlaying) return;
  if (smoothPreviewActive()) {
    state.timelinePlaying = false;
    seekTimeline(Math.max(0, state.timeline?.duration_seconds || 0));
    updateStudioPlaybackButton();
    return;
  }
  if (combinedVoiceoverTrack()) {
    syncTimelineToVoiceover(globalTimeFromAudio());
    return;
  }
  const media = currentMediaItem();
  if (!media) return;
  advanceTimelinePlayback(media.end_seconds + 0.001);
}

function onStudioAudioTimeUpdate() {
  if (!state.timelinePlaying || !combinedVoiceoverTrack()) return;
  syncTimelineToVoiceover(globalTimeFromAudio());
}

function advanceTimelinePlayback(globalTime) {
  if (!state.timeline) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  if (globalTime >= duration - 0.01) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  seekTimeline(globalTime, { autoplay: true });
}

function syncTimelineToSmoothPreview() {
  const video = document.getElementById("studio-video");
  if (!state.timeline || !smoothPreviewActive() || !video) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const time = clamp(Number(video.currentTime || 0), 0, duration);
  if (time >= duration - 0.03) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  const media = mediaItemAtTime(time);
  if (media && state.selectedSceneId !== media.scene_id) {
    state.selectedSceneId = media.scene_id;
    if (!selectedItem() || selectedItem()?.scene_id !== media.scene_id) {
      state.selectedItemId = media.item_id;
    }
    renderStudio();
  }
  updateStudioClock(time);
}

function syncTimelineToVoiceover(globalTime) {
  if (!state.timeline || !combinedVoiceoverTrack()) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const time = clamp(Number(globalTime || 0), 0, duration);
  if (time >= duration - 0.03) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  const media = mediaItemAtTime(time);
  if (!media) {
    updateStudioClock(time);
    return;
  }
  const sceneChanged = state.selectedSceneId !== media.scene_id;
  if (sceneChanged) {
    state.selectedSceneId = media.scene_id;
    if (!selectedItem() || selectedItem()?.scene_id !== media.scene_id) {
      state.selectedItemId = media.item_id;
    }
    promoteTransitionBufferToPrimary(media);
    renderStudio();
  }
  syncStudioVideoToTimeline(time, {
    autoplay: true,
    tolerateDrift: true,
    skipAudioSync: true,
    videoDriftThreshold: sceneChanged ? 0.35 : 0.18,
  });
  updateStudioClock(time);
}

function promoteTransitionBufferToPrimary(media) {
  const video = document.getElementById("studio-video");
  const nextVideo = document.getElementById("studio-next-video");
  if (!video || !nextVideo || !media?.source_ref?.media_url) return false;
  const nextSrc = nextVideo.getAttribute("src") || "";
  if (nextSrc !== media.source_ref.media_url || nextVideo.dataset.transitionReady !== "true") return false;

  video.pause();

  video.id = "studio-next-video";
  nextVideo.id = "studio-video";
  video.classList.add("vd-next-video");
  nextVideo.classList.remove("vd-next-video");

  video.style.opacity = "0";
  video.dataset.transitionTransform = "";
  setStudioVideoTransform(video);

  nextVideo.style.opacity = "";
  nextVideo.dataset.transitionTransform = "";
  applyStudioMediaEffects(nextVideo, media);
  setStudioVideoTransform(nextVideo);

  return true;
}

function startTimelineFrameTicker() {
  if (timelineFrameRequest) return;
  const tick = () => {
    timelineFrameRequest = null;
    if (!state.timelinePlaying) return;
    if (smoothPreviewActive()) syncTimelineToSmoothPreview();
    else if (combinedVoiceoverTrack()) syncTimelineToVoiceover(globalTimeFromAudio());
    else updateStudioClock();
    timelineFrameRequest = requestAnimationFrame(tick);
  };
  timelineFrameRequest = requestAnimationFrame(tick);
}

function stopTimelineFrameTicker() {
  if (!timelineFrameRequest) return;
  cancelAnimationFrame(timelineFrameRequest);
  timelineFrameRequest = null;
}

function updateStudioClock(forcedGlobalTime = null) {
  const media = currentMediaItem();
  const hasForcedTime = typeof forcedGlobalTime === "number" && Number.isFinite(forcedGlobalTime);
  const globalTime = hasForcedTime ? forcedGlobalTime : (smoothPreviewActive() ? globalTimeFromVideo(media) : (combinedVoiceoverTrack() ? globalTimeFromAudio() : globalTimeFromVideo(media)));
  state.timelinePlayheadSeconds = clamp(globalTime, 0, Math.max(1, state.timeline?.duration_seconds || 1));
  updateCaptionPreview(state.timelinePlayheadSeconds);
  applyTransitionPreview(state.timelinePlayheadSeconds);
  triggerRealtimeSfx(state.timelinePlayheadSeconds);
  const time = document.getElementById("studio-time");
  if (time) time.textContent = state.timeline ? `${formatDuration(state.timelinePlayheadSeconds)} / ${formatDuration(state.timeline.duration_seconds)}` : "0:00";
  updateTimelinePlayhead(state.timelinePlayheadSeconds);
}

function triggerRealtimeSfx(globalTime) {
  if (!state.timelinePlaying || smoothPreviewActive()) return;
  const windowStart = Number(globalTime || 0) - 0.04;
  const windowEnd = Number(globalTime || 0) + 0.12;
  const dueItems = timelineItems().filter((item) => {
    if (item.type !== "sfx" || item.style?.enabled === false || state.playedSfxIds.has(item.item_id)) return false;
    return item.start_seconds >= windowStart && item.start_seconds <= windowEnd;
  });
  for (const item of dueItems) {
    state.playedSfxIds.add(item.item_id);
    playTimelineSfx(item);
  }
}

function playTimelineSfx(item) {
  const asset = sfxAsset(item.source_ref?.asset_id);
  const url = asset?.audio_url || item.source_ref?.audio_url || "";
  if (!url) return;
  const audio = new Audio(url);
  audio.volume = clamp(Number(item.style?.volume ?? asset?.default_volume ?? 0.35), 0, 1);
  const promise = audio.play();
  if (promise?.catch) promise.catch(() => {});
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
  const audio = document.getElementById("studio-audio");
  const music = document.getElementById("studio-music");
  const button = document.getElementById("studio-play");
  if (!button || !video) return;
  button.textContent = state.timelinePlaying || !video.paused || (audio?.src && !audio.paused) || (music?.src && !music.paused) ? "Pause" : "Play";
}

function ensureProject() {
  if (!state.projectId) throw new Error("Create or load a project first.");
}

function setStatus(message, mode) {
  const status = document.getElementById("vd-status");
  status.textContent = message;
  status.dataset.mode = mode;
}

function sceneVisualSearchPlan(scene) {
  return scene?.visual_search_plan && typeof scene.visual_search_plan === "object"
    ? scene.visual_search_plan
    : {};
}

function materialSearchPlan() {
  const plan = state.project?.material_search_plan;
  return plan && typeof plan === "object"
    ? plan
    : { popular_first: true, groups: [] };
}

function cloneMaterialSearchPlan() {
  return JSON.parse(JSON.stringify(materialSearchPlan()));
}

function materialSearchGroups() {
  return Array.isArray(materialSearchPlan().groups) ? materialSearchPlan().groups : [];
}

function searchGroupForScene(scene) {
  if (!scene) return null;
  return materialSearchGroups().find((group) => (group.scene_ids || []).includes(scene.scene_id)) || null;
}

function selectedMaterialSearchGroup(row = selectedRow()) {
  const groups = materialSearchGroups();
  return groups.find((group) => group.group_id === state.selectedSearchGroupId)
    || searchGroupForScene(row?.scene)
    || groups[0]
    || null;
}

function materialKeywordsForScene(scene) {
  const group = searchGroupForScene(scene);
  if (group) {
    return {
      douyin: String(group.douyin_keyword || "").trim(),
      pinterest: String(group.pinterest_keyword || "").trim(),
    };
  }
  const plan = sceneVisualSearchPlan(scene);
  const legacy = scene?.matching_keywords || [];
  return {
    douyin: String(plan.douyin_primary_keyword || legacy[0] || "").trim(),
    pinterest: String(plan.pinterest_primary_keyword || legacy[0] || "").trim(),
  };
}
