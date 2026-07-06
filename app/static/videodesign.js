const state = {
  projectId: "",
  project: null,
  rows: [],
  timeline: null,
  activeView: "start",
  selectedSceneId: "",
  selectedItemId: "",
  selectedTool: "script",
  running: false,
  lastProgressMessage: "",
  preset: defaultPreset(),
};

let progressTimer = null;
let dragState = null;

const viewTitles = {
  start: "Create video",
  script: "Script creation",
  template: "Template setup",
  plan: "Scene plan",
  materials: "Material review",
  studio: "Studio timeline",
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();
  updateDurationLabel();
  navigate("start");
  restoreProject();
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.viewTarget));
  });

  document.getElementById("start-duration").addEventListener("input", updateDurationLabel);
  document.getElementById("create-project").addEventListener("click", createProject);
  document.getElementById("load-saved-project").addEventListener("click", () => {
    const projectId = localStorage.getItem("videodesignProjectId");
    if (projectId) loadProject(projectId, "script");
    else setStatus("No saved project found.", "error");
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

  document.getElementById("generate-tts").addEventListener("click", generateTts);
  document.getElementById("save-scene").addEventListener("click", saveSelectedScene);
  document.getElementById("split-scene").addEventListener("click", splitSelectedScene);
  document.getElementById("merge-prev-scene").addEventListener("click", mergePreviousScene);

  document.getElementById("search-current-scene").addEventListener("click", searchSelectedScene);
  document.getElementById("search-all-scenes").addEventListener("click", searchAllScenes);
  document.getElementById("download-approved").addEventListener("click", downloadApproved);

  document.getElementById("create-timeline").addEventListener("click", createTimeline);
  document.getElementById("studio-play").addEventListener("click", toggleStudioPlayback);
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTool = button.dataset.studioTool;
      renderStudio();
    });
  });

  document.getElementById("studio-text").addEventListener("pointerdown", startCanvasTextDrag);
  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", endPointerDrag);
}

async function restoreProject() {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("project_id") || localStorage.getItem("videodesignProjectId");
  if (projectId) await loadProject(projectId, params.get("view") || null);
}

async function createProject() {
  await run("Creating project", async () => {
    const prompt = document.getElementById("start-prompt").value.trim();
    if (!prompt) throw new Error("Add an idea or script first.");

    const looksLikeScript = wordCount(prompt) >= 35 || sentenceCount(prompt) > 1;
    const data = await api("/api/videodesign/projects", {
      method: "POST",
      body: {
        idea: looksLikeScript ? null : prompt,
        script: looksLikeScript ? prompt : null,
        target_platform: document.getElementById("start-platform").value,
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
    navigate("script");
  });
}

async function loadProject(projectId, preferredView = null) {
  await run("Loading project", async () => {
    const data = await api(`/api/videodesign/projects/${projectId}`);
    state.project = data.project;
    state.projectId = data.project.project_id;
    state.preset = mergePreset(defaultPreset(), state.project.design_preset || {});
    localStorage.setItem("videodesignProjectId", state.projectId);
    hydrateProjectFields();
    await loadReview();
    await loadTimeline();
    navigate(preferredView || (state.timeline ? "studio" : "script"));
  });
}

async function saveProjectPatch(patch) {
  const data = await api(`/api/videodesign/projects/${state.projectId}`, {
    method: "PATCH",
    body: patch,
  });
  state.project = data.project;
  hydrateProjectFields(false);
  return data.project;
}

async function generateScript() {
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
    await loadReview();
    setStatus("Script generated.", "idle");
  });
}

async function saveScript() {
  ensureProject();
  await run("Saving script", async () => {
    await saveProjectPatch({
      idea: document.getElementById("script-idea").value.trim(),
      script: document.getElementById("script-editor").value.trim(),
    });
    setStatus("Script saved.", "idle");
  });
}

async function parseScenes() {
  ensureProject();
  await run("Parsing scenes", async () => {
    await saveScript();
    await saveSplitSettings();
    await savePreset();
    await api(`/api/videodesign/projects/${state.projectId}/plan`, { method: "POST" });
    await loadReview();
    selectFirstScene();
    navigate("plan");
  });
}

async function saveSplitSettings() {
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

async function savePreset() {
  if (!state.projectId) return;
  state.preset.scene_media.candidate_count = Number(document.getElementById("preset-candidate-count").value || state.preset.scene_media.candidate_count);
  state.preset.scene_media.translate_to_chinese = document.getElementById("preset-translate").checked;
  state.preset.voiceover.provider = document.getElementById("tts-provider").value;
  state.preset.voiceover.voice_id = document.getElementById("voice-id").value.trim() || "en-US-AriaNeural";
  const data = await api(`/api/videodesign/projects/${state.projectId}/preset`, {
    method: "PATCH",
    body: state.preset,
  });
  state.project = data.project;
}

async function generateTts() {
  ensureProject();
  await run("Generating TTS timing", async () => {
    await savePreset();
    await api(`/api/videodesign/projects/${state.projectId}/tts/generate`, {
      method: "POST",
      body: {
        provider: state.preset.voiceover.provider,
        voice_id: state.preset.voiceover.voice_id,
      },
    });
    await loadReview();
    navigate("materials");
  });
}

async function loadReview() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/review`);
  state.rows = data.rows;
  if (!state.selectedSceneId || !state.rows.some((row) => row.scene.scene_id === state.selectedSceneId)) {
    selectFirstScene();
  }
  renderAll();
}

async function loadTimeline() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline`);
  state.timeline = data.timeline;
  if (state.timeline && !state.selectedItemId) {
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
  }
  renderAll();
}

