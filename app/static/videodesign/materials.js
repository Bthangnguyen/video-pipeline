import { api, run, startProgressPolling, stopProgressPolling } from "./api.js";
import { saveSceneDraft } from "./project.js";
import { state } from "./state.js";
import { ensureProject, selectFirstScene, selectedRow, setStatus } from "./ui.js";
import {
  escapeHtml,
  formatDuration,
  inputChecked,
  inputValue,
  setInputValue,
  sourceLabel,
  titleCase,
  uniqueValues,
} from "./utils.js";

let renderCallback = () => {};

export function configureMaterials({ renderAll }) {
  renderCallback = renderAll;
}


export async function loadReview() {
  if (!state.projectId) return;
  const data = await api(`/api/videodesign/projects/${state.projectId}/review`);
  state.rows = data.rows;
  if (data.search_plan) {
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    const popularToggle = document.getElementById("popular-first");
    if (popularToggle) popularToggle.checked = data.search_plan.popular_first !== false;
  }
  if (!state.selectedSceneId || !state.rows.some((row) => row.scene.scene_id === state.selectedSceneId)) {
    selectFirstScene();
  }
  const groupIds = new Set(materialSearchGroups().map((group) => group.group_id));
  if (!groupIds.has(state.selectedSearchGroupId)) {
    state.selectedSearchGroupId = selectedRow()?.scene?.search_group_id || materialSearchGroups()[0]?.group_id || "";
  }
  renderCallback();
}


export async function generateSelectedSceneKeywords() {
  const row = selectedRow();
  if (!row) return;
  await run("Generating scene keywords", async () => {
    await saveSceneDraft(row);
    await api(`/api/videodesign/projects/${state.projectId}/keywords/generate`, {
      method: "POST",
      body: { scene_ids: [row.scene.scene_id] },
    });
    await loadReview();
    state.selectedSceneId = row.scene.scene_id;
  });
}


export async function generateAllSceneKeywords() {
  ensureProject();
  await run("Generating all scene keywords", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/keywords/generate`, {
      method: "POST",
      body: { scene_ids: null },
    });
    await loadReview();
  });
}


export async function saveMaterialKeywords() {
  const row = selectedRow();
  if (!row) return;
  await run("Saving material keywords", async () => {
    await saveMaterialKeywordsDraft(row);
    await loadReview();
  });
}


export async function saveMaterialKeywordsDraft(row) {
  const douyinKeyword = inputValue("materials-douyin-keyword").trim();
  const pinterestKeyword = inputValue("materials-pinterest-keyword").trim();
  const group = selectedMaterialSearchGroup(row);
  if (group) {
    const plan = cloneMaterialSearchPlan();
    const editable = plan.groups.find((item) => item.group_id === group.group_id);
    if (!editable) return;
    editable.douyin_keyword = douyinKeyword;
    editable.pinterest_keyword = pinterestKeyword;
    const data = await api(`/api/videodesign/projects/${state.projectId}/search-plan`, {
      method: "PATCH",
      body: plan,
    });
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    return;
  }
  const keywords = uniqueValues([pinterestKeyword, douyinKeyword]);
  const visualPlan = {
    ...sceneVisualSearchPlan(row.scene),
    douyin_primary_keyword: douyinKeyword,
    pinterest_primary_keyword: pinterestKeyword,
  };
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${row.scene.scene_id}`, {
    method: "PATCH",
    body: { matching_keywords: keywords, visual_search_plan: visualPlan },
  });
}


export async function assignSelectedSceneToGroup() {
  const row = selectedRow();
  const targetGroupId = inputValue("scene-search-group").trim();
  if (!row || !targetGroupId || row.scene.search_group_id === targetGroupId) return;
  await run("Moving scene to search pool", async () => {
    const plan = cloneMaterialSearchPlan();
    const current = plan.groups.find((group) => (group.scene_ids || []).includes(row.scene.scene_id));
    if (current?.role === "base" && current.scene_ids.length === 1) {
      throw new Error("The base pool must keep at least one scene.");
    }
    plan.groups.forEach((group) => {
      group.scene_ids = (group.scene_ids || []).filter((sceneId) => sceneId !== row.scene.scene_id);
    });
    const target = plan.groups.find((group) => group.group_id === targetGroupId);
    if (!target) throw new Error("Selected search group no longer exists.");
    target.scene_ids.push(row.scene.scene_id);
    plan.groups = plan.groups.filter((group) => group.scene_ids.length);
    const data = await api(`/api/videodesign/projects/${state.projectId}/search-plan`, {
      method: "PATCH",
      body: plan,
    });
    state.project = { ...(state.project || {}), material_search_plan: data.search_plan };
    state.selectedSearchGroupId = targetGroupId;
    await loadReview();
  });
}


