import { api } from "../api.js";
import {
  TIMELINE_LABEL_WIDTH,
  TIMELINE_LABEL_WIDTH_COMPACT,
  TIMELINE_MAX_ZOOM,
  TIMELINE_MIN_CLIP_SECONDS,
  TIMELINE_MIN_ZOOM,
  state,
} from "../state.js";
import { selectedItem, timelineItems } from "../ui.js";
import { clamp, escapeHtml, formatDuration } from "../utils.js";
import {
  mediaItemAtTime,
  pauseStudioMedia,
  placeTimelineClip,
  playTimelineFrom,
  syncSmoothPreviewToTimeline,
  syncStudioVideoToTimeline,
  timelineClipLabel,
  updateStudioClock,
  updateStudioPlaybackButton,
  updateTimelineClipActiveStates,
  updateTimelinePlayhead,
} from "./playback.js";
import { renderStudioIcons, renderStudioInspector, renderStudioStage, updateCaptionPreview } from "./stage.js";

let dragState = null;
const callbacks = {
  itemForScene: () => null,
  markSmoothPreviewStale: () => {},
  renderStudio: () => {},
  renderStudioToolPanel: () => {},
  smoothPreviewActive: () => false,
  studioToolForItem: () => "script",
};

export function configureTimeline(next) {
  Object.assign(callbacks, next);
}


export function replaceTimelineItem(item) {
  const index = state.timeline?.items.findIndex((entry) => entry.item_id === item.item_id) ?? -1;
  if (index >= 0) state.timeline.items[index] = item;
}


export function sceneBounds(sceneId) {
  const media = timelineItems().find((item) => item.scene_id === sceneId && item.type === "media");
  return { start: media?.start_seconds || 0, end: media?.end_seconds || 0 };
}


export function renderTimeline() {
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
      const tool = callbacks.studioToolForItem(item);
      if (tool) state.selectedTool = tool;
      callbacks.renderStudio();
    });
    clip.addEventListener("pointerdown", startTimelineDrag);
  });
  updateTimelineZoomButtons();
  updateStudioClock();
}


export function timelineClip(item, metrics) {
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


export function timelineMetrics(duration = Math.max(1, state.timeline?.duration_seconds || 1)) {
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


export function timelineTicks(duration, metrics) {
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


export function niceTimelineStep(rawStep) {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60];
  return steps.find((step) => step >= rawStep) || 120;
}


export function editableTimelineItem(item) {
  return ["media", "text", "caption", "overlay", "icon", "transition", "music", "sfx"].includes(item?.type);
}


export function fitTimeline() {
  state.timelineFit = true;
  renderTimeline();
}


export function zoomTimeline(direction) {
  state.timelineFit = false;
  const factor = direction > 0 ? 1.25 : 0.8;
  state.timelinePixelsPerSecond = clamp(state.timelinePixelsPerSecond * factor, TIMELINE_MIN_ZOOM, TIMELINE_MAX_ZOOM);
  renderTimeline();
}


export function updateTimelineZoomButtons() {
  const fit = document.getElementById("timeline-fit");
  const zoomOut = document.getElementById("timeline-zoom-out");
  const zoomIn = document.getElementById("timeline-zoom-in");
  if (fit) fit.dataset.active = state.timelineFit ? "true" : "false";
  if (zoomOut) zoomOut.disabled = !state.timeline || (!state.timelineFit && state.timelinePixelsPerSecond <= TIMELINE_MIN_ZOOM);
  if (zoomIn) zoomIn.disabled = !state.timeline || (!state.timelineFit && state.timelinePixelsPerSecond >= TIMELINE_MAX_ZOOM);
}


export function seekTimelineFromPointer(event) {
  if (!state.timeline || event.button !== 0 || event.target.closest("[data-item-id]")) return;
  if (event.target.closest("#timeline-playhead")) return;
  const fromRuler = event.currentTarget?.id === "timeline-ruler";
  if (!fromRuler && !event.target.closest(".vd-track-lane")) return;
  const time = timeFromTimelinePointer(event);
  if (time !== null) seekTimeline(time, { autoplay: state.timelinePlaying });
}


export function seekTimeline(globalTime, options = {}) {
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
    callbacks.renderStudio();
    if (callbacks.smoothPreviewActive()) {
      syncSmoothPreviewToTimeline(time, options);
      return;
    }
    syncStudioVideoToTimeline(time, options);
    return;
  }
  updateStudioClock(time);
}


export function startCanvasTextDrag(event) {
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


export function startCanvasCaptionDrag(event) {
  const itemId = event.currentTarget.dataset.itemId;
  const item = timelineItems().find((entry) => entry.item_id === itemId) || callbacks.itemForScene("caption");
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


export function startCanvasIconDrag(event) {
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


export function startTimelineDrag(event) {
  const item = state.timeline?.items.find((entry) => entry.item_id === event.currentTarget.dataset.itemId);
  if (!item || !editableTimelineItem(item)) return;
  event.preventDefault();
  event.stopPropagation();
  const lane = event.currentTarget.closest(".vd-track-lane");
  const metrics = timelineMetrics();
  state.selectedItemId = item.item_id;
  state.selectedSceneId = item.scene_id;
  const tool = callbacks.studioToolForItem(item);
  if (tool) state.selectedTool = tool;
  updateTimelineClipActiveStates();
  callbacks.renderStudioToolPanel();
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


export function startPlayheadDrag(event) {
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


export function onPointerMove(event) {
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


export async function endPointerDrag() {
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


export function scrubTimelineToPointer(event) {
  const time = timeFromTimelinePointer(event);
  if (time === null) return;
  seekTimeline(time, { autoplay: false, tolerateDrift: false });
}


export function timeFromTimelinePointer(event) {
  if (!state.timeline) return null;
  const board = document.querySelector(".vd-timeline-board");
  if (!board) return null;
  const metrics = timelineMetrics();
  const rect = board.getBoundingClientRect();
  const x = event.clientX - rect.left + board.scrollLeft - metrics.labelWidth;
  return clamp(x / metrics.pxPerSecond, 0, metrics.duration);
}


export async function patchTimelineItem(itemId, patch, options = {}) {
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, {
    method: "PATCH",
    body: patch,
  });
  const index = state.timeline.items.findIndex((item) => item.item_id === itemId);
  if (index >= 0) state.timeline.items[index] = data.item;
  callbacks.markSmoothPreviewStale();
  if (options.render !== false) callbacks.renderStudio();
}
