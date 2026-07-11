import { api, run } from "../api.js";
import { CAPTION_MODES, FONT_OPTIONS, ICON_OPTIONS, OVERLAY_OPTIONS, TRANSITION_OPTIONS, state } from "../state.js";
import { replaceScene, selectFirstItemForScene, selectedItem, selectedRow, timelineItems } from "../ui.js";
import {
  clamp,
  escapeHtml,
  formatDuration,
  inputChecked,
  inputValue,
  overlayLabel,
  textForItem,
  titleCase,
  transitionLabel,
} from "../utils.js";
import { renderAudioPanel } from "./audio.js";
import { assetDurationFromMedia, mediaTrimStart } from "./playback.js";
import {
  applyCaptionDraftToStage,
  applyIconDraftToStage,
  applyTextDraftToStage,
  applyTrimDraftToStage,
  captionModeLabel,
  iconPreview,
} from "./stage.js";
import { patchTimelineItem, replaceTimelineItem, sceneBounds } from "./timeline.js";

const callbacks = {
  markSmoothPreviewStale: () => {},
  renderStudio: () => {},
};

export function configurePanels(next) {
  Object.assign(callbacks, next);
}


export function renderStudioToolPanel() {
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
      callbacks.renderStudio();
    });
  });
}


export function renderTextStylePanel(panel, row) {
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


export function renderCaptionStylePanel(panel, row) {
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


export function renderOverlayPanel(panel, row) {
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


export function renderTransitionsPanel(panel, row) {
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


export function renderIconsPanel(panel, row) {
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


export function itemForScene(type, row = selectedRow()) {
  return timelineItems().find((item) => item.type === type && item.scene_id === row?.scene.scene_id) || null;
}


export function itemsForScene(type, row = selectedRow()) {
  return timelineItems().filter((item) => item.type === type && item.scene_id === row?.scene.scene_id);
}


export function fontOptionsHtml(selected) {
  return optionListHtml(FONT_OPTIONS, selected || "Montserrat", (value) => value);
}


export function optionListHtml(values, selected, labeler) {
  return values.map((value) => `<option value="${escapeHtml(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(labeler(value))}</option>`).join("");
}


export function optionButtonHtml(datasetName, value, label, active) {
  return `<button data-${datasetName}="${escapeHtml(value)}" data-active="${active ? "true" : "false"}" type="button">${label}</button>`;
}


export function selectedOption(panel, datasetName) {
  return panel.querySelector(`[data-${datasetName}][data-active="true"]`)?.dataset[toDatasetKey(datasetName)] || "";
}


export function toDatasetKey(name) {
  return name.replace(/-([a-z])/g, (_match, char) => char.toUpperCase());
}


export function textStyle(item) {
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


export function captionStyle(item) {
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


export function collectTextStyle(panel) {
  return {
    font_family: inputValue("studio-text-font", "Montserrat"),
    font_size: Number(inputValue("studio-text-size", 42)),
    font_weight: inputChecked("studio-text-bold", true) ? 800 : 400,
    italic: inputChecked("studio-text-italic", false),
    text_color: inputValue("studio-text-color", "#ffffff"),
    shadow: inputChecked("studio-text-shadow", true),
  };
}


export function collectCaptionStyle(panel) {
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


export async function saveCaptionStyle(panel, item) {
  if (!item || item.type !== "caption") return;
  applyCaptionDraftToStage(panel, item);
  await patchTimelineItem(item.item_id, { style: item.style, transform: item.transform });
}


export async function applyCaptionStyleAll(panel, item) {
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
  callbacks.renderStudio();
}


export function overlayIdForItem(item) {
  return item?.source_ref?.overlay_id || item?.source_ref?.overlay_pack_id || item?.style?.overlay_pack_id || "none";
}


export function transitionIdForItem(item) {
  return item?.source_ref?.transition_id || item?.source_ref?.transition_pack_id || item?.style?.transition_id || item?.style?.transition_pack_id || "none";
}


export function previewOverlay(overlayId, opacity = 0.35) {
  const stage = document.getElementById("studio-stage");
  if (!stage) return;
  stage.dataset.overlay = overlayId || "none";
  stage.style.setProperty("--scene-overlay-opacity", String(opacity));
}


export async function saveOverlay(sceneId, overlayId, opacity) {
  if (!sceneId) return;
  await run("Saving overlay", async () => {
    await upsertOverlayForScene(sceneId, overlayId, opacity);
  });
}


export async function applyOverlayAll(overlayId, opacity) {
  await run("Applying overlay", async () => {
    for (const row of state.rows) {
      await upsertOverlayForScene(row.scene.scene_id, overlayId, opacity);
    }
  });
}


export async function upsertOverlayForScene(sceneId, overlayId, opacity) {
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
    callbacks.markSmoothPreviewStale();
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
  callbacks.markSmoothPreviewStale();
}


export function _transitionHasNextScene(sceneId) {
  const media = timelineItems().filter((item) => item.type === "media").sort((a, b) => a.start_seconds - b.start_seconds);
  return media.findIndex((item) => item.scene_id === sceneId) >= 0 && media.findIndex((item) => item.scene_id === sceneId) < media.length - 1;
}


export async function saveSelectedTransition(sceneId) {
  await run("Saving transition", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/transition`, {
      method: "POST",
      body: {
        transition_id: inputValue("transition-id", "fade"),
        duration_seconds: Number(inputValue("transition-duration", 0.35)),
      },
    });
    state.timeline = data.timeline;
    callbacks.markSmoothPreviewStale();
  });
}


export async function saveAllTransitions(transitionId) {
  await run("Applying transitions", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/transitions/apply-all`, {
      method: "POST",
      body: {
        transition_id: transitionId,
        duration_seconds: Number(inputValue("transition-duration", 0.35)),
      },
    });
    state.timeline = data.timeline;
    callbacks.markSmoothPreviewStale();
  });
}


export async function randomizeTransitions() {
  await run("Randomizing transitions", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/transitions/randomize`, { method: "POST" });
    state.timeline = data.timeline;
    callbacks.markSmoothPreviewStale();
  });
}


export async function addIconToScene(sceneId, iconId) {
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
    callbacks.markSmoothPreviewStale();
    state.selectedItemId = data.item.item_id;
    state.selectedTool = "icons";
  });
}


export async function saveIcon(panel, item) {
  if (!item || item.type !== "icon") return;
  applyIconDraftToStage(panel, item);
  await patchTimelineItem(item.item_id, { transform: item.transform, style: item.style });
}


export async function deleteTimelineItem(itemId, rerender = true) {
  if (!itemId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, { method: "DELETE" });
  state.timeline = data.timeline;
  callbacks.markSmoothPreviewStale();
  if (state.selectedItemId === itemId) state.selectedItemId = "";
  if (rerender) callbacks.renderStudio();
}


export function renderStudioMediaPanel(panel, row) {
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
    panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigateCallback("materials"));
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


export function bindStudioMediaPanel(panel, media, row) {
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
  panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigateCallback("materials"));
  panel.querySelectorAll("#trim-flip-horizontal, #trim-contrast, #trim-brightness, #trim-saturation").forEach((input) => {
    input.addEventListener("input", () => applyTrimDraftToStage(panel));
  });
  sync(mediaTrimStart(media), true);
  applyTrimDraftToStage(panel);
}


export function updateTrimControls(panel, media, row, value = null) {
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


export function playTrimSegment(panel, media, row) {
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


export async function saveSceneClip(panel, media, row, trimSource) {
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
      callbacks.markSmoothPreviewStale();
    }
  });
}


export function trimTransformFromPanel(panel) {
  return {
    flip_horizontal: Boolean(panel.querySelector("#trim-flip-horizontal")?.checked),
  };
}


export function trimEffectsFromPanel(panel) {
  return {
    contrast: Number(panel.querySelector("#trim-contrast")?.value || 1),
    brightness: Number(panel.querySelector("#trim-brightness")?.value || 1),
    saturation: Number(panel.querySelector("#trim-saturation")?.value || 1),
  };
}


export async function saveStudioText(panel = null, item = selectedItem()) {
  if (!item || item.type !== "text") return;
  if (panel) applyTextDraftToStage(panel, item);
  else item.source_ref = { ...(item.source_ref || {}), text: document.getElementById("studio-text-input")?.value.trim() || textForItem(item) };
  await patchTimelineItem(item.item_id, { source_ref: item.source_ref, style: item.style, transform: item.transform });
}


export function studioToolForItem(item) {
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