export async function runMaterialHealth() {
  const row = selectedRow();
  const keyword = inputValue("materials-douyin-keyword").trim()
    || inputValue("materials-pinterest-keyword").trim()
    || materialKeywordsForScene(row?.scene).douyin
    || materialKeywordsForScene(row?.scene).pinterest
    || "cat";
  state.materialHealth = { running: true, keyword, sources: [] };
  renderMaterialHealth();
  await run("Checking Douyin and Pinterest health", async () => {
    state.materialHealth = await api("/api/videodesign/materials/preflight", {
      method: "POST",
      body: { keyword },
    });
    renderMaterialHealth();
  });
}


export async function searchSelectedScene() {
  const row = selectedRow();
  const group = selectedMaterialSearchGroup(row);
  if (!row || !group) {
    setStatus("Generate or select a search group first.", "error");
    return;
  }
  await run("Searching selected group", async () => {
    await saveMaterialKeywordsDraft(row);
    const body = materialSearchBody(null, [group.group_id]);
    await api(`/api/videodesign/projects/${state.projectId}/materials/search`, {
      method: "POST",
      body,
    });
    await loadReview();
  });
}


export async function searchAllScenes() {
  ensureProject();
  await run("Searching all scenes", async () => {
    const row = selectedRow();
    if (row) await saveMaterialKeywordsDraft(row);
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


export async function approveCandidate(sceneId, candidateId) {
  await run("Approving candidate", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "approve", candidate_id: candidateId },
    });
    await loadReview();
  });
}


export async function deleteCandidate(sceneId, candidateId) {
  await run("Deleting candidate", async () => {
    await rejectCandidate(sceneId, candidateId);
    if (state.previewCandidateId === candidateId) state.previewCandidateId = "";
    await loadReview();
  });
}


export async function clearSelectedSceneCandidates() {
  const row = selectedRow();
  if (!row) {
    setStatus("Select a scene first.", "error");
    return;
  }
  if (!row.candidates.length) {
    setStatus("This scene has no videos to clear.", "idle");
    return;
  }
  if (!window.confirm(`Clear ${row.candidates.length} videos from Scene ${row.scene.order}?`)) return;
  await run("Clearing scene videos", async () => {
    for (const candidate of row.candidates) {
      await rejectCandidate(row.scene.scene_id, candidate.candidate_id);
    }
    state.previewCandidateId = "";
    await loadReview();
  });
}


export async function clearAllCandidates() {
  const candidates = state.rows.flatMap((row) => row.candidates.map((candidate) => ({ ...candidate, scene_id: row.scene.scene_id })));
  if (!candidates.length) {
    setStatus("There are no videos to clear.", "idle");
    return;
  }
  if (!window.confirm(`Clear all ${candidates.length} material videos from this project?`)) return;
  await run("Clearing all material videos", async () => {
    for (const candidate of candidates) {
      await rejectCandidate(candidate.scene_id, candidate.candidate_id);
    }
    state.previewCandidateId = "";
    await loadReview();
  });
}


export async function rejectCandidate(sceneId, candidateId) {
  await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
    method: "PATCH",
    body: { action: "reject", candidate_id: candidateId },
  });
}


export async function allowPlaceholder(sceneId) {
  await run("Allowing placeholder", async () => {
    await api(`/api/videodesign/projects/${state.projectId}/scenes/${sceneId}/selection`, {
      method: "PATCH",
      body: { action: "placeholder" },
    });
    await loadReview();
  });
}