async function saveSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Saving scene", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
      method: "PATCH",
      body: {
        voiceover_text: document.getElementById("scene-voiceover").value.trim(),
        tts_text: document.getElementById("scene-voiceover").value.trim(),
        caption_text: document.getElementById("scene-voiceover").value.trim(),
        on_screen_text: document.getElementById("scene-onscreen").value.trim(),
        visual_brief: document.getElementById("scene-visual").value.trim(),
        matching_keywords: document.getElementById("scene-keywords").value.split(",").map((item) => item.trim()).filter(Boolean),
      },
    });
    await loadReview();
  });
}

async function splitSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Splitting scene", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/split`, { method: "POST" });
    await loadReview();
  });
}

async function mergePreviousScene() {
  const row = selectedRow();
  const index = state.rows.findIndex((item) => item.scene.scene_id === row?.scene.scene_id);
  if (!row || index <= 0) return;
  await run("Merging scenes", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/merge`, {
      method: "POST",
      body: { scene_ids: [state.rows[index - 1].scene.scene_id, row.scene.scene_id] },
    });
    await loadReview();
  });
}

async function searchSelectedScene() {
  const row = selectedRow();
  if (!row) return;
  await run("Searching selected scene", async () => {
    const manualKeyword = document.getElementById("manual-keyword").value.trim();
    if (manualKeyword) {
      await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
        method: "PATCH",
        body: { matching_keywords: [manualKeyword, ...row.scene.matching_keywords.filter((item) => item !== manualKeyword)] },
      });
    }
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}/materials/search`, {
      method: "POST",
      body: materialSearchBody([row.scene.scene_id]),
    });
    await loadReview();
  });
}

async function searchAllScenes() {
  ensureProject();
  await run("Searching all scenes", async () => {
    startProgressPolling();
    try {
      await api(`/api/videodesign/projects/${state.projectId}/materials/search`, {
        method: "POST",
        body: materialSearchBody(),
      });
    } finally {
      stopProgressPolling();
    }
    await loadReview();
  });
}

async function approveCandidate(sceneId, candidateId) {
  await run("Approving candidate", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "approve", candidate_id: candidateId },
    });
    await loadReview();
  });
}

async function allowPlaceholder(sceneId) {
  await run("Allowing placeholder", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "placeholder" },
    });
    await loadReview();
  });
}

