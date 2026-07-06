const statusEl = document.getElementById("status");
const reviewEl = document.getElementById("review");
const timelineEl = document.getElementById("timeline");
const stepperEl = document.getElementById("stepper");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const activityLog = document.getElementById("activity-log");

const steps = [
  ["create", "Create"],
  ["script", "Script"],
  ["plan", "Plan"],
  ["tts", "TTS"],
  ["search", "Search"],
  ["review", "Review"],
  ["download", "Download"],
  ["studio", "Studio"],
];

const state = {
  projectId: "",
  completed: new Set(),
  rows: [],
  timeline: null,
  running: "",
  lastProgressMessage: "",
};
let progressTimer = null;

const actions = {
  "create": createProject,
  "generate-script": generateScript,
  "use-script": useCurrentScript,
  "plan": planScenes,
  "tts": generateTts,
  "search-materials": searchMaterials,
  "download": downloadApproved,
  "studio": createStudio,
};

for (const [id, handler] of Object.entries(actions)) {
  document.getElementById(id).addEventListener("click", handler);
}

renderStepper();
setStatus("Ready", "idle");
logActivity("Ready to create a video design project.");
updateUi();
restoreProject();

async function createProject() {
  await runStep("create", "Creating project", async () => {
    const script = document.getElementById("script").value.trim();
    const idea = document.getElementById("idea").value.trim();
    const data = await api("/api/videodesign/projects", {
      method: "POST",
      body: {
        script: script || null,
        idea: idea || null,
        target_platform: document.getElementById("target-platform").value,
        target_duration_seconds: Number(document.getElementById("target-duration").value || 45),
        language: "en",
      },
    });
    state.projectId = data.project.project_id;
    localStorage.setItem("videodesignProjectId", state.projectId);
    await saveSplitSettings();
    state.rows = [];
    state.timeline = null;
    renderStudio(null);
    logActivity(`Created project ${state.projectId}.`);
  });
}

async function generateScript() {
  await runStep("script", "Generating script with DeepSeek", async () => {
    ensureProject();
    const data = await api(`/api/videodesign/projects/${state.projectId}/script/generate`, {
      method: "POST",
      body: {
        idea: document.getElementById("idea").value.trim(),
        target_duration_seconds: Number(document.getElementById("target-duration").value || 45),
        language: "en",
      },
    });
    document.getElementById("script").value = data.project.script;
    await renderReview();
    logActivity("DeepSeek script generated.");
  });
}

async function useCurrentScript() {
  await runStep("script", "Marking script ready", async () => {
    ensureProject();
    logActivity("Using the current script without DeepSeek regeneration.");
  });
}

async function planScenes() {
  await runStep("plan", "Planning scenes", async () => {
    ensureProject();
    await saveSplitSettings();
    await api(`/api/videodesign/projects/${state.projectId}/plan`, { method: "POST" });
    await renderReview();
    logActivity(`Planned ${state.rows.length} scenes.`);
  });
}

async function generateTts() {
  await runStep("tts", "Generating TTS timing", async () => {
    ensureProject();
    await api(`/api/videodesign/projects/${state.projectId}/tts/generate`, {
      method: "POST",
      body: {
        provider: document.getElementById("tts-provider").value,
        voice_id: document.getElementById("voice-id").value.trim() || "en-US-AriaNeural",
      },
    });
    await renderReview();
    logActivity("Generated voice timing and caption chunks.");
  });
}

async function searchMaterials() {
  await runStep("search", "Searching Douyin per scene", async () => {
    ensureProject();
    startProgressPolling();
    try {
      await api(`/api/videodesign/projects/${state.projectId}/materials/search`, {
        method: "POST",
        body: {
          candidates_per_scene: Number(document.getElementById("candidate-count").value || 4),
          queries_per_scene: Number(document.getElementById("query-count").value || 1),
          translate_to_chinese: true,
        },
      });
    } finally {
      stopProgressPolling();
    }
    await renderReview();
    logActivity("Douyin search completed for planned scenes.");
  });
  setStepDone("review", hasApprovedScene());
}

async function downloadApproved() {
  await runStep("download", "Downloading approved videos", async () => {
    ensureProject();
    await api(`/api/videodesign/projects/${state.projectId}/materials/download`, { method: "POST", body: {} });
    await renderReview();
    logActivity("Downloaded approved scene videos into material assets.");
  });
}

async function createStudio() {
  await runStep("studio", "Creating studio timeline", async () => {
    ensureProject();
    const data = await api(`/api/videodesign/projects/${state.projectId}/studio`, { method: "POST" });
    state.timeline = data.timeline;
    renderStudio(data.timeline);
    logActivity("Studio timeline created.");
  });
}