export async function keepSelectedCandidates() {
  ensureProject();
  const sceneIds = state.rows.filter(rowHasApprovedCandidate).map((row) => row.scene.scene_id);
  if (!sceneIds.length) {
    setStatus("No selected candidates are ready to keep.", "idle");
    return;
  }
  if (!window.confirm(`Remove unselected candidate videos from ${sceneIds.length} selected scene(s)?`)) return;
  await run("Keeping selected videos", async () => {
    const data = await api(`/api/videodesign/projects/${state.projectId}/materials/prune`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    state.previewCandidateId = "";
    await loadReview();
    setStatus(`Kept ${data.kept} selected video(s), removed ${data.removed} extra candidate(s).`, "idle");
  });
}


export async function downloadApproved() {
  ensureProject();
  await run("Downloading approved videos", async () => {
    const sceneIds = state.rows
      .filter((row) => rowHasApprovedCandidate(row) && !row.scene.material_asset_id)
      .map((row) => row.scene.scene_id);
    if (!sceneIds.length) throw new Error("No approved scenes are waiting for download.");
    const data = await api(`/api/videodesign/projects/${state.projectId}/materials/download`, {
      method: "POST",
      body: { scene_ids: sceneIds },
    });
    await loadReview();
    if (data.skipped?.length) {
      setStatus(`Downloaded ${data.assets.length} video(s), skipped ${data.skipped.length} scene(s) without approved candidates.`, "idle");
    }
  });
}


export function rowHasApprovedCandidate(row) {
  if (!row?.scene?.selected_candidate_id) return false;
  const selected = row.candidates?.find((candidate) => candidate.candidate_id === row.scene.selected_candidate_id);
  return selected?.status === "approved";
}


export function materialSearchBody(sceneIds = null, groupIds = null) {
  const douyinMin = Number(inputValue("douyin-min-count", state.preset.scene_media.candidate_count || 0));
  const pinterestMin = Number(inputValue("pinterest-min-count", state.preset.scene_media.pinterest_candidate_count || 0));
  return {
    scene_ids: sceneIds,
    group_ids: groupIds,
    candidates_per_scene: Math.max(douyinMin, 1),
    douyin_min_per_scene: douyinMin,
    pinterest_min_per_scene: pinterestMin,
    queries_per_scene: 2,
    translate_to_chinese: true,
    use_smart_keywords: false,
    popular_first: inputChecked("popular-first", true),
  };
}


export function renderCandidateBoard() {
  const row = selectedRow();
  const board = document.getElementById("candidate-board");
  document.getElementById("materials-scene-title").textContent = row ? `Scene ${row.scene.order}: ${row.scene.approval_state}` : "Select a scene";
  renderMaterialControls(row);
  if (!row) {
    board.innerHTML = `<div class="vd-empty">Select a scene to review candidates.</div>`;
    return;
  }
  if (!row.candidates.length) {
    board.innerHTML = `
      <div class="vd-empty">
        <h3>No candidates yet</h3>
        <p>Search this scene or allow a placeholder before Studio.</p>
        <button data-placeholder-scene="${row.scene.scene_id}" type="button">Allow placeholder</button>
      </div>
    `;
  } else {
    const bySource = {
      douyinsearch: row.candidates.filter((candidate) => candidate.source !== "pinterestsearch"),
      pinterestsearch: row.candidates.filter((candidate) => candidate.source === "pinterestsearch"),
    };
    board.innerHTML = `
      <section class="vd-source-section">
        <h3>Douyin <span>${bySource.douyinsearch.length}</span></h3>
        <div class="vd-source-grid">${candidateCards(bySource.douyinsearch, row, "douyinsearch")}</div>
      </section>
      <section class="vd-source-section">
        <h3>Pinterest <span>${bySource.pinterestsearch.length}</span></h3>
        <div class="vd-source-grid">${candidateCards(bySource.pinterestsearch, row, "pinterestsearch")}</div>
      </section>
    `;
  }
  board.querySelectorAll("[data-approve-candidate]").forEach((button) => {
    button.addEventListener("click", () => approveCandidate(button.dataset.approveScene, button.dataset.approveCandidate));
  });
  board.querySelectorAll("[data-placeholder-scene]").forEach((button) => {
    button.addEventListener("click", () => allowPlaceholder(button.dataset.placeholderScene));
  });
  board.querySelectorAll("[data-preview-candidate]").forEach((button) => {
    button.addEventListener("click", () => previewCandidate(button.dataset.previewCandidate));
  });
  board.querySelectorAll("[data-delete-candidate]").forEach((button) => {
    button.addEventListener("click", () => deleteCandidate(button.dataset.deleteScene, button.dataset.deleteCandidate));
  });
  hydrateCandidateCoverImages(board);
}


export function candidateCards(candidates, row, source) {
  if (!candidates.length) return `<div class="vd-empty">No ${escapeHtml(sourceLabel(source))} candidates yet.</div>`;
  return candidates.map((candidate) => {
    const coverSrc = candidateCoverSrc(candidate);
    const coverState = state.materialCoverCache[candidate.candidate_id]?.state || "loading";
    const orderLabel = candidateOrderLabel(candidate);
    const usedBy = candidateUsedByScene(candidate, row.scene.scene_id);
    const likes = Number(candidate.stats?.digg_count || 0);
    return `
      <article class="vd-candidate ${candidate.status === "approved" ? "is-approved" : ""}">
        <img src="${escapeHtml(coverSrc)}" alt="" loading="eager" decoding="async" data-cover-candidate-id="${escapeHtml(candidate.candidate_id)}" data-cover-url="${escapeHtml(candidate.cover_url || "")}" data-cover-state="${escapeHtml(coverState)}">
        <div>
          <div class="vd-candidate-badges">
            <span class="vd-source-badge">${escapeHtml(sourceLabel(candidate.source))}</span>
            <span class="vd-order-badge" data-applied="${candidate.popularity?.applied === true}">${escapeHtml(orderLabel)}</span>
          </div>
          <h3>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</h3>
          <p>${escapeHtml(candidate.match_reason)}</p>
          <p>${formatDuration(candidate.duration)}${likes ? ` / ${escapeHtml(formatCompactCount(likes))} likes` : ""}</p>
          ${usedBy ? `<p class="vd-used-note">Also selected in Scene ${usedBy.scene.order}</p>` : ""}
          <div class="vd-button-row">
            <button data-approve-candidate="${candidate.candidate_id}" data-approve-scene="${row.scene.scene_id}" type="button">${candidate.status === "approved" ? "Approved" : "Approve"}</button>
            <button data-preview-candidate="${candidate.candidate_id}" type="button">Preview</button>
            <button data-delete-candidate="${candidate.candidate_id}" data-delete-scene="${row.scene.scene_id}" class="vd-danger" type="button">Delete</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
}


export function candidateOrderLabel(candidate) {
  if (candidate.source === "pinterestsearch") return "Platform order";
  if (candidate.popularity?.applied) return "Popular";
  if (candidate.popularity?.requested) return "Popular unavailable";
  return "Relevance";
}


export function candidateUsedByScene(candidate, currentSceneId) {
  const sourceId = candidate.source_result_id || candidate.source_item_id || candidate.douyin_aweme_id;
  if (!sourceId) return null;
  return state.rows.find((row) => {
    if (row.scene.scene_id === currentSceneId || !row.scene.selected_candidate_id) return false;
    const selected = row.candidates.find((item) => item.candidate_id === row.scene.selected_candidate_id);
    const selectedSourceId = selected?.source_result_id || selected?.source_item_id || selected?.douyin_aweme_id;
    return selected?.source === candidate.source && selectedSourceId === sourceId;
  }) || null;
}


export function formatCompactCount(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(number >= 100_000 ? 0 : 1)}K`;
  return String(Math.round(number));
}


export function candidateCoverSrc(candidate) {
  const cached = state.materialCoverCache[candidate.candidate_id];
  return cached?.objectUrl || cached?.url || candidate.cover_url || "";
}


export function hydrateCandidateCoverImages(container) {
  container.querySelectorAll("[data-cover-candidate-id]").forEach((image) => {
    const candidateId = image.dataset.coverCandidateId;
    const coverUrl = image.dataset.coverUrl || "";
    if (!candidateId || !coverUrl) {
      image.dataset.coverState = "empty";
      return;
    }
    const cached = state.materialCoverCache[candidateId];
    if (cached?.objectUrl) {
      image.src = cached.objectUrl;
      image.dataset.coverState = "loaded";
      return;
    }
    image.addEventListener("load", () => {
      state.materialCoverCache[candidateId] = { ...(state.materialCoverCache[candidateId] || {}), url: coverUrl, state: "loaded" };
      image.dataset.coverState = "loaded";
    }, { once: true });
    image.addEventListener("error", () => {
      state.materialCoverCache[candidateId] = { ...(state.materialCoverCache[candidateId] || {}), url: coverUrl, state: "error" };
      image.dataset.coverState = "error";
    }, { once: true });
    if (cached?.fetching || cached?.state === "error") return;
    state.materialCoverCache[candidateId] = { url: coverUrl, state: "loading", fetching: true };
    fetch(coverUrl, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error("cover fetch failed");
        return response.blob();
      })
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        state.materialCoverCache[candidateId] = { url: coverUrl, objectUrl, state: "loaded" };
        if (document.body.contains(image)) {
          image.src = objectUrl;
          image.dataset.coverState = "loaded";
        }
      })
      .catch(() => {
        state.materialCoverCache[candidateId] = { url: coverUrl, state: "error" };
        if (document.body.contains(image)) image.dataset.coverState = "error";
      });
  });
}