async function downloadApproved() {
  ensureProject();
  await run("Downloading approved videos", async () => {
    const sceneIds = state.rows
      .filter((row) => row.scene.selected_candidate_id && !row.scene.material_asset_id)
      .map((row) => row.scene.scene_id);
    if (!sceneIds.length) throw new Error("No approved scenes are waiting for download.");
    await api(`/api/videodesign/projects/${state.projectId}/materials/download`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    await loadReview();
  });
}

async function createTimeline() {
  ensureProject();
  await run("Creating Studio timeline", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/studio`, { method: "POST" });
    state.timeline = data.timeline;
    const firstText = state.timeline.items.find((item) => item.type === "text");
    state.selectedItemId = firstText?.item_id || state.timeline.items[0]?.item_id || "";
    renderStudio();
  });
}

function materialSearchBody(sceneIds = null) {
  return {
    scene_ids: sceneIds,
    candidates_per_scene: Number(document.getElementById("candidate-count").value || state.preset.scene_media.candidate_count || 4),
    queries_per_scene: 1,
    translate_to_chinese: document.getElementById("translate-query").checked,
  };
}

function navigate(view) {
  if (!view) return;
  if (view !== "start" && !state.projectId) {
    setStatus("Create or load a project first.", "error");
    view = "start";
  }
  state.activeView = view;
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
  renderSummaryRails();
  renderSceneRails();
  renderSceneEditor();
  renderCandidateBoard();
  renderStudio();
  updateScriptMetrics();
}

function renderProjectChip() {
  const chip = document.getElementById("vd-project-chip");
  chip.textContent = state.projectId ? state.projectId : "No project";
}

function renderSummaryRails() {
  const html = `
    <h3>Your video</h3>
    ${summaryRow("Format", state.preset.format.aspect_ratio)}
    ${summaryRow("Template", templateLabel(state.preset.template.template_id))}
    ${summaryRow("Scene media", mediaLabel(state.preset.scene_media.media_source))}
    ${summaryRow("Voiceover", `${state.preset.voiceover.provider} - ${state.preset.voiceover.voice_id}`)}
    ${summaryRow("Captions", state.preset.captions.style_id.replaceAll("_", " "))}
    ${summaryRow("Extras", state.preset.extras.transition_pack_id.replaceAll("_", " "))}
    <button class="vd-primary" data-summary-action="save-template" type="button">Save preset and continue</button>
  `;
  document.querySelectorAll(".vd-summary-rail").forEach((rail) => {
    rail.innerHTML = html;
    rail.querySelector("[data-summary-action='save-template']").addEventListener("click", async () => {
      await run("Saving preset", async () => {
        await savePreset();
        if (!state.rows.length) await parseScenes();
        else navigate("plan");
      });
    });
  });
}

function summaryRow(label, value) {
  return `<div class="vd-summary-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not set")}</strong></div>`;
}

function renderSceneRails() {
  const html = state.rows.length ? state.rows.map((row) => sceneRailButton(row)).join("") : `<div class="vd-empty">No scenes yet. Parse the script first.</div>`;
  document.getElementById("plan-scene-rail").innerHTML = html;
  document.getElementById("materials-scene-rail").innerHTML = html;
  document.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      renderAll();
    });
  });
}

function sceneRailButton(row) {
  const active = row.scene.scene_id === state.selectedSceneId ? "true" : "false";
  return `
    <button class="vd-scene-pill" data-scene-id="${row.scene.scene_id}" data-active="${active}" type="button">
      <span>Scene ${row.scene.order}</span>
      <strong>${escapeHtml(row.scene.on_screen_text || row.scene.voiceover_text || "Untitled")}</strong>
      <em>${escapeHtml(row.scene.approval_state)} / ${row.candidates.length} candidates</em>
    </button>
  `;
}

function renderSceneEditor() {
  const row = selectedRow();
  document.getElementById("plan-scene-title").textContent = row ? `Scene ${row.scene.order}` : "Select a scene";
  document.getElementById("scene-voiceover").value = row?.scene.voiceover_text || "";
  document.getElementById("scene-onscreen").value = row?.scene.on_screen_text || "";
  document.getElementById("scene-visual").value = row?.scene.visual_brief || "";
  document.getElementById("scene-keywords").value = row?.scene.matching_keywords?.join(", ") || "";
}

function renderCandidateBoard() {
  const row = selectedRow();
  const board = document.getElementById("candidate-board");
  document.getElementById("materials-scene-title").textContent = row ? `Scene ${row.scene.order}: ${row.scene.approval_state}` : "Select a scene";
  if (!row) {
    board.innerHTML = `<div class="vd-empty">Select a scene to review candidates.</div>`;
    return;
  }
  document.getElementById("manual-keyword").value = document.getElementById("manual-keyword").value || row.scene.matching_keywords[0] || "";
  if (!row.candidates.length) {
    board.innerHTML = `
      <div class="vd-empty">
        <h3>No candidates yet</h3>
        <p>Search this scene or allow a placeholder before Studio.</p>
        <button data-placeholder-scene="${row.scene.scene_id}" type="button">Allow placeholder</button>
      </div>
    `;
  } else {
    board.innerHTML = row.candidates.map((candidate) => `
      <article class="vd-candidate ${candidate.status === "approved" ? "is-approved" : ""}">
        <img src="${candidate.cover_url}" alt="">
        <div>
          <h3>${escapeHtml(candidate.title || candidate.douyin_aweme_id)}</h3>
          <p>${escapeHtml(candidate.match_reason)} Score ${candidate.score}</p>
          <p>${formatDuration(candidate.duration)} / ${escapeHtml(candidate.douyin_aweme_id)}</p>
          <div class="vd-button-row">
            <button data-approve-candidate="${candidate.candidate_id}" data-approve-scene="${row.scene.scene_id}" type="button">${candidate.status === "approved" ? "Approved" : "Approve"}</button>
            <a href="${candidate.stream_url}" target="_blank" rel="noreferrer">Preview stream</a>
          </div>
        </div>
      </article>
    `).join("");
  }
  board.querySelectorAll("[data-approve-candidate]").forEach((button) => {
    button.addEventListener("click", () => approveCandidate(button.dataset.approveScene, button.dataset.approveCandidate));
  });
  board.querySelectorAll("[data-placeholder-scene]").forEach((button) => {
    button.addEventListener("click", () => allowPlaceholder(button.dataset.placeholderScene));
  });
}

function renderStudio() {
  renderStudioToolPanel();
  renderStudioStage();
  renderTimeline();
  document.querySelectorAll("[data-studio-tool]").forEach((button) => {
    button.dataset.active = button.dataset.studioTool === state.selectedTool ? "true" : "false";
  });
}

function renderStudioToolPanel() {
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
    const item = selectedItem();
    panel.innerHTML = `
      <h3>Text overlay</h3>
      <label>Text <input id="studio-text-input" value="${escapeHtml(textForItem(item))}"></label>
      <p class="vd-muted">Drag the text directly on the preview canvas.</p>
      <button id="save-studio-text" type="button">Save text</button>
    `;
    panel.querySelector("#save-studio-text")?.addEventListener("click", () => saveStudioText());
  } else if (state.selectedTool === "media") {
    panel.innerHTML = `<h3>Media</h3><p>${row ? `Scene ${row.scene.order}` : "Select a scene"}</p><button data-view-target="materials" type="button">Return to materials</button>`;
    panel.querySelector("[data-view-target]")?.addEventListener("click", () => navigate("materials"));
  } else {
    panel.innerHTML = `<h3>${escapeHtml(titleCase(state.selectedTool))}</h3><p class="vd-muted">Controls for this tool will build on the selected timeline item.</p>`;
  }
  panel.querySelectorAll("[data-scene-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedSceneId = button.dataset.sceneId;
      selectFirstItemForScene(button.dataset.sceneId);
      renderStudio();
    });
  });
}

function renderStudioStage() {
  const row = selectedRow();
  const media = timelineItems().find((item) => item.type === "media" && item.scene_id === row?.scene.scene_id);
  const text = timelineItems().find((item) => item.type === "text" && item.scene_id === row?.scene.scene_id);
  const caption = timelineItems().find((item) => item.type === "caption" && item.scene_id === row?.scene.scene_id);
  const video = document.getElementById("studio-video");
  const captionEl = document.getElementById("studio-caption");
  const textEl = document.getElementById("studio-text");

  if (media?.source_ref?.media_url && video.getAttribute("src") !== media.source_ref.media_url) {
    video.src = media.source_ref.media_url;
    video.load();
  }
  if (!media?.source_ref?.media_url) video.removeAttribute("src");

  const chunks = caption?.source_ref?.caption_chunks || row?.scene.caption_chunks || [];
  captionEl.textContent = chunks.map((chunk) => chunk.text).join(" ") || row?.scene.caption_text || "";
  textEl.textContent = textForItem(text) || row?.scene.on_screen_text || "";
  textEl.dataset.itemId = text?.item_id || "";
  const transform = text?.transform || { x: 50, y: 18 };
  textEl.style.left = `${Number(transform.x ?? 50)}%`;
  textEl.style.top = `${Number(transform.y ?? 18)}%`;
}

function renderTimeline() {
  const ruler = document.getElementById("timeline-ruler");
  const tracks = document.getElementById("timeline-tracks");
  if (!state.timeline) {
    ruler.innerHTML = "";
    tracks.innerHTML = `<div class="vd-empty">Create a Studio timeline after videos are downloaded.</div>`;
    return;
  }
  const duration = Math.max(1, state.timeline.duration_seconds || 1);
  ruler.innerHTML = [0, 25, 50, 75, 100].map((tick) => `<span style="left:${tick}%">${Math.round(duration * tick / 100)}s</span>`).join("");
  tracks.innerHTML = state.timeline.layers.map((layer) => {
    const items = state.timeline.items.filter((item) => item.layer_id === layer);
    return `
      <div class="vd-track">
        <div class="vd-track-name">${escapeHtml(layer.replaceAll("_", " "))}</div>
        <div class="vd-track-lane" data-track-layer="${layer}">
          ${items.map((item) => timelineClip(item, duration)).join("")}
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
      if (item?.type === "text") state.selectedTool = "text";
      renderStudio();
    });
    clip.addEventListener("pointerdown", startTimelineDrag);
  });
}

