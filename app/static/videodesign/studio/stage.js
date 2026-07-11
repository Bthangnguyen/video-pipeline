import { state } from "../state.js";
import { selectedItem, selectedRow, timelineItems } from "../ui.js";
import {
  captionLabel,
  clamp,
  escapeHtml,
  formatDuration,
  inputValue,
  itemLabel,
  overlayLabel,
  rgbaFromHex,
  textForItem,
  transitionLabel,
} from "../utils.js";
import {
  applyStudioMediaEffects,
  combinedVoiceoverTrack,
  currentMediaItem,
  mediaTrimEnd,
  mediaTrimStart,
  musicLocalTime,
  musicPreviewVolume,
  setPlaybackElementSource,
  trimStatusLabel,
  updateStudioClock,
  updateStudioPlaybackButton,
} from "./playback.js";

const callbacks = {
  backgroundMusicItem: () => null,
  captionStyle: () => ({}),
  collectCaptionStyle: () => ({}),
  collectTextStyle: () => ({}),
  itemForScene: () => null,
  itemsForScene: () => [],
  overlayIdForItem: () => "none",
  renderStudio: () => {},
  smoothPreviewActive: () => false,
  smoothPreviewStatusLabel: () => "",
  startCanvasIconDrag: () => {},
  summaryRow: () => "",
  textStyle: () => ({}),
  trimEffectsFromPanel: () => ({}),
  trimTransformFromPanel: () => ({}),
};

export function configureStage(next) {
  Object.assign(callbacks, next);
}


export function applyTextDraftToStage(panel, item) {
  if (!item) return;
  item.source_ref = { ...(item.source_ref || {}), text: inputValue("studio-text-input", textForItem(item)) };
  item.source_ref.user_text = true;
  item.style = callbacks.collectTextStyle(panel);
  item.transform = { ...(item.transform || {}), scale: Number(inputValue("studio-text-scale", item.transform?.scale || 1)) };
  renderStudioText(item);
}


export function applyCaptionDraftToStage(panel, item) {
  if (!item) return;
  item.style = callbacks.collectCaptionStyle(panel);
  updateCaptionPreview(state.timelinePlayheadSeconds);
}


export function applyIconDraftToStage(panel, item) {
  if (!item) return;
  item.style = { ...(item.style || {}), color: inputValue("icon-color", "#ffffff") };
  item.transform = {
    ...(item.transform || {}),
    scale: Number(inputValue("icon-scale", item.transform?.scale || 1)),
    rotation: Number(inputValue("icon-rotation", item.transform?.rotation || 0)),
  };
  renderStudioIcons();
}


export function captionModeLabel(value) {
  return {
    one_word: "One word",
    full_line: "Full line",
    word_reveal: "Word reveal",
    active_word_highlight: "Active word",
    typewriter: "Typewriter",
    two_line_karaoke: "Two-line karaoke",
  }[value] || String(value).replaceAll("_", " ");
}


export function iconPreview(value) {
  return `<span class="vd-icon-sample">${iconGlyph(value)}</span><small>${escapeHtml(iconLabel(value))}</small>`;
}