export function renderMaterialControls(row) {
  const group = selectedMaterialSearchGroup(row);
  const plan = sceneVisualSearchPlan(row?.scene);
  const keywords = group
    ? { douyin: group.douyin_keyword || "", pinterest: group.pinterest_keyword || "" }
    : materialKeywordsForScene(row?.scene);
  renderMaterialSearchGroups();
  const title = document.getElementById("materials-group-title");
  const role = document.getElementById("materials-group-role");
  if (title) title.textContent = group?.label || "Select a search group";
  if (role) {
    role.textContent = titleCase(group?.role || "base");
    role.dataset.role = group?.role || "base";
  }
  const chips = document.getElementById("materials-keyword-chips");
  if (chips) {
    chips.innerHTML = keywords.douyin || keywords.pinterest
      ? `
        ${keywords.douyin ? `<button data-keyword-source="douyin" type="button"><strong>Douyin</strong> ${escapeHtml(keywords.douyin)}</button>` : ""}
        ${keywords.pinterest ? `<button data-keyword-source="pinterest" type="button"><strong>Pinterest</strong> ${escapeHtml(keywords.pinterest)}</button>` : ""}
      `
      : `<span class="vd-muted">No visual search plan yet.</span>`;
    chips.querySelectorAll("[data-keyword-source]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.keywordSource === "douyin") setInputValue("materials-douyin-keyword", keywords.douyin || "");
        if (button.dataset.keywordSource === "pinterest") setInputValue("materials-pinterest-keyword", keywords.pinterest || "");
      });
    });
  }
  setInputValue("materials-douyin-keyword", keywords.douyin || "");
  setInputValue("materials-pinterest-keyword", keywords.pinterest || "");
  renderSceneSearchGroupSelect(row, group);
  renderVisualSearchNotes(plan, group);
  renderSearchErrors(row);
  renderMaterialHealth();
  renderMaterialPreview(row);
}


