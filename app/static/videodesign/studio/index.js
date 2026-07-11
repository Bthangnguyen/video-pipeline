import { api, run } from "../api.js";
import { summaryRow } from "../project.js";
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
} from "../state.js";
import {
  ensureProject,
  replaceScene,
  selectFirstItemForScene,
  selectedItem,
  selectedRow,
  setStatus,
  timelineItems,
} from "../ui.js";
import {
  captionLabel,
  clamp,
  defaultSmoothPreview,
  escapeHtml,
  formatDuration,
  inputChecked,
  inputValue,
  itemLabel,
  overlayLabel,
  rgbaFromHex,
  textForItem,
  titleCase,
  transitionLabel,
} from "../utils.js";
import * as playback from "./playback.js";
import * as stage from "./stage.js";
import * as timeline from "./timeline.js";
import * as audio from "./audio.js";
import * as panels from "./panels.js";

export * from "./audio.js";
export * from "./panels.js";
export * from "./playback.js";
export * from "./stage.js";
export * from "./timeline.js";

const {
  applyStudioMediaEffects,
  assetDurationFromMedia,
  combinedVoiceoverTrack,
  currentMediaItem,
  mediaItemAtTime,
  mediaSceneDuration,
  mediaTrimEnd,
  mediaTrimStart,
  musicLocalTime,
  musicPreviewVolume,
  onStudioVideoEnded,
  onStudioVideoTimeUpdate,
  pauseStudioMedia,
  placeTimelineClip,
  playTimelineFrom,
  setPlaybackElementSource,
  syncSmoothPreviewToTimeline,
  syncStudioVideoToTimeline,
  timelineClipLabel,
  trimStatusLabel,
  updateStudioClock,
  updateStudioPlaybackButton,
  updateTimelineClipActiveStates,
  updateTimelinePlayhead,
} = playback;
const {
  applyCaptionDraftToStage,
  applyCaptionStyleToElement,
  applyCaptionTransformToElement,
  applyIconDraftToStage,
  applyTextDraftToStage,
  applyTrimDraftToStage,
  captionHtmlForTime,
  captionModeLabel,
  iconGlyph,
  iconLabel,
  iconPreview,
  renderStudioIcons,
  renderStudioInspector,
  renderStudioStage,
  renderStudioText,
  studioMediaStateLabel,
  updateCaptionPreview,
  visibleTextForItem,
} = stage;
const {
  patchTimelineItem,
  renderTimeline,
  replaceTimelineItem,
  sceneBounds,
  seekTimeline,
  startCanvasIconDrag,
  timelineMetrics,
} = timeline;
const { backgroundMusicItem, renderAudioPanel, sfxAsset } = audio;
const {
  captionStyle,
  collectCaptionStyle,
  collectTextStyle,
  deleteTimelineItem,
  itemForScene,
  itemsForScene,
  overlayIdForItem,
  renderStudioToolPanel,
  studioToolForItem,
  textStyle,
  transitionIdForItem,
  trimEffectsFromPanel,
  trimTransformFromPanel,
} = panels;

let navigateCallback = () => {};
let renderCallback = () => {};

export function configureStudio({ navigate, renderAll }) {
  navigateCallback = navigate;
  renderCallback = renderAll;
}

playback.configurePlayback({
  backgroundMusicItem,
  iconLabel,
  overlayIdForItem,
  renderStudio,
  seekTimeline,
  sfxAsset,
  smoothPreviewActive,
  timelineMetrics,
  transitionIdForItem,
  updateCaptionPreview,
});
stage.configureStage({
  backgroundMusicItem,
  captionStyle,
  collectCaptionStyle,
  collectTextStyle,
  itemForScene,
  itemsForScene,
  overlayIdForItem,
  renderStudio,
  smoothPreviewActive,
  smoothPreviewStatusLabel,
  startCanvasIconDrag,
  summaryRow,
  textStyle,
  trimEffectsFromPanel,
  trimTransformFromPanel,
});
timeline.configureTimeline({
  itemForScene,
  markSmoothPreviewStale,
  renderStudio,
  renderStudioToolPanel,
  smoothPreviewActive,
  studioToolForItem,
});
audio.configureAudio({
  deleteTimelineItem,
  loadSfxCatalog,
  loadTimeline,
  markSmoothPreviewStale,
});
panels.configurePanels({ markSmoothPreviewStale, renderStudio });


export function bindStudioVideoEvents(video) {
  if (!video) return;
  video.addEventListener("timeupdate", onStudioVideoTimeUpdate);
  video.addEventListener("loadedmetadata", updateStudioClock);
  video.addEventListener("ended", onStudioVideoEnded);
  video.addEventListener("play", updateStudioPlaybackButton);
  video.addEventListener("pause", updateStudioPlaybackButton);
}


export async function loadTimeline() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline`);
  state.timeline = data.timeline;
  await loadSmoothPreview({ render: false });
  await loadSfxSuggestions({ render: false });
  if (state.timeline && !state.selectedItemId) {
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
  }
  renderCallback();
}


export async function loadSmoothPreview(options = {}) {
  if (!state.projectId) return defaultSmoothPreview();
  const data = await api(`/api/videodesign/projects/${state.projectId}/preview`);
  state.smoothPreview = data.preview || defaultSmoothPreview();
  if (!smoothPreviewUsable() && state.previewMode === "smooth") {
    state.previewMode = "realtime";
  }
  if (options.render !== false) renderStudio();
  return state.smoothPreview;
}


export async function loadSfxCatalog(options = {}) {
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


export async function loadSfxSuggestions(options = {}) {
  if (!state.projectId) return [];
  const data = await api(`/api/videodesign/projects/${state.projectId}/sfx/suggestions`);
  state.sfxSuggestions = data.suggestions || [];
  if (options.render !== false) renderStudio();
  return state.sfxSuggestions;
}


export async function createTimeline() {
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


export async function clearTimeline() {
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


export async function buildSmoothPreview() {
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


export async function renderExportVideo() {
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


export function downloadExportVideo() {
  ensureProject();
  if (state.smoothPreview?.status !== "ready" || !state.smoothPreview?.preview_url) {
    setStatus("Render export first.", "error");
    return;
  }
  window.location.href = `/api/videodesign/projects/${state.projectId}/export/file`;
}


export function toggleSmoothPreviewMode() {
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


export function renderStudio() {
  renderSmoothPreviewControls();
  renderStudioToolPanel();
  renderStudioStage();
  renderStudioInspector();
  renderTimeline();
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}


export function smoothPreviewUsable() {
  return ["ready", "stale"].includes(state.smoothPreview?.status) && Boolean(state.smoothPreview?.preview_url);
}


export function smoothPreviewActive() {
  return state.previewMode === "smooth" && smoothPreviewUsable();
}


export function markSmoothPreviewStale() {
  if (!state.smoothPreview?.preview_url) {
    state.smoothPreview = defaultSmoothPreview();
    state.previewMode = "realtime";
    return;
  }
  if (state.smoothPreview.status === "ready") {
    state.smoothPreview = { ...state.smoothPreview, status: "stale" };
  }
}


export function renderSmoothPreviewControls() {
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


export function smoothPreviewStatusLabel(preview) {
  const status = preview?.status || "missing";
  if (status === "ready") return `Smooth ready ${formatDuration(preview.duration_seconds || state.timeline?.duration_seconds || 0)}`;
  if (status === "stale") return "Smooth stale - rebuild";
  if (status === "rendering") return "Rendering smooth preview";
  if (status === "failed") return preview?.error?.message || "Smooth preview failed";
  return "Preview missing";
}
