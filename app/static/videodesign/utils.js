export function projectStageLabel(stage) {
  return {
    idea: "Idea",
    script: "Script",
    plan: "Plan",
    review_materials: "Review",
    materials_downloaded: "Materials",
    studio: "Studio",
    export_ready: "Export ready",
  }[stage] || "Project";
}


export function formatProjectDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}


export function defaultSmoothPreview() {
  return { status: "missing", preview_url: "", preview_path: "", timeline_id: "", duration_seconds: 0, updated_at: "", error: {} };
}


export function defaultPreset() {
  return {
    format: { aspect_ratio: "9:16", platform: "tiktok", target_duration_seconds: 45 },
    template: { template_id: "short_form_editor", template_category: "timeline_template", scene_pacing: "normal" },
    scene_media: { media_source: "multi_source", candidate_count: 4, pinterest_candidate_count: 4, translate_to_chinese: true },
    voiceover: { provider: "free_tts", voice_id: "en-US-AriaNeural", voice_speed: 1, language: "en" },
    captions: { enabled: true, style_id: "bold_outline", position: "bottom_safe", animation_id: "word_reveal" },
    video_defaults: { flip_horizontal: false, brightness: 1, contrast: 1.08, saturation: 1.08 },
    extras: { transition_pack_id: "fade", overlay_pack_id: "caption_shadow", icon_pack_id: "none" },
  };
}


export function mergePreset(base, source) {
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


export function setByPath(target, path, value) {
  const parts = path.split(".");
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    cursor[part] = cursor[part] || {};
    cursor = cursor[part];
  }
  cursor[parts.at(-1)] = value;
}


export function getByPath(target, path) {
  return path.split(".").reduce((cursor, part) => cursor?.[part], target);
}


export function templateLabel(value) {
  return {
    short_form_editor: "Short-form editor",
    dynamic_short: "Legacy dynamic short",
    explainer_clean: "Legacy explainer",
    quote_motivation: "Legacy motivation",
  }[value] || value;
}


export function captionLabel(value) {
  return {
    bold_outline: "Bold outline",
    word_reveal: "Word reveal",
    clean_lower: "Clean lower third",
  }[value] || String(value || "").replaceAll("_", " ");
}


export function voiceLabel(value) {
  return {
    "en-US-AriaNeural": "Aria",
    "en-US-JennyNeural": "Jenny",
    "en-US-GuyNeural": "Guy",
    "en-US-RogerNeural": "Roger",
    "en-US-AnaNeural": "Ana",
    "en-GB-SoniaNeural": "Sonia",
  }[value] || String(value || "Voice");
}


export function videoDefaultsLabel(defaults = {}) {
  const parts = [];
  if (defaults.flip_horizontal) parts.push("flip");
  if (Math.abs(Number(defaults.contrast ?? 1) - 1) > 0.01) parts.push(`contrast ${Number(defaults.contrast).toFixed(2)}`);
  if (Math.abs(Number(defaults.saturation ?? 1) - 1) > 0.01) parts.push(`saturation ${Number(defaults.saturation).toFixed(2)}`);
  if (Math.abs(Number(defaults.brightness ?? 1) - 1) > 0.01) parts.push(`brightness ${Number(defaults.brightness).toFixed(2)}`);
  return parts.length ? parts.join(", ") : "natural";
}


export function transitionLabel(value) {
  return {
    none: "None",
    mix: "Mix motion",
    clean_cut: "Clean cut",
    fade: "Fade",
    dissolve: "Dissolve",
    slide_left: "Slide left",
    slide_right: "Slide right",
    slide_up: "Slide up",
    zoom_in: "Zoom in",
    zoom_out: "Zoom out",
    whip_pan: "Whip pan",
    flash_cut: "Flash cut",
    push_slide: "Push slide",
    speed_zoom: "Speed zoom",
    fast_swipes: "Legacy fast swipes",
  }[value] || String(value || "").replaceAll("_", " ");
}


export function overlayLabel(value) {
  return {
    none: "None",
    caption_shadow: "Caption shadow",
    focus_frame: "Focus frame",
    soft_vignette: "Soft vignette",
    dim_background: "Dim background",
    caption_shade: "Caption shade",
    subtle_grain: "Subtle grain",
    clean_shadow: "Legacy clean shadow",
  }[value] || String(value || "").replaceAll("_", " ");
}


export function itemLabel(item) {
  if (!item) return "";
  return {
    media: "Video",
    caption: "Captions",
    text: "Text",
    overlay: "Overlay",
    icon: "Icon",
    audio: "Voice",
    sfx: "SFX",
    transition: "Transition",
  }[item.type] || titleCase(item.type);
}


export function mediaLabel(value) {
  return {
    douyin_stock: "Douyin stock",
    multi_source: "Douyin + Pinterest",
    uploads: "Uploads",
    placeholder: "Placeholder",
  }[value] || value;
}


export function sourceLabel(value) {
  return {
    douyinsearch: "Douyin",
    pinterestsearch: "Pinterest",
  }[value] || "Source";
}


export function textForItem(item) {
  return item?.source_ref?.text || "";
}


export function titleCase(value) {
  return String(value).slice(0, 1).toUpperCase() + String(value).slice(1);
}


export function wordCount(text) {
  return String(text || "").trim().split(/\s+/).filter(Boolean).length;
}


export function sentenceCount(text) {
  return String(text || "").split(/[.!?]+/).map((part) => part.trim()).filter(Boolean).length;
}


export function keywordsFromText(text) {
  return String(text || "").split(",").map((item) => item.trim()).filter(Boolean);
}


export function uniqueValues(values) {
  const seen = new Set();
  return (values || []).map((value) => String(value || "").trim()).filter((value) => {
    const key = value.toLowerCase();
    if (!value || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


export function formatDuration(seconds) {
  const value = Number(seconds || 0);
  const mins = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}


export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}


export function rgbaFromHex(hex, alpha = 1) {
  const value = String(hex || "").replace("#", "").trim();
  const normalized = value.length === 3
    ? value.split("").map((char) => char + char).join("")
    : value.padEnd(6, "0").slice(0, 6);
  const number = Number.parseInt(normalized, 16);
  if (Number.isNaN(number)) return `rgba(60, 230, 172, ${clamp(alpha, 0, 1)})`;
  const red = (number >> 16) & 255;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${clamp(alpha, 0, 1)})`;
}


export function inputValue(id, fallback = "") {
  const input = document.getElementById(id);
  return input ? input.value : String(fallback ?? "");
}


export function inputChecked(id, fallback = false) {
  const input = document.getElementById(id);
  return input ? Boolean(input.checked) : Boolean(fallback);
}


export function setInputValue(id, value) {
  const input = document.getElementById(id);
  if (input) input.value = value;
}


export function setInputChecked(id, value) {
  const input = document.getElementById(id);
  if (input) input.checked = Boolean(value);
}


export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}
