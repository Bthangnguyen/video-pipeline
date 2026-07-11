import { api, run } from "./api.js";
import { state } from "./state.js";
import { ensureProject, selectFirstScene, selectedRow, setStatus } from "./ui.js";
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
  mergePreset,
  overlayLabel,
  projectStageLabel,
  sentenceCount,
  setByPath,
  setInputChecked,
  setInputValue,
  transitionLabel,
  videoDefaultsLabel,
  voiceLabel,
  wordCount,
} from "./utils.js";

let navigateCallback = () => {};
let renderCallback = () => {};
let loadReviewCallback = async () => {};
let loadTimelineCallback = async () => {};
let combinedVoiceoverTrackCallback = () => null;

export function configureProject({ navigate, renderAll, loadReview, loadTimeline, combinedVoiceoverTrack }) {
  navigateCallback = navigate;
  renderCallback = renderAll;
  loadReviewCallback = loadReview;
  loadTimelineCallback = loadTimeline;
  combinedVoiceoverTrackCallback = combinedVoiceoverTrack;
}


export async function restoreProject() {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("project_id") || localStorage.getItem("videodesignProjectId");
  if (projectId) await loadProject(projectId, params.get("view") || null);
}


export async function createProject() {
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
    navigateCallback("script");
  });
}


export async function loadProject(projectId, preferredView = null) {
  await run("Loading project", async () => {
    const data = await api(`/api/videodesign/projects/${projectId}`);
    state.project = data.project;
    state.projectId = data.project.project_id;
    state.preset = mergePreset(defaultPreset(), state.project.design_preset || {});
    state.smoothPreview = state.project.smooth_preview || defaultSmoothPreview();
    localStorage.setItem("videodesignProjectId", state.projectId);
    hydrateProjectFields();
    await loadReviewCallback();
    await loadTimelineCallback();
    renderProjectList();
    navigateCallback(preferredView || (state.timeline ? "studio" : "script"));
  });
}


export async function loadProjectList() {
  try {
    const data = await api("/api/videodesign/projects");
    state.projects = data.projects || [];
    renderProjectList();
  } catch (error) {
    const library = document.getElementById("project-library");
    if (library) library.innerHTML = `<div class="vd-empty">Could not load projects.</div>`;
  }
}


export function renderProjectList() {
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


export async function saveProjectPatch(patch) {
  const data = await api(`/api/videodesign/projects/${state.projectId}`, {
    method: "PATCH",
    body: patch,
  });
  state.project = data.project;
  hydrateProjectFields(false);
  return data.project;
}


export async function generateScript() {
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
    await loadReviewCallback();
    setStatus("Script generated.", "idle");
  });
}


export async function saveScript() {
  ensureProject();
  await run("Saving script", async () => {
    await saveProjectPatch({
      idea: document.getElementById("script-idea").value.trim(),
      script: document.getElementById("script-editor").value.trim(),
    });
    setStatus("Script saved.", "idle");
  });
}


export async function parseScenes() {
  ensureProject();
  await run("Preparing template", async () => {
    await saveScript();
    await saveSplitSettings();
    await savePreset();
    navigateCallback("template");
  });
}


export async function createScenePlan() {
  await saveScript();
  await saveSplitSettings();
  await api(`/api/videodesign/projects/${state.projectId}/plan`, { method: "POST" });
  await loadReviewCallback();
  selectFirstScene();
  navigateCallback("plan");
}


export async function saveSplitSettings() {
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


export async function savePreset() {
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


export function previewSelectedVoice() {
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


export async function generateTts() {
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
    await loadReviewCallback();
    setStatus("Project voiceover generated as one continuous track.", "idle");
  });
}


export async function buildCombinedVoiceover(options = {}) {
  ensureProject();
  const data = await api(`/api/videodesign/projects/${state.projectId}/audio/combined`, { method: "POST" });
  state.project = {
    ...(state.project || {}),
    voiceover_track: data.voiceover_track,
  };
  if (options.refresh !== false) {
    await loadReviewCallback();
    if (state.timeline) await loadTimelineCallback();
  }
  return data.voiceover_track;
}


export async function clearGeneratedTts() {
  ensureProject();
  if (!window.confirm("Clear all generated TTS audio for this project? The Studio timeline will need to be created again.")) return;
  await run("Clearing generated TTS", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/tts`, { method: "DELETE" });
    state.project = data.project;
    state.timeline = null;
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    state.selectedItemId = "";
    await loadReviewCallback();
    setStatus(`Cleared generated TTS audio (${data.deleted_files || 0} file(s)).`, "idle");
  });
}


export async function saveSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Saving scene", async () => {
    await saveSceneDraft(row);
    await loadReviewCallback();
  });
}


export async function saveSceneDraft(row) {
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
    method: "PATCH",
    body: sceneEditorPatch(),
  });
}


export function sceneEditorPatch() {
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


export async function splitSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Splitting scene", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/split`, { method: "POST" });
    await loadReviewCallback();
  });
}