export function renderMaterialSearchGroups() {
  const panel = document.getElementById("materials-search-groups");
  if (!panel) return;
  const groups = materialSearchGroups();
  if (!groups.length) {
    panel.innerHTML = `<div class="vd-empty vd-search-plan-empty">Generate a shared search plan before searching video.</div>`;
    return;
  }
  panel.innerHTML = groups.map((group) => {
    const rows = state.rows.filter((row) => (group.scene_ids || []).includes(row.scene.scene_id));
    const candidateCount = rows.reduce((maximum, row) => Math.max(maximum, row.candidates.length), 0);
    return `
      <button class="vd-search-group" data-search-group-id="${escapeHtml(group.group_id)}" data-active="${group.group_id === selectedMaterialSearchGroup()?.group_id}" type="button">
        <span class="vd-pool-badge" data-role="${escapeHtml(group.role)}">${escapeHtml(titleCase(group.role))}</span>
        <strong>${escapeHtml(group.label || group.pinterest_keyword || group.douyin_keyword)}</strong>
        <em>${rows.length} scene${rows.length === 1 ? "" : "s"} / ${candidateCount} candidates</em>
      </button>
    `;
  }).join("");
  panel.querySelectorAll("[data-search-group-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = groups.find((item) => item.group_id === button.dataset.searchGroupId);
      state.selectedSearchGroupId = group?.group_id || "";
      if (group?.scene_ids?.length) state.selectedSceneId = group.scene_ids[0];
      renderCallback();
    });
  });
}


export function renderSceneSearchGroupSelect(row, activeGroup) {
  const select = document.getElementById("scene-search-group");
  if (!select) return;
  const groups = materialSearchGroups();
  select.innerHTML = groups.length
    ? groups.map((group) => `<option value="${escapeHtml(group.group_id)}">${escapeHtml(titleCase(group.role))}: ${escapeHtml(group.label || group.pinterest_keyword)}</option>`).join("")
    : `<option value="">No search groups</option>`;
  select.value = row?.scene?.search_group_id || activeGroup?.group_id || "";
  select.disabled = !row || !groups.length;
  const button = document.getElementById("assign-scene-search-group");
  if (button) button.disabled = !row || groups.length < 2;
}