export function iconGlyph(value) {
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


export function iconLabel(value) {
  return {
    arrow_right: "Arrow",
    x_mark: "X mark",
  }[value] || String(value).replaceAll("_", " ");
}


export function applyTrimDraftToStage(panel) {
  const media = currentMediaItem();
  if (!media) return;
  media.transform = { ...(media.transform || {}), ...callbacks.trimTransformFromPanel(panel) };
  media.source_ref = { ...(media.source_ref || {}), effects: callbacks.trimEffectsFromPanel(panel) };
  applyStudioMediaEffects(document.getElementById("studio-video"), media);
}


export function renderStudioStage() {
  const row = selectedRow();
  const media = timelineItems().find((item) => item.type === "media" && item.scene_id === row?.scene.scene_id);
  const audioItem = timelineItems().find((item) => item.type === "audio" && item.scene_id === row?.scene.scene_id);
  const musicItem = callbacks.backgroundMusicItem();
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
  const useSmoothPreview = callbacks.smoothPreviewActive();

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
  mediaState.textContent = useSmoothPreview ? callbacks.smoothPreviewStatusLabel(state.smoothPreview) : studioMediaStateLabel(media, audioItem, voiceoverTrack, musicItem);
  stage.dataset.overlay = callbacks.overlayIdForItem(overlay);
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


export function renderStudioText(item) {
  const textEl = document.getElementById("studio-text");
  if (!textEl) return;
  if (!item) {
    textEl.textContent = "";
    textEl.dataset.itemId = "";
    return;
  }
  const style = callbacks.textStyle(item);
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


export function visibleTextForItem(item) {
  const text = textForItem(item);
  const row = selectedRow();
  if (!text) return "";
  const isDefaultSceneText = row && [row.scene.on_screen_text, row.scene.voiceover_text, row.scene.caption_text]
    .filter(Boolean)
    .some((value) => String(value).trim() === String(text).trim());
  if (isDefaultSceneText && !item?.source_ref?.user_text) return "";
  return text;
}


export function updateCaptionPreview(globalTime = state.timelinePlayheadSeconds) {
  const row = selectedRow();
  const item = callbacks.itemForScene("caption", row);
  const captionEl = document.getElementById("studio-caption");
  if (!captionEl) return;
  const chunks = item?.source_ref?.caption_chunks || row?.scene.caption_chunks || [];
  const style = callbacks.captionStyle(item);
  applyCaptionStyleToElement(captionEl, style);
  applyCaptionTransformToElement(captionEl, item);
  captionEl.innerHTML = captionHtmlForTime(chunks, row, item, globalTime, style);
}


export function applyCaptionStyleToElement(element, style) {
  element.style.fontFamily = style.font_family || "Montserrat";
  element.style.fontSize = `${Number(style.font_size || 46)}px`;
  element.style.fontWeight = String(style.font_weight || 800);
  element.style.fontStyle = style.italic ? "italic" : "normal";
  element.style.color = style.text_color || "#ffffff";
  element.style.textShadow = style.shadow === false ? "none" : `0 2px 10px ${style.stroke_color || "#111111"}`;
  element.style.setProperty("--caption-active-glow", style.glow === false ? "none" : activeWordGlow(style));
}


export function applyCaptionTransformToElement(element, item) {
  if (!element) return;
  const transform = item?.transform || { x: 50, y: 78, scale: 1, rotation: 0 };
  element.style.left = `${Number(transform.x ?? 50)}%`;
  element.style.top = `${Number(transform.y ?? 78)}%`;
  element.style.bottom = "auto";
  element.style.transform = `translate(-50%, -50%) scale(${Number(transform.scale || 1)}) rotate(${Number(transform.rotation || 0)}deg)`;
}


export function activeWordGlow(style) {
  const color = style.glow_color || style.active_word_color || "#3ce6ac";
  const blur = Math.max(0, Number(style.glow_blur ?? 14));
  const intensity = clamp(Number(style.glow_intensity ?? 0.75), 0, 1);
  if (!blur || !intensity) return "none";
  return `0 0 ${blur}px ${rgbaFromHex(color, intensity)}, 0 0 ${Math.round(blur * 0.45)}px ${color}`;
}


export function captionHtmlForTime(chunks, row, item, globalTime, style) {
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


export function renderStudioIcons() {
  const layer = document.getElementById("studio-icon-layer");
  if (!layer) return;
  const row = selectedRow();
  const icons = callbacks.itemsForScene("icon", row);
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
    button.addEventListener("pointerdown", callbacks.startCanvasIconDrag);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedItemId = button.dataset.iconItemId;
      state.selectedTool = "icons";
      callbacks.renderStudio();
    });
  });
}


export function studioMediaStateLabel(media, audioItem, voiceoverTrack = combinedVoiceoverTrack(), musicItem = callbacks.backgroundMusicItem()) {
  if (!media?.source_ref?.media_url) return "No media";
  const cutLabel = `Cut ${formatDuration(mediaTrimStart(media))}-${formatDuration(mediaTrimEnd(media))}`;
  const voice = voiceoverTrack?.audio_url || audioItem?.source_ref?.audio_url ? " + voice" : " / no voice";
  const music = musicItem?.source_ref?.audio_url && musicItem.style?.enabled !== false ? " + music" : "";
  if (voiceoverTrack?.audio_url) return `${trimStatusLabel(media)} / ${cutLabel} + project voice${music}`;
  return `${trimStatusLabel(media)} / ${cutLabel}${voice}${music}`;
}


export function renderStudioInspector() {
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
    ${callbacks.summaryRow("Scene", row ? `Scene ${row.scene.order}` : "None")}
    ${callbacks.summaryRow("Selected", item ? itemLabel(item) : "None")}
    ${callbacks.summaryRow("Start", item ? formatDuration(item.start_seconds) : "0:00")}
    ${callbacks.summaryRow("End", item ? formatDuration(item.end_seconds) : "0:00")}
    ${item?.type === "media" ? callbacks.summaryRow("Source trim", `${formatDuration(mediaTrimStart(item))} - ${formatDuration(mediaTrimEnd(item))}`) : ""}
    ${callbacks.summaryRow("Text style", captionLabel(state.preset.captions.style_id))}
    ${callbacks.summaryRow("Transition", transitionLabel(state.preset.extras.transition_pack_id))}
    ${callbacks.summaryRow("Overlay", overlayLabel(state.preset.extras.overlay_pack_id))}
  `;
}