function timelineClip(item, duration) {
  const left = Math.max(0, Math.min(100, (item.start_seconds / duration) * 100));
  const width = Math.max(2, Math.min(100 - left, ((item.end_seconds - item.start_seconds) / duration) * 100));
  const active = item.item_id === state.selectedItemId ? "true" : "false";
  return `
    <button class="vd-timeline-clip" data-item-id="${item.item_id}" data-type="${item.type}" data-active="${active}" style="left:${left}%;width:${width}%;" type="button">
      <span class="vd-resize-handle" data-edge="left"></span>
      ${escapeHtml(item.type)}
      <span class="vd-resize-handle" data-edge="right"></span>
    </button>
  `;
}

async function saveStudioText() {
  const item = selectedItem();
  if (!item || item.type !== "text") return;
  item.source_ref = { ...(item.source_ref || {}), text: document.getElementById("studio-text-input").value.trim() };
  await patchTimelineItem(item.item_id, { source_ref: item.source_ref });
}

function startCanvasTextDrag(event) {
  const item = selectedItem();
  if (!item || item.type !== "text") return;
  event.preventDefault();
  const rect = document.getElementById("studio-stage").getBoundingClientRect();
  dragState = {
    kind: "canvas-text",
    itemId: item.item_id,
    rect,
  };
}

