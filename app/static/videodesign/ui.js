import { state } from "./state.js";

export function selectFirstScene() {
  state.selectedSceneId = state.rows[0]?.scene.scene_id || "";
}


export function selectFirstItemForScene(sceneId) {
  const preferredType = {
    media: "media",
    text: "text",
    captions: "caption",
    overlay: "overlay",
    transitions: "transition",
    icons: "icon",
    audio: "sfx",
  }[state.selectedTool] || "text";
  const item = timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === preferredType)
    || timelineItems().find((entry) => entry.scene_id === sceneId && entry.type === "media")
    || timelineItems().find((entry) => entry.scene_id === sceneId);
  state.selectedItemId = item?.item_id || "";
}


export function selectedRow() {
  return state.rows.find((row) => row.scene.scene_id === state.selectedSceneId) || null;
}


export function replaceScene(scene) {
  if (!scene?.scene_id) return;
  const row = state.rows.find((entry) => entry.scene.scene_id === scene.scene_id);
  if (row) row.scene = scene;
  const projectIndex = state.project?.scenes?.findIndex((entry) => entry.scene_id === scene.scene_id) ?? -1;
  if (projectIndex >= 0) state.project.scenes[projectIndex] = scene;
}


export function selectedItem() {
  return timelineItems().find((item) => item.item_id === state.selectedItemId) || null;
}


export function timelineItems() {
  return state.timeline?.items || [];
}


export function ensureProject() {
  if (!state.projectId) throw new Error("Create or load a project first.");
}


export function setStatus(message, mode) {
  const status = document.getElementById("vd-status");
  status.textContent = message;
  status.dataset.mode = mode;
}