export function renderVisualSearchNotes(plan, group = null) {
  const panel = document.getElementById("materials-visual-notes");
  if (!panel) return;
  if (!group && (!plan || !Object.keys(plan).length)) {
    panel.innerHTML = `<p class="vd-muted">Generate a shared search plan first.</p>`;
    return;
  }
  const douyinFallbacks = group?.douyin_fallback ? [group.douyin_fallback] : (plan.fallbacks?.douyin || []);
  const pinterestFallbacks = group?.pinterest_fallback ? [group.pinterest_fallback] : (plan.fallbacks?.pinterest || []);
  panel.innerHTML = `
    ${group ? `<p><strong>${group.scene_ids.length} assigned scene${group.scene_ids.length === 1 ? "" : "s"}</strong></p>` : ""}
    ${group?.exact_subject ? `<p><strong>Exact subject</strong> ${escapeHtml(group.exact_subject)}</p>` : ""}
    ${!group && plan.retention_role ? `<p><strong>Role</strong> ${escapeHtml(plan.retention_role)}</p>` : ""}
    ${!group && plan.content_anchor ? `<p><strong>Anchor</strong> ${escapeHtml(plan.content_anchor)}</p>` : ""}
    ${!group && plan.material_notes ? `<p>${escapeHtml(plan.material_notes)}</p>` : ""}
    ${douyinFallbacks.length || pinterestFallbacks.length ? `
      <p class="vd-muted">Fallbacks:
        ${douyinFallbacks.length ? `Douyin ${douyinFallbacks.map(escapeHtml).join(", ")}` : ""}
        ${pinterestFallbacks.length ? ` Pinterest ${pinterestFallbacks.map(escapeHtml).join(", ")}` : ""}
      </p>
    ` : ""}
  `;
}


export function renderSearchErrors(row) {
  const panel = document.getElementById("materials-search-errors");
  if (!panel) return;
  const errors = (row?.search_errors || []).slice(-6);
  panel.innerHTML = errors.length
    ? `
      <h4>Search issues</h4>
      ${errors.map((error) => `
        <div class="vd-search-error">
          <strong>${escapeHtml(sourceLabel(error.source))} / ${escapeHtml(error.keyword)}</strong>
          <span>${escapeHtml(error.code)}</span>
        </div>
      `).join("")}
    `
    : "";
}


export function renderMaterialPreview(row) {
  const panel = document.getElementById("materials-preview");
  if (!panel) return;
  const candidate = row?.candidates.find((item) => item.candidate_id === state.previewCandidateId);
  if (!candidate) {
    panel.innerHTML = `<div class="vd-empty">Choose a candidate to preview here.</div>`;
    return;
  }
  const sources = materialPreviewSources(candidate);
  panel.innerHTML = `
    <h4>${escapeHtml(sourceLabel(candidate.source))} preview</h4>
    <video data-material-preview-video controls playsinline preload="metadata" poster="${escapeHtml(candidate.cover_url || "")}"></video>
    <div class="vd-preview-status" data-material-preview-status>${sources.length ? "Loading preview..." : "No preview URL is available for this candidate."}</div>
    ${sources.length > 1 ? `
      <div class="vd-preview-sources">
        ${sources.map((source, index) => `<button data-preview-source-index="${index}" type="button">${escapeHtml(source.label)}</button>`).join("")}
      </div>
    ` : ""}
    <strong>${escapeHtml(candidate.title || candidate.source_item_id || candidate.douyin_aweme_id)}</strong>
    <p>${escapeHtml(candidate.search_keyword || candidate.match_reason || "")}</p>
  `;
  setupMaterialPreviewVideo(panel, sources);
}


export function materialPreviewSources(candidate) {
  const sources = [];
  const add = (url, label) => {
    const value = String(url || "").trim();
    if (!value || sources.some((source) => source.url === value)) return;
    sources.push({ url: value, label });
  };
  if (candidate.source === "pinterestsearch") {
    add(candidate.media_url, "Media");
    add(candidate.stream_url, "Stream");
    add(candidate.download_url, "Download");
  } else {
    add(candidate.stream_url, "Stream");
    add(candidate.download_url, "Download");
  }
  return sources;
}