function startTimelineDrag(event) {
  const item = state.timeline?.items.find((entry) => entry.item_id === event.currentTarget.dataset.itemId);
  if (!item || !["text", "media"].includes(item.type)) return;
  event.preventDefault();
  const lane = event.currentTarget.closest(".vd-track-lane");
  dragState = {
    kind: "timeline",
    itemId: item.item_id,
    edge: event.target.dataset.edge || "move",
    startX: event.clientX,
    laneWidth: lane.getBoundingClientRect().width,
    timelineDuration: Math.max(1, state.timeline.duration_seconds || 1),
    originalStart: item.start_seconds,
    originalEnd: item.end_seconds,
  };
}

function onPointerMove(event) {
  if (!dragState) return;
  if (dragState.kind === "canvas-text") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const x = clamp(((event.clientX - dragState.rect.left) / dragState.rect.width) * 100, 0, 100);
    const y = clamp(((event.clientY - dragState.rect.top) / dragState.rect.height) * 100, 0, 100);
    item.transform = { ...(item.transform || {}), x: Math.round(x), y: Math.round(y) };
    renderStudioStage();
  }
  if (dragState.kind === "timeline") {
    const item = state.timeline.items.find((entry) => entry.item_id === dragState.itemId);
    if (!item) return;
    const deltaSeconds = ((event.clientX - dragState.startX) / dragState.laneWidth) * dragState.timelineDuration;
    const snap = (value) => Math.round(value * 10) / 10;
    if (dragState.edge === "left") {
      item.start_seconds = snap(clamp(dragState.originalStart + deltaSeconds, 0, item.end_seconds - 0.5));
    } else if (dragState.edge === "right") {
      item.end_seconds = snap(Math.max(item.start_seconds + 0.5, dragState.originalEnd + deltaSeconds));
    } else {
      const duration = dragState.originalEnd - dragState.originalStart;
      const nextStart = snap(Math.max(0, dragState.originalStart + deltaSeconds));
      item.start_seconds = nextStart;
      item.end_seconds = snap(nextStart + duration);
    }
    renderTimeline();
  }
}