export async function mergePreviousScene() {
  const row = selectedRow();
  const index = state.rows.findIndex((item) => item.scene.scene_id === row?.scene.scene_id);
  if (!row || index <= 0) return;
  await run("Merging scenes", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/merge`, {
      method: "POST",
      body: { scene_ids: [state.rows[index - 1].scene.scene_id, row.scene.scene_id] },
    });
    await loadReviewCallback();
  });
}


export function renderProjectChip() {
  const chip = document.getElementById("vd-project-chip");
  chip.textContent = state.projectId ? state.projectId : "No project";
}


export function renderSummaryRails() {
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
        else navigateCallback("plan");
      });
    });
  });
}


export function summaryRow(label, value) {
  return `<div class="vd-summary-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not set")}</strong></div>`;
}


export function renderTemplateSelections() {
  document.querySelectorAll("[data-preset-path]").forEach((button) => {
    const value = getByPath(state.preset, button.dataset.presetPath);
    button.classList.toggle("is-selected", value === button.dataset.presetValue);
  });
  document.querySelectorAll("[data-caption-style]").forEach((button) => {
    button.classList.toggle("is-selected", state.preset.captions.style_id === button.dataset.captionStyle);
  });
}


export function renderSceneRails() {
  const html = state.rows.length ? state.rows.map((row) => sceneRailButton(row)).join("") : `<div class="vd-empty">No scenes yet. Parse the script first.</div>`;
  document.getElementById("plan-scene-rail").innerHTML = html;
  document.getElementById("materials-scene-rail").innerHTML = html;
  document.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      const row = state.rows.find((item) => item.scene.scene_id === state.selectedSceneId);
      state.selectedSearchGroupId = row?.scene?.search_group_id || state.selectedSearchGroupId;
      renderCallback();
    });
  });
}


export function sceneRailButton(row) {
  const active = row.scene.scene_id === state.selectedSceneId ? "true" : "false";
  return `
    <button class="vd-scene-pill" data-scene-id="${row.scene.scene_id}" data-active="${active}" type="button">
      <span>Scene ${row.scene.order}</span>
      <strong>${escapeHtml(row.scene.on_screen_text || row.scene.voiceover_text || "Untitled")}</strong>
      <em>${escapeHtml(row.scene.approval_state)} / ${row.candidates.length} candidates</em>
    </button>
  `;
}


export function renderSceneEditor() {
  const row = selectedRow();
  document.getElementById("plan-scene-title").textContent = row ? `Scene ${row.scene.order}` : "Select a scene";
  setInputValue("scene-voiceover", row?.scene.voiceover_text || "");
  setInputValue("scene-onscreen", row?.scene.on_screen_text || "");
  setInputValue("scene-visual", row?.scene.visual_brief || "");
  setInputValue("scene-keywords", row?.scene.matching_keywords?.join(", ") || "");
}


export function renderTtsStatus() {
  const panel = document.getElementById("tts-status-panel");
  if (!panel) return;
  const rows = state.rows || [];
  const row = selectedRow();
  const synced = rows.filter((row) => row.scene.tts?.sync_state === "synced").length;
  const audioUrl = row?.scene.tts?.audio_url || "";
  const voiceoverTrack = combinedVoiceoverTrackCallback();
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
      renderCallback();
    });
  });
  panel.querySelector("#build-combined-voiceover")?.addEventListener("click", () => {
    run("Building combined voiceover", async () => {
      await buildCombinedVoiceover();
      setStatus("Combined voiceover is ready for Studio playback.", "idle");
    });
  });
  panel.querySelector("#clear-generated-tts")?.addEventListener("click", clearGeneratedTts);
  panel.querySelector("#tts-continue-materials")?.addEventListener("click", () => navigateCallback("materials"));
}


export function setPresetChoice(button) {
  const peers = button.parentElement.querySelectorAll(`[data-preset-path="${button.dataset.presetPath}"]`);
  peers.forEach((peer) => peer.classList.remove("is-selected"));
  button.classList.add("is-selected");
  setByPath(state.preset, button.dataset.presetPath, button.dataset.presetValue);
  renderSummaryRails();
}


export function setTemplateChoice(button) {
  document.querySelectorAll("[data-template-id]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.template.template_id = button.dataset.templateId;
  state.preset.template.template_category = "dynamic_template";
  renderSummaryRails();
}


export function setCaptionStyle(button) {
  document.querySelectorAll("[data-caption-style]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.captions.style_id = button.dataset.captionStyle;
  state.preset.captions.animation_id = button.dataset.captionStyle;
  renderSummaryRails();
}


export function hydrateProjectFields(updateInputs = true) {
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


export function updateDurationLabel() {
  const value = document.getElementById("start-duration").value;
  document.getElementById("start-duration-label").textContent = `${value} seconds`;
}


export function updateVoiceSpeedLabel() {
  const value = Number(inputValue("voice-speed", 1));
  const label = document.getElementById("voice-speed-label");
  if (label) label.textContent = `${value.toFixed(2)}x`;
}


export function updateScriptMetrics() {
  const text = document.getElementById("script-editor")?.value || "";
  const words = wordCount(text);
  const seconds = Math.max(2, Math.round(words / 2.6));
  const scenes = Math.max(0, sentenceCount(text));
  const metrics = document.getElementById("script-metrics");
  if (metrics) metrics.textContent = `${words} words / ${formatDuration(seconds)} / ${scenes} scenes`;
}