async function restoreProject() {
  const params = new URLSearchParams(window.location.search);
  const savedProjectId = params.get("project_id") || localStorage.getItem("videodesignProjectId");
  if (!savedProjectId || state.projectId) return;
  state.projectId = savedProjectId;
  try {
    setStatus("Loading saved project", "running");
    await renderReview();
    const data = await api(`/api/videodesign/projects/${state.projectId}/timeline`);
    if (data.timeline) {
      state.timeline = data.timeline;
      renderStudio(data.timeline);
      state.completed.add("studio");
    }
    state.completed.add("create");
    if (state.rows.length) {
      state.completed.add("script");
      state.completed.add("plan");
      state.completed.add("tts");
      if (state.rows.some((row) => row.candidates.length || row.scene.material_asset_id)) {
        state.completed.add("search");
      }
      if (state.rows.some((row) => row.scene.selected_candidate_id || row.scene.material_asset_id)) {
        state.completed.add("review");
      }
      if (allScenesDownloaded()) {
        state.completed.add("download");
      }
    }
    localStorage.setItem("videodesignProjectId", state.projectId);
    setStatus("Ready", "idle");
    logActivity(`Loaded project ${state.projectId}.`);
  } catch (error) {
    localStorage.removeItem("videodesignProjectId");
    state.projectId = "";
    setStatus("Ready", "idle");
    logActivity("Saved project was not available on this server run.");
  } finally {
    updateUi();
  }
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

async function renderReview() {
  const data = await api(`/api/videodesign/projects/${state.projectId}/review`);
  state.rows = data.rows;
  if (!state.rows.length) {
    reviewEl.className = "review-empty";
    reviewEl.textContent = "No scenes yet. Plan scenes to continue.";
    updateFacts();
    updateUi();
    return;
  }

  reviewEl.className = "";
  reviewEl.innerHTML = state.rows.map((row) => `
    <div class="scene-review" data-state="${row.scene.approval_state}">
      <div class="scene-summary">
        <div>
          <span class="scene-kicker">Scene ${row.scene.order}</span>
          <h3>${escapeHtml(row.scene.on_screen_text || `Scene ${row.scene.order}`)}</h3>
          <p>${escapeHtml(row.scene.voiceover_text)}</p>
        </div>
        <span class="scene-status">${escapeHtml(row.scene.approval_state)}</span>
      </div>
      <div class="scene-meta">
        <span>${formatDuration(row.scene.duration_seconds)}</span>
        <span>${row.candidates.length} candidates</span>
        <span>${row.scene.material_asset_id ? "downloaded" : "not downloaded"}</span>
      </div>
      <div class="candidate-grid">
        ${row.candidates.map((candidate) => `
          <article class="candidate ${candidate.status === "approved" ? "is-approved" : ""}">
            <img src="${candidate.cover_url}" alt="">
            <div class="candidate-body">
              <strong>${escapeHtml(candidate.title || candidate.douyin_aweme_id)}</strong>
              <p class="meta">${formatDuration(candidate.duration)} / score ${candidate.score}</p>
              <p>${escapeHtml(candidate.match_reason)}</p>
              <button data-scene="${row.scene.scene_id}" data-candidate="${candidate.candidate_id}">
                ${candidate.status === "approved" ? "Approved" : "Approve"}
              </button>
            </div>
          </article>
        `).join("")}
      </div>
    </div>
  `).join("");

  reviewEl.querySelectorAll("button[data-candidate]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runInline("Approving candidate", async () => {
        await api(`/api/videodesign/projects/${state.projectId}/scenes/${button.dataset.scene}/selection`, {
          method: "PATCH",
          body: { action: "approve", candidate_id: button.dataset.candidate },
        });
        await renderReview();
        state.completed.add("review");
        logActivity(`Approved video for scene ${button.dataset.scene.slice(0, 8)}.`);
      });
    });
  });

  setStepDone("review", hasApprovedScene());
  updateFacts();
  updateUi();
}

