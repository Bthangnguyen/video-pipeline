import { api, configureApi, run, startProgressPolling, stopProgressPolling } from "./api.js";
import {
  assignSelectedSceneToGroup,
  clearAllCandidates,
  clearSelectedSceneCandidates,
  configureMaterials,
  downloadApproved,
  generateAllSceneKeywords,
  generateSelectedSceneKeywords,
  keepSelectedCandidates,
  loadReview,
  renderCandidateBoard,
  runMaterialHealth,
  saveMaterialKeywords,
  searchAllScenes,
  searchSelectedScene,
} from "./materials.js";
import {
  buildCombinedVoiceover,
  clearGeneratedTts,
  configureProject,
  createProject,
  createScenePlan,
  generateScript,
  generateTts,
  hydrateProjectFields,
  loadProject,
  loadProjectList,
  mergePreviousScene,
  parseScenes,
  previewSelectedVoice,
  renderProjectChip,
  renderProjectList,
  renderSceneEditor,
  renderSceneRails,
  renderSummaryRails,
  renderTemplateSelections,
  renderTtsStatus,
  restoreProject,
  savePreset,
  saveSceneDraft,
  saveScript,
  saveSelectedScene,
  setCaptionStyle,
  setPresetChoice,
  setTemplateChoice,
  splitSelectedScene,
  updateDurationLabel,
  updateScriptMetrics,
  updateVoiceSpeedLabel,
} from "./project.js";
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
import {
  ensureProject,
  replaceScene,
  selectFirstItemForScene,
  selectFirstScene,
  selectedItem,
  selectedRow,
  setStatus,
  timelineItems,
} from "./ui.js";
import * as studio from "./studio/index.js";

configureApi({ renderAll, loadReview });
configureProject({ navigate, renderAll, loadReview, loadTimeline: studio.loadTimeline, combinedVoiceoverTrack: studio.combinedVoiceoverTrack });
configureMaterials({ renderAll });
studio.configureStudio({ navigate, renderAll });

export function init() {
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

  document.getElementById("create-timeline").addEventListener("click", studio.createTimeline);
  document.getElementById("clear-timeline").addEventListener("click", studio.clearTimeline);
  document.getElementById("build-smooth-preview").addEventListener("click", studio.buildSmoothPreview);
  document.getElementById("toggle-smooth-preview").addEventListener("click", studio.toggleSmoothPreviewMode);
  document.getElementById("render-export").addEventListener("click", studio.renderExportVideo);
  document.getElementById("download-export").addEventListener("click", studio.downloadExportVideo);
  document.getElementById("studio-play").addEventListener("click", studio.toggleStudioPlayback);
  studio.bindStudioVideoEvents(document.getElementById("studio-video"));
  studio.bindStudioVideoEvents(document.getElementById("studio-next-video"));
  document.getElementById("studio-audio").addEventListener("timeupdate", studio.onStudioAudioTimeUpdate);
  document.getElementById("studio-audio").addEventListener("play", studio.updateStudioPlaybackButton);
  document.getElementById("studio-audio").addEventListener("pause", studio.updateStudioPlaybackButton);
  document.getElementById("studio-music").addEventListener("play", studio.updateStudioPlaybackButton);
  document.getElementById("studio-music").addEventListener("pause", studio.updateStudioPlaybackButton);
  document.getElementById("timeline-fit").addEventListener("click", studio.fitTimeline);
  document.getElementById("timeline-zoom-out").addEventListener("click", () => studio.zoomTimeline(-1));
  document.getElementById("timeline-zoom-in").addEventListener("click", () => studio.zoomTimeline(1));
  document.getElementById("timeline-ruler").addEventListener("pointerdown", studio.seekTimelineFromPointer);
  document.getElementById("timeline-tracks").addEventListener("pointerdown", studio.seekTimelineFromPointer);
  document.getElementById("timeline-playhead").addEventListener("pointerdown", studio.startPlayheadDrag);
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTool = button.dataset.studioTool;
      studio.renderStudio();
    });
  });

  document.getElementById("studio-text").addEventListener("pointerdown", studio.startCanvasTextDrag);
  document.getElementById("studio-caption").addEventListener("pointerdown", studio.startCanvasCaptionDrag);
  document.addEventListener("pointermove", studio.onPointerMove);
  document.addEventListener("pointerup", studio.endPointerDrag);
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
  studio.renderStudio();
  updateScriptMetrics();
}