export function setupMaterialPreviewVideo(panel, sources) {
  const video = panel.querySelector("[data-material-preview-video]");
  const status = panel.querySelector("[data-material-preview-status]");
  const buttons = Array.from(panel.querySelectorAll("[data-preview-source-index]"));
  if (!video || !sources.length) return;

  let activeIndex = 0;
  const setStatusText = (message) => {
    if (status) status.textContent = message;
  };
  const updateButtons = () => {
    buttons.forEach((button) => {
      button.dataset.active = Number(button.dataset.previewSourceIndex) === activeIndex ? "true" : "false";
    });
  };
  const setSource = (index, message = "") => {
    activeIndex = index;
    const source = sources[activeIndex];
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.src = source.url;
    video.load();
    setStatusText(message || `Loading ${source.label.toLowerCase()} preview...`);
    updateButtons();
  };

  video.addEventListener("loadedmetadata", () => setStatusText(`Preview ready via ${sources[activeIndex].label.toLowerCase()}.`));
  video.addEventListener("error", () => {
    const failed = sources[activeIndex];
    if (activeIndex < sources.length - 1) {
      const next = sources[activeIndex + 1];
      setSource(activeIndex + 1, `${failed.label} preview failed, trying ${next.label.toLowerCase()}...`);
      return;
    }
    setStatusText("Preview failed in browser. Try approving/downloading this candidate, or choose another result.");
  });
  buttons.forEach((button) => {
    button.addEventListener("click", () => setSource(Number(button.dataset.previewSourceIndex || 0)));
  });
  setSource(0);
}


export function renderMaterialHealth() {
  const panel = document.getElementById("material-health-panel");
  if (!panel) return;
  const health = state.materialHealth;
  if (!health) {
    panel.innerHTML = `<div class="vd-muted">Run health check before searching if Douyin or Pinterest feels unstable.</div>`;
    return;
  }
  if (health.running) {
    panel.innerHTML = `<div class="vd-health-running">Checking cookie, anti-bot, page load, input search, and network for "${escapeHtml(health.keyword)}"...</div>`;
    return;
  }
  panel.innerHTML = `
    <h4>Search health: ${health.healthy ? "Ready" : "Needs attention"}</h4>
    ${(health.sources || []).map((source) => `
      <section class="vd-health-source" data-ok="${source.success ? "true" : "false"}">
        <strong>${escapeHtml(sourceLabel(source.source))}</strong>
        ${(source.checks || []).map((check) => `
          <div class="vd-health-check" data-ok="${check.ok ? "true" : "false"}">
            <span>${check.ok ? "OK" : "FAIL"}</span>
            <p><b>${escapeHtml(check.name)}</b> ${escapeHtml(check.message)}</p>
          </div>
        `).join("")}
      </section>
    `).join("")}
  `;
}


export function previewCandidate(candidateId) {
  state.previewCandidateId = candidateId;
  renderCandidateBoard();
}


export function sceneVisualSearchPlan(scene) {
  return scene?.visual_search_plan && typeof scene.visual_search_plan === "object"
    ? scene.visual_search_plan
    : {};
}


export function materialSearchPlan() {
  const plan = state.project?.material_search_plan;
  return plan && typeof plan === "object"
    ? plan
    : { popular_first: true, groups: [] };
}


export function cloneMaterialSearchPlan() {
  return JSON.parse(JSON.stringify(materialSearchPlan()));
}


export function materialSearchGroups() {
  return Array.isArray(materialSearchPlan().groups) ? materialSearchPlan().groups : [];
}


export function searchGroupForScene(scene) {
  if (!scene) return null;
  return materialSearchGroups().find((group) => (group.scene_ids || []).includes(scene.scene_id)) || null;
}


export function selectedMaterialSearchGroup(row = selectedRow()) {
  const groups = materialSearchGroups();
  return groups.find((group) => group.group_id === state.selectedSearchGroupId)
    || searchGroupForScene(row?.scene)
    || groups[0]
    || null;
}


export function materialKeywordsForScene(scene) {
  const group = searchGroupForScene(scene);
  if (group) {
    return {
      douyin: String(group.douyin_keyword || "").trim(),
      pinterest: String(group.pinterest_keyword || "").trim(),
    };
  }
  const plan = sceneVisualSearchPlan(scene);
  const legacy = scene?.matching_keywords || [];
  return {
    douyin: String(plan.douyin_primary_keyword || legacy[0] || "").trim(),
    pinterest: String(plan.pinterest_primary_keyword || legacy[0] || "").trim(),
  };
}