function renderStudio(timeline) {
  if (!timeline) {
    timelineEl.className = "studio-empty";
    timelineEl.textContent = "Timeline preview will appear after studio creation.";
    return;
  }

  const duration = timeline.duration_seconds || 1;
  const mediaItems = timeline.items.filter((item) => item.type === "media");
  const layerNames = timeline.layers.length ? timeline.layers : Array.from(new Set(timeline.items.map((item) => item.layer_id)));

  timelineEl.className = "studio-panel";
  timelineEl.innerHTML = `
    <div class="studio-layout">
      <div class="studio-stage" data-aspect="${escapeHtml(timeline.aspect_ratio)}">
        <video id="studio-video" controls playsinline></video>
        <div id="studio-caption" class="studio-caption"></div>
        <div id="studio-text" class="studio-text"></div>
      </div>
      <div class="studio-inspector">
        <h3>Studio Timeline</h3>
        <dl>
          <dt>Duration</dt>
          <dd>${formatDuration(duration)}</dd>
          <dt>Scenes</dt>
          <dd>${timeline.scenes.length}</dd>
          <dt>Layers</dt>
          <dd>${layerNames.length}</dd>
        </dl>
        <div id="studio-scene-list" class="studio-scene-list"></div>
      </div>
    </div>
    <div class="timeline-ruler">
      ${[0, 25, 50, 75, 100].map((tick) => `<span style="left:${tick}%">${Math.round(duration * tick / 100)}s</span>`).join("")}
    </div>
    <div class="timeline-tracks">
      ${layerNames.map((layer) => renderTimelineLayer(layer, timeline.items, duration)).join("")}
    </div>
    <details class="timeline-json">
      <summary>Timeline JSON</summary>
      <pre>${escapeHtml(JSON.stringify(timeline, null, 2))}</pre>
    </details>
  `;

  const sceneList = document.getElementById("studio-scene-list");
  sceneList.innerHTML = mediaItems.map((item, index) => {
    const row = state.rows.find((entry) => entry.scene.scene_id === item.scene_id);
    const label = row ? `Scene ${row.scene.order}` : `Scene ${index + 1}`;
    return `<button data-studio-scene="${item.scene_id}">${escapeHtml(label)}</button>`;
  }).join("");

  document.querySelectorAll("[data-studio-scene]").forEach((button) => {
    button.addEventListener("click", () => selectStudioScene(timeline, button.dataset.studioScene));
  });
  document.querySelectorAll("[data-timeline-scene]").forEach((button) => {
    button.addEventListener("click", () => selectStudioScene(timeline, button.dataset.timelineScene));
  });

  if (mediaItems.length) {
    selectStudioScene(timeline, mediaItems[0].scene_id);
  }
}

