import { api, run } from "../api.js";
import { state } from "../state.js";
import { setStatus, timelineItems } from "../ui.js";
import { clamp, escapeHtml, formatDuration, inputChecked, inputValue, transitionLabel } from "../utils.js";
import { replaceTimelineItem } from "./timeline.js";

const callbacks = {
  deleteTimelineItem: async () => {},
  loadSfxCatalog: async () => [],
  loadTimeline: async () => {},
  markSmoothPreviewStale: () => {},
};

export function configureAudio(next) {
  Object.assign(callbacks, next);
}


export function renderAudioPanel(panel) {
  if (!state.timeline) {
    panel.innerHTML = `<h3>Audio</h3><p class="vd-muted">Create a timeline before adding SFX.</p>`;
    return;
  }
  if (!state.sfxCatalog.length && !state.sfxCatalogLoading) {
    callbacks.loadSfxCatalog({ render: true }).catch(() => {});
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
    if (item) callbacks.deleteTimelineItem(item.item_id);
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


export function backgroundMusicControlsHtml(item) {
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


export function sfxSuggestionRow(suggestion) {
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


export function transitionSfxRulesHtml() {
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


export function backgroundMusicItem() {
  return timelineItems().find((item) => item.type === "music") || null;
}


export function updateMusicSliderLabel(inputId, labelId) {
  const input = document.getElementById(inputId);
  const label = document.getElementById(labelId);
  if (input && label) label.textContent = `${Math.round(Number(input.value || 0))}%`;
}


export function updateMusicTrimControls(source) {
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


export async function uploadBackgroundMusic() {
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
    callbacks.markSmoothPreviewStale();
    setStatus("Background music added.", "idle");
  });
}


export async function saveBackgroundMusic() {
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
    callbacks.markSmoothPreviewStale();
    setStatus("Background music mix saved.", "idle");
  });
}


export async function generateSfxSuggestions() {
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
    await callbacks.loadSfxCatalog({ render: false });
    setStatus(`Generated ${state.sfxSuggestions.length} SFX suggestion(s).`, "idle");
  });
}


export async function applySelectedSfxSuggestions() {
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
    callbacks.markSmoothPreviewStale();
    setStatus(`Applied ${data.applied?.length || 0} SFX item(s).`, "idle");
  });
}


export async function clearTimelineSfx() {
  const items = timelineItems().filter((item) => item.type === "sfx");
  if (!items.length) return;
  if (!window.confirm(`Remove ${items.length} SFX item(s) from the timeline?`)) return;
  await run("Clearing SFX", async () => {
    for (const item of items) {
      await callbacks.deleteTimelineItem(item.item_id, false);
    }
    await callbacks.loadTimeline();
    callbacks.markSmoothPreviewStale();
  });
}


export function sfxPreviewVolume(button) {
  const suggestionId = button.dataset.previewSfxSuggestion;
  if (!suggestionId) return undefined;
  const input = document.querySelector(`[data-sfx-volume="${CSS.escape(suggestionId)}"]`);
  return input ? clamp(Number(input.value || 0.35), 0, 1) : undefined;
}


export function previewSfx(assetId, volumeOverride = undefined) {
  const asset = sfxAsset(assetId);
  const url = asset?.audio_url || `/api/videodesign/sfx/${assetId}/file`;
  const audio = new Audio(url);
  audio.volume = clamp(Number(volumeOverride ?? Math.min(0.8, Number(asset?.default_volume || 0.35) * 1.4)), 0, 1);
  const promise = audio.play();
  if (promise?.catch) promise.catch(() => setStatus("Browser blocked SFX preview. Try clicking Play again.", "error"));
}


export function sfxAsset(assetId) {
  return state.sfxCatalog.find((asset) => asset.asset_id === assetId) || null;
}
