import { SAFE_REALTIME_TRANSITIONS, TRANSITION_PRELOAD_MARGIN, state } from "../state.js";
import { selectedItem, selectedRow, timelineItems } from "../ui.js";
import { clamp, formatDuration, itemLabel, overlayLabel, transitionLabel } from "../utils.js";

let timelineFrameRequest = null;
const callbacks = {
  backgroundMusicItem: () => null,
  iconLabel: () => "",
  overlayIdForItem: () => "none",
  renderStudio: () => {},
  seekTimeline: () => {},
  sfxAsset: () => null,
  smoothPreviewActive: () => false,
  timelineMetrics: () => ({ labelWidth: 0, pxPerSecond: 1 }),
  transitionIdForItem: () => "none",
  updateCaptionPreview: () => {},
};

export function configurePlayback(next) {
  Object.assign(callbacks, next);
}


export function setPlaybackElementSource(element, url) {
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


export function mediaItemAtTime(time) {
  const mediaItems = timelineItems().filter((item) => item.type === "media");
  return mediaItems.find((item) => time >= item.start_seconds && time <= item.end_seconds)
    || mediaItems.find((item) => time < item.start_seconds)
    || mediaItems.at(-1)
    || null;
}


export function syncSmoothPreviewToTimeline(globalTime, options = {}) {
  const video = document.getElementById("studio-video");
  if (!video || !callbacks.smoothPreviewActive()) return;
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


export function syncStudioVideoToTimeline(globalTime, options = {}) {
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


export function combinedVoiceoverTrack() {
  const track = state.project?.voiceover_track;
  return track?.audio_url ? track : null;
}


export function currentAudioItem() {
  return timelineItems().find((item) => item.type === "audio" && item.scene_id === selectedRow()?.scene.scene_id) || null;
}


export function musicPreviewVolume(item = callbacks.backgroundMusicItem()) {
  if (!item || item.style?.enabled === false) return 0;
  const hasVoice = Boolean(combinedVoiceoverTrack()?.audio_url || currentAudioItem()?.source_ref?.audio_url);
  if (hasVoice && item.style?.ducking !== false) {
    return clamp(Number(item.style?.ducking_volume ?? 0.08), 0, 1);
  }
  return clamp(Number(item.style?.volume ?? 0.16), 0, 1);
}


export function musicLocalTime(globalTime, item = callbacks.backgroundMusicItem()) {
  if (!item) return 0;
  const duration = Math.max(0.05, Number(item.source_ref?.duration_seconds || 0.05));
  const trimStart = clamp(Number(item.source_ref?.trim_start_seconds || 0), 0, Math.max(0, duration - 0.05));
  const trimEnd = clamp(Number(item.source_ref?.trim_end_seconds || duration), trimStart + 0.05, duration);
  const trimDuration = Math.max(0.05, trimEnd - trimStart);
  const local = Math.max(0, Number(globalTime || 0) - Number(item.start_seconds || 0));
  if (item.style?.loop !== false) return trimStart + (local % trimDuration);
  return trimStart + clamp(local, 0, trimDuration);
}


export function syncStudioAudioToTimeline(globalTime, options = {}) {
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


export function syncStudioMusicToTimeline(globalTime, options = {}) {
  const music = document.getElementById("studio-music");
  const item = callbacks.backgroundMusicItem();
  if (!music || !item?.source_ref?.audio_url || !music.src || item.style?.enabled === false) return;
  if (globalTime < item.start_seconds || globalTime > item.end_seconds) {
    music.pause();
    return;
  }
  music.volume = musicPreviewVolume(item);
  syncAudioElementToTime(music, musicLocalTime(globalTime, item), options);
}


export function syncAudioElementToTime(audio, targetTime, options = {}) {
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


export function playStudioAudio() {
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


export function pauseStudioMedia() {
  document.getElementById("studio-video")?.pause();
  document.getElementById("studio-next-video")?.pause();
  document.getElementById("studio-audio")?.pause();
  document.getElementById("studio-music")?.pause();
  stopTimelineFrameTicker();
}


export function playStudioVideo() {
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
  if (!callbacks.smoothPreviewActive()) playStudioAudio();
}


export function currentMediaItem() {
  return timelineItems().find((item) => item.type === "media" && item.scene_id === selectedRow()?.scene.scene_id) || null;
}


export function mediaSceneDuration(media, row = selectedRow()) {
  return Number(media?.source_ref?.timeline_duration_seconds || row?.scene?.duration_seconds || ((media?.end_seconds || 0) - (media?.start_seconds || 0)) || 0);
}


export function assetDurationFromMedia(media, video = null) {
  const loadedDuration = Number(video?.duration || 0);
  if (Number.isFinite(loadedDuration) && loadedDuration > 0) return loadedDuration;
  return Number(media?.source_ref?.asset_duration_seconds || 0);
}


export function globalTimeFromVideo(media = currentMediaItem(), video = document.getElementById("studio-video")) {
  if (callbacks.smoothPreviewActive()) {
    return clamp(Number(video?.currentTime || 0), 0, Math.max(1, state.timeline?.duration_seconds || 1));
  }
  if (!media) return state.timelinePlayheadSeconds || 0;
  const localElapsed = Math.max(0, Number(video?.currentTime || 0) - mediaTrimStart(media));
  return (media.start_seconds || 0) + localElapsed;
}


export function globalTimeFromAudio(track = combinedVoiceoverTrack(), audio = document.getElementById("studio-audio")) {
  if (!track || !audio?.src) return state.timelinePlayheadSeconds || 0;
  const duration = Math.max(0, Number(track.duration_seconds || state.timeline?.duration_seconds || 0));
  return clamp(Number(audio.currentTime || 0), 0, duration || Number(audio.currentTime || 0));
}


export function mediaTrimStart(item) {
  return Number(item?.source_ref?.trim_start_seconds || 0);
}


export function mediaTrimEnd(item) {
  const fallback = mediaTrimStart(item) + Math.max(0, (item?.end_seconds || 0) - (item?.start_seconds || 0));
  return Number(item?.source_ref?.trim_end_seconds || fallback);
}


export function trimStatusLabel(item) {
  const status = item?.source_ref?.trim_status || "";
  if (status === "trim_manual") return "Manual trim";
  if (status === "trim_short_loop") return "Short clip loop";
  if (status === "trim_stale") return "Stale trim";
  return item?.source_ref?.trim_source === "manual" ? "Manual trim" : "Auto-start";
}


export function timelineClipLabel(item) {
  if (item?.type === "media") return trimStatusLabel(item);
  if (item?.type === "icon") return callbacks.iconLabel(item.source_ref?.icon_id || "icon");
  if (item?.type === "overlay") return overlayLabel(callbacks.overlayIdForItem(item));
  if (item?.type === "music") return item.source_ref?.name || "Music";
  if (item?.type === "sfx") return item.source_ref?.label || callbacks.sfxAsset(item.source_ref?.asset_id)?.name || "SFX";
  if (item?.type === "transition") return transitionLabel(callbacks.transitionIdForItem(item));
  return itemLabel(item);
}


export function applyStudioMediaEffects(video, media) {
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


export function setStudioVideoTransform(video = document.getElementById("studio-video")) {
  if (!video) return;
  video.style.transform = `${video.dataset.baseTransform || ""} ${video.dataset.transitionTransform || ""}`.trim();
}


export function applyTransitionPreview(globalTime) {
  const stage = document.getElementById("studio-stage");
  const video = document.getElementById("studio-video");
  const nextVideo = document.getElementById("studio-next-video");
  if (!stage || !video || !nextVideo) return;
  if (callbacks.smoothPreviewActive()) {
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
  const requestedId = normalizedTransitionId(callbacks.transitionIdForItem(item));
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


export function transitionItemAtTime(globalTime) {
  return timelineItems().find((item) => item.type === "transition" && globalTime >= item.start_seconds && globalTime <= item.end_seconds) || null;
}


export function upcomingTransitionItem(globalTime) {
  return timelineItems()
    .filter((item) => item.type === "transition" && item.start_seconds > globalTime && item.start_seconds - globalTime <= TRANSITION_PRELOAD_MARGIN)
    .sort((a, b) => a.start_seconds - b.start_seconds)[0] || null;
}


export function nextMediaForTransition(transitionItem) {
  const mediaItems = timelineItems().filter((item) => item.type === "media").sort((a, b) => a.start_seconds - b.start_seconds);
  const index = mediaItems.findIndex((item) => item.scene_id === transitionItem.scene_id);
  return index >= 0 ? mediaItems[index + 1] || null : null;
}


export function normalizedTransitionId(id) {
  return {
    clean_cut: "fade",
    push_slide: "slide_left",
    speed_zoom: "zoom_in",
    fast_swipes: "whip_pan",
  }[id] || id || "fade";
}


export function easeInOutCubic(value) {
  const p = clamp(Number(value || 0), 0, 1);
  return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
}


export function syncTransitionNextVideo(nextVideo, nextMedia, options = {}) {
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


export function playBufferedVideo(video) {
  if (!video?.src || !video.paused) return;
  const promise = video.play();
  if (promise?.catch) promise.catch(() => {});
}


export function placeTimelineClip(clip, item) {
  if (!clip || !item) return;
  const metrics = callbacks.timelineMetrics();
  clip.style.left = `${Math.max(0, item.start_seconds * metrics.pxPerSecond)}px`;
  clip.style.width = `${Math.max(12, (item.end_seconds - item.start_seconds) * metrics.pxPerSecond)}px`;
}


export function updateTimelineClipActiveStates() {
  document.querySelectorAll(".vd-timeline-clip").forEach((clip) => {
    clip.dataset.active = clip.dataset.itemId === state.selectedItemId ? "true" : "false";
  });
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}


export function toggleStudioPlayback() {
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


export function playTimelineFrom(globalTime) {
  state.timelinePlaying = true;
  state.playedSfxIds.clear();
  callbacks.seekTimeline(globalTime, { autoplay: true });
  startTimelineFrameTicker();
  updateStudioPlaybackButton();
}


export function onStudioVideoTimeUpdate() {
  if (callbacks.smoothPreviewActive()) {
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


export function onStudioVideoEnded() {
  if (!state.timelinePlaying) return;
  if (callbacks.smoothPreviewActive()) {
    state.timelinePlaying = false;
    callbacks.seekTimeline(Math.max(0, state.timeline?.duration_seconds || 0));
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


export function onStudioAudioTimeUpdate() {
  if (!state.timelinePlaying || !combinedVoiceoverTrack()) return;
  syncTimelineToVoiceover(globalTimeFromAudio());
}


export function advanceTimelinePlayback(globalTime) {
  if (!state.timeline) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  if (globalTime >= duration - 0.01) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    callbacks.seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  callbacks.seekTimeline(globalTime, { autoplay: true });
}


export function syncTimelineToSmoothPreview() {
  const video = document.getElementById("studio-video");
  if (!state.timeline || !callbacks.smoothPreviewActive() || !video) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const time = clamp(Number(video.currentTime || 0), 0, duration);
  if (time >= duration - 0.03) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    callbacks.seekTimeline(duration);
    updateStudioPlaybackButton();
    return;
  }
  const media = mediaItemAtTime(time);
  if (media && state.selectedSceneId !== media.scene_id) {
    state.selectedSceneId = media.scene_id;
    if (!selectedItem() || selectedItem()?.scene_id !== media.scene_id) {
      state.selectedItemId = media.item_id;
    }
    callbacks.renderStudio();
  }
  updateStudioClock(time);
}


export function syncTimelineToVoiceover(globalTime) {
  if (!state.timeline || !combinedVoiceoverTrack()) return;
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  const time = clamp(Number(globalTime || 0), 0, duration);
  if (time >= duration - 0.03) {
    state.timelinePlaying = false;
    pauseStudioMedia();
    callbacks.seekTimeline(duration);
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
    callbacks.renderStudio();
  }
  syncStudioVideoToTimeline(time, {
    autoplay: true,
    tolerateDrift: true,
    skipAudioSync: true,
    videoDriftThreshold: sceneChanged ? 0.35 : 0.18,
  });
  updateStudioClock(time);
}


export function promoteTransitionBufferToPrimary(media) {
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


export function startTimelineFrameTicker() {
  if (timelineFrameRequest) return;
  const tick = () => {
    timelineFrameRequest = null;
    if (!state.timelinePlaying) return;
    if (callbacks.smoothPreviewActive()) syncTimelineToSmoothPreview();
    else if (combinedVoiceoverTrack()) syncTimelineToVoiceover(globalTimeFromAudio());
    else updateStudioClock();
    timelineFrameRequest = requestAnimationFrame(tick);
  };
  timelineFrameRequest = requestAnimationFrame(tick);
}


export function stopTimelineFrameTicker() {
  if (!timelineFrameRequest) return;
  cancelAnimationFrame(timelineFrameRequest);
  timelineFrameRequest = null;
}


export function updateStudioClock(forcedGlobalTime = null) {
  const media = currentMediaItem();
  const hasForcedTime = typeof forcedGlobalTime === "number" && Number.isFinite(forcedGlobalTime);
  const globalTime = hasForcedTime ? forcedGlobalTime : (callbacks.smoothPreviewActive() ? globalTimeFromVideo(media) : (combinedVoiceoverTrack() ? globalTimeFromAudio() : globalTimeFromVideo(media)));
  state.timelinePlayheadSeconds = clamp(globalTime, 0, Math.max(1, state.timeline?.duration_seconds || 1));
  callbacks.updateCaptionPreview(state.timelinePlayheadSeconds);
  applyTransitionPreview(state.timelinePlayheadSeconds);
  triggerRealtimeSfx(state.timelinePlayheadSeconds);
  const time = document.getElementById("studio-time");
  if (time) time.textContent = state.timeline ? `${formatDuration(state.timelinePlayheadSeconds)} / ${formatDuration(state.timeline.duration_seconds)}` : "0:00";
  updateTimelinePlayhead(state.timelinePlayheadSeconds);
}


export function triggerRealtimeSfx(globalTime) {
  if (!state.timelinePlaying || callbacks.smoothPreviewActive()) return;
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


export function playTimelineSfx(item) {
  const asset = callbacks.sfxAsset(item.source_ref?.asset_id);
  const url = asset?.audio_url || item.source_ref?.audio_url || "";
  if (!url) return;
  const audio = new Audio(url);
  audio.volume = clamp(Number(item.style?.volume ?? asset?.default_volume ?? 0.35), 0, 1);
  const promise = audio.play();
  if (promise?.catch) promise.catch(() => {});
}


export function updateTimelinePlayhead(globalTime) {
  const playhead = document.getElementById("timeline-playhead");
  if (!playhead) return;
  const duration = Math.max(1, state.timeline?.duration_seconds || 1);
  const metrics = callbacks.timelineMetrics(duration);
  const left = metrics.labelWidth + clamp(Number(globalTime || 0), 0, duration) * metrics.pxPerSecond;
  playhead.style.left = `${left}px`;
}


export function updateStudioPlaybackButton() {
  const video = document.getElementById("studio-video");
  const audio = document.getElementById("studio-audio");
  const music = document.getElementById("studio-music");
  const button = document.getElementById("studio-play");
  if (!button || !video) return;
  button.textContent = state.timelinePlaying || !video.paused || (audio?.src && !audio.paused) || (music?.src && !music.paused) ? "Pause" : "Play";
}