function renderTimelineLayer(layer, items, duration) {
  const clips = items.filter((item) => item.layer_id === layer);
  return `
    <div class="timeline-layer">
      <div class="timeline-layer-name">${escapeHtml(layer.replaceAll("_", " "))}</div>
      <div class="timeline-layer-clips">
        ${clips.map((item) => {
          const left = Math.max(0, Math.min(100, (item.start_seconds / duration) * 100));
          const width = Math.max(2, Math.min(100 - left, ((item.end_seconds - item.start_seconds) / duration) * 100));
          return `
            <button class="timeline-clip" data-type="${escapeHtml(item.type)}" data-timeline-scene="${item.scene_id}" style="left:${left}%;width:${width}%">
              ${escapeHtml(item.type)}
            </button>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function selectStudioScene(timeline, sceneId) {
  const media = timeline.items.find((item) => item.type === "media" && item.scene_id === sceneId);
  const caption = timeline.items.find((item) => item.type === "caption" && item.scene_id === sceneId);
  const text = timeline.items.find((item) => item.type === "text" && item.scene_id === sceneId);
  const row = state.rows.find((entry) => entry.scene.scene_id === sceneId);
  const video = document.getElementById("studio-video");
  const captionEl = document.getElementById("studio-caption");
  const textEl = document.getElementById("studio-text");

  if (media?.source_ref?.media_url && video.getAttribute("src") !== media.source_ref.media_url) {
    video.src = media.source_ref.media_url;
    video.load();
  }
  const captionChunks = caption?.source_ref?.caption_chunks || row?.scene?.caption_chunks || [];
  captionEl.textContent = captionChunks.map((chunk) => chunk.text).join(" ") || row?.scene?.caption_text || "";
  textEl.textContent = text?.source_ref?.text || row?.scene?.on_screen_text || "";

  document.querySelectorAll("[data-studio-scene], [data-timeline-scene]").forEach((button) => {
    button.dataset.active = button.dataset.studioScene === sceneId || button.dataset.timelineScene === sceneId ? "true" : "false";
  });
}

async function runStep(stepId, label, handler) {
  try {
    state.running = stepId;
    setStepState(stepId, "running");
    setStatus(label, "running");
    updateUi();
    await handler();
    state.completed.add(stepId);
    setStepState(stepId, "done");
    setStatus("Ready", "idle");
  } catch (error) {
    setStepState(stepId, "error");
    setStatus(error.message, "error");
    logActivity(error.message);
  } finally {
    state.running = "";
    updateUi();
  }
}

async function runInline(label, handler) {
  try {
    setStatus(label, "running");
    await handler();
    setStatus("Ready", "idle");
  } catch (error) {
    setStatus(error.message, "error");
    logActivity(error.message);
  } finally {
    updateUi();
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
  pollProgress();
  progressTimer = window.setInterval(pollProgress, 2000);
}

function stopProgressPolling() {
  if (progressTimer) {
    window.clearInterval(progressTimer);
    progressTimer = null;
  }
}

async function pollProgress() {
  if (!state.projectId || state.running !== "search") return;
  try {
    const data = await api(`/api/videodesign/projects/${state.projectId}/progress`);
    const progress = data.progress;
    if (!progress || !progress.message) return;

    const mode = progress.stage === "idle" ? "idle" : "running";
    setStatus(progress.message, mode);
    if (progress.total) {
      progressLabel.textContent = `Search ${progress.current}/${progress.total} scenes`;
    }
    if (progress.message !== state.lastProgressMessage) {
      state.lastProgressMessage = progress.message;
      logActivity(progress.message);
    }
  } catch (error) {
    // Progress polling is best-effort; the main search request owns errors.
  }
}

function renderStepper() {
  stepperEl.innerHTML = steps.map(([id, label], index) => `
    <div class="step-pill" data-step="${id}">
      <span>${index + 1}</span>
      <strong>${label}</strong>
    </div>
  `).join("");
}

function updateUi() {
  for (const [id] of steps) {
    const stateName = state.completed.has(id) ? "done" : state.running === id ? "running" : "waiting";
    setStepState(id, stateName);
  }

  const completeCount = state.completed.size;
  progressFill.style.width = `${Math.round((completeCount / steps.length) * 100)}%`;
  progressLabel.textContent = `${completeCount}/${steps.length} steps complete`;

  const hasProject = Boolean(state.projectId);
  setDisabled("generate-script", !hasProject || state.running);
  setDisabled("use-script", !hasProject || state.running);
  setDisabled("plan", !hasProject || !state.completed.has("script") || state.running);
  setDisabled("tts", !hasProject || !state.completed.has("plan") || state.running);
  setDisabled("search-materials", !hasProject || !state.completed.has("tts") || state.running);
  setDisabled("download", !hasProject || (!allScenesApproved() && !allScenesDownloaded()) || state.running);
  setDisabled("studio", !allScenesDownloaded() || state.running);
  updateFacts();
}

function setStepState(stepId, value) {
  const card = document.querySelector(`[data-step-card="${stepId}"]`);
  const chip = document.querySelector(`[data-step-state="${stepId}"]`);
  const pill = document.querySelector(`[data-step="${stepId}"]`);
  if (card) card.dataset.state = value;
  if (chip) chip.textContent = value;
  if (pill) pill.dataset.state = value;
}

function setStepDone(stepId, done) {
  if (done) state.completed.add(stepId);
  else state.completed.delete(stepId);
}

function setDisabled(id, disabled) {
  document.getElementById(id).disabled = Boolean(disabled);
}

function setStatus(text, mode) {
  statusEl.textContent = text;
  statusEl.dataset.mode = mode;
}

function logActivity(text) {
  const line = document.createElement("div");
  line.className = "activity-line";
  line.textContent = `${new Date().toLocaleTimeString()} / ${text}`;
  activityLog.prepend(line);
}

function updateFacts() {
  document.getElementById("project-id").textContent = state.projectId || "Not created";
  document.getElementById("scene-count").textContent = state.rows.length;
  document.getElementById("approved-count").textContent = state.rows.filter((row) => row.scene.selected_candidate_id).length;
  document.getElementById("downloaded-count").textContent = state.rows.filter((row) => row.scene.material_asset_id).length;
}

function ensureProject() {
  if (!state.projectId) throw new Error("NO_PROJECT: Create a project first.");
}

function hasApprovedScene() {
  return state.rows.some((row) => row.scene.selected_candidate_id);
}

function allScenesApproved() {
  return state.rows.length > 0 && state.rows.every((row) => row.scene.selected_candidate_id);
}

function allScenesDownloaded() {
  return state.rows.length > 0 && state.rows.every((row) => row.scene.material_asset_id);
}

function formatDuration(seconds) {
  if (!seconds) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}