async function endPointerDrag() {
  if (!dragState) return;
  const item = state.timeline?.items.find((entry) => entry.item_id === dragState.itemId);
  const patch = item ? { start_seconds: item.start_seconds, end_seconds: item.end_seconds, transform: item.transform } : null;
  dragState = null;
  if (item && patch) await patchTimelineItem(item.item_id, patch);
}

async function patchTimelineItem(itemId, patch) {
  const data = await api(`/api/videodesign/projects/${state.projectId}/timeline/items/${itemId}`, {
    method: "PATCH",
    body: patch,
  });
  const index = state.timeline.items.findIndex((item) => item.item_id === itemId);
  if (index >= 0) state.timeline.items[index] = data.item;
  renderStudio();
}

function setPresetChoice(button) {
  const peers = button.parentElement.querySelectorAll(`[data-preset-path="${button.dataset.presetPath}"]`);
  peers.forEach((peer) => peer.classList.remove("is-selected"));
  button.classList.add("is-selected");
  setByPath(state.preset, button.dataset.presetPath, button.dataset.presetValue);
  renderSummaryRails();
}

function setTemplateChoice(button) {
  document.querySelectorAll("[data-template-id]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.template.template_id = button.dataset.templateId;
  state.preset.template.template_category = "dynamic_template";
  renderSummaryRails();
}

function setCaptionStyle(button) {
  document.querySelectorAll("[data-caption-style]").forEach((item) => item.classList.remove("is-selected"));
  button.classList.add("is-selected");
  state.preset.captions.style_id = button.dataset.captionStyle;
  renderSummaryRails();
}

async function run(label, handler) {
  try {
    state.running = true;
    setStatus(label, "running");
    await handler();
    setStatus("Ready", "idle");
  } catch (error) {
    setStatus(error.message || String(error), "error");
  } finally {
    state.running = false;
    renderAll();
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json();
  if (!data.success) {
    throw new Error(`${data.error.code}: ${data.error.message}`);
  }
  return data;
}

function startProgressPolling() {
  stopProgressPolling();
  state.lastProgressMessage = "";
  progressTimer = window.setInterval(pollProgress, 2000);
  pollProgress();
}

function stopProgressPolling() {
  if (progressTimer) window.clearInterval(progressTimer);
  progressTimer = null;
}

async function pollProgress() {
  if (!state.projectId) return;
  try {
    const data = await api(`/api/videodesign/projects/${state.projectId}/progress`);
    const progress = data.progress;
    if (!progress?.message) return;
    document.getElementById("search-progress").textContent = `${progress.current}/${progress.total} ${progress.message}`;
    if (progress.message !== state.lastProgressMessage) {
      state.lastProgressMessage = progress.message;
      setStatus(progress.message, progress.stage === "idle" ? "idle" : "running");
    }
  } catch {
    return;
  }
}

function hydrateProjectFields(updateInputs = true) {
  if (!state.project || !updateInputs) return;
  document.getElementById("script-idea").value = state.project.idea || "";
  document.getElementById("script-editor").value = state.project.script || "";
  if (state.project.split_settings) {
    document.getElementById("split-mode").value = state.project.split_settings.split_mode || "normal";
    document.getElementById("max-words").value = state.project.split_settings.max_words_per_scene || 18;
    document.getElementById("scene-seconds").value = state.project.split_settings.target_scene_duration_seconds || 4;
  }
  document.getElementById("tts-provider").value = state.preset.voiceover.provider || "timing_only";
  document.getElementById("voice-id").value = state.preset.voiceover.voice_id || "en-US-AriaNeural";
  document.getElementById("preset-candidate-count").value = state.preset.scene_media.candidate_count || 4;
  document.getElementById("preset-translate").checked = Boolean(state.preset.scene_media.translate_to_chinese);
}

function updateDurationLabel() {
  const value = document.getElementById("start-duration").value;
  document.getElementById("start-duration-label").textContent = `${value} seconds`;
}

function updateScriptMetrics() {
  const text = document.getElementById("script-editor")?.value || "";
  const words = wordCount(text);
  const seconds = Math.max(2, Math.round(words / 2.6));
  const scenes = Math.max(0, sentenceCount(text));
  const metrics = document.getElementById("script-metrics");
  if (metrics) metrics.textContent = `${words} words / ${formatDuration(seconds)} / ${scenes} scenes`;
}

function selectFirstScene() {
  state.selectedSceneId = state.rows[0]?.scene.scene_id || "";
}

function selectFirstItemForScene(sceneId) {
  const item = timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === "text") || timelineItems().find((entry) => entry.scene_id === sceneId);
  state.selectedItemId = item?.item_id || "";
}

function selectedRow() {
  return state.rows.find((row) => row.scene.scene_id === state.selectedSceneId) || null;
}

function selectedItem() {
  return timelineItems().find((item) => item.item_id === state.selectedItemId) || null;
}

function timelineItems() {
  return state.timeline?.items || [];
}

function toggleStudioPlayback() {
  const video = document.getElementById("studio-video");
  if (!video.src) return;
  if (video.paused) video.play();
  else video.pause();
}

function ensureProject() {
  if (!state.projectId) throw new Error("Create or load a project first.");
}

function setStatus(message, mode) {
  const status = document.getElementById("vd-status");
  status.textContent = message;
  status.dataset.mode = mode;
}

function defaultPreset() {
  return {
    format: { aspect_ratio: "9:16", platform: "tiktok", target_duration_seconds: 45 },
    template: { template_id: "dynamic_short", template_category: "dynamic_template", scene_pacing: "normal" },
    scene_media: { media_source: "douyin_stock", candidate_count: 4, translate_to_chinese: true },
    voiceover: { provider: "timing_only", voice_id: "en-US-AriaNeural", language: "en" },
    captions: { enabled: true, style_id: "bold_outline", position: "bottom_safe", animation_id: "word_reveal" },
    extras: { transition_pack_id: "fast_swipes", overlay_pack_id: "clean_shadow", icon_pack_id: "arrows_shapes_basic" },
  };
}

function mergePreset(base, source) {
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

function setByPath(target, path, value) {
  const parts = path.split(".");
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    cursor[part] = cursor[part] || {};
    cursor = cursor[part];
  }
  cursor[parts.at(-1)] = value;
}

function templateLabel(value) {
  return {
    dynamic_short: "Dynamic Short",
    explainer_clean: "Explainer",
    quote_motivation: "Motivation",
  }[value] || value;
}

function mediaLabel(value) {
  return {
    douyin_stock: "Douyin stock",
    uploads: "Uploads",
    placeholder: "Placeholder",
  }[value] || value;
}

function textForItem(item) {
  return item?.source_ref?.text || "";
}

function titleCase(value) {
  return String(value).slice(0, 1).toUpperCase() + String(value).slice(1);
}

function wordCount(text) {
  return String(text || "").trim().split(/\s+/).filter(Boolean).length;
}

function sentenceCount(text) {
  return String(text || "").split(/[.!?]+/).map((part) => part.trim()).filter(Boolean).length;
}

function formatDuration(seconds) {
  const value = Number(seconds || 0);
  const mins = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}
