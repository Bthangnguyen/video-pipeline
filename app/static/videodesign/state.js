import { defaultPreset, defaultSmoothPreview } from "./utils.js";

export const state = {
  projectId: "",
  project: null,
  projects: [],
  rows: [],
  timeline: null,
  activeView: "start",
  selectedSceneId: "",
  selectedSearchGroupId: "",
  selectedItemId: "",
  previewCandidateId: "",
  smoothPreview: defaultSmoothPreview(),
  previewMode: "realtime",
  sfxCatalog: [],
  sfxSuggestions: [],
  sfxTransitionPresets: [],
  sfxCatalogLoading: false,
  materialHealth: null,
  materialCoverCache: {},
  selectedTool: "script",
  timelineFit: true,
  timelinePixelsPerSecond: 48,
  timelinePlayheadSeconds: 0,
  timelinePlaying: false,
  playedSfxIds: new Set(),
  running: false,
  lastProgressMessage: "",
  preset: defaultPreset(),
};

export const TIMELINE_LABEL_WIDTH = 122;
export const TIMELINE_LABEL_WIDTH_COMPACT = 96;
export const TIMELINE_MIN_CLIP_SECONDS = 0.25;
export const TIMELINE_MIN_ZOOM = 18;
export const TIMELINE_MAX_ZOOM = 140;
export const TRANSITION_PRELOAD_MARGIN = 0.55;
export const SAFE_REALTIME_TRANSITIONS = new Set(["none", "fade", "dissolve", "slide_left", "slide_right", "slide_up", "zoom_in", "zoom_out"]);
export const FONT_OPTIONS = ["Inter", "Montserrat", "Poppins", "Anton", "Bebas Neue", "Arial", "Georgia"];
export const CAPTION_MODES = ["one_word", "full_line", "word_reveal", "active_word_highlight", "typewriter", "two_line_karaoke"];
export const OVERLAY_OPTIONS = ["none", "caption_shadow", "soft_vignette", "focus_frame", "dim_background", "caption_shade", "subtle_grain"];
export const TRANSITION_OPTIONS = ["none", "fade", "dissolve", "slide_left", "slide_right", "slide_up", "zoom_in", "zoom_out", "whip_pan", "flash_cut"];
export const ICON_OPTIONS = ["arrow_right", "circle", "rectangle", "underline", "check", "x_mark", "starburst", "pointer", "question", "exclamation"];

export const viewTitles = {
  start: "Create video",
  script: "Script creation",
  template: "Template setup",
  plan: "Scene plan",
  materials: "Material review",
  studio: "Studio timeline",
};
