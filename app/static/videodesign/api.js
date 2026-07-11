import { state } from "./state.js";
import { setStatus } from "./ui.js";

let progressTimer = null;
let renderCallback = () => {};
let reviewCallback = async () => {};

export function configureApi({ renderAll, loadReview }) {
  renderCallback = renderAll;
  reviewCallback = loadReview;
}


export async function api(url, options = {}) {
  const hasFormData = Boolean(options.formData);
  const response = await fetch(url, {
    method: options.method || "GET",
    headers: !hasFormData && options.body ? { "Content-Type": "application/json" } : undefined,
    body: hasFormData ? options.formData : (options.body ? JSON.stringify(options.body) : undefined),
  });
  const data = await response.json();
  if (!data.success) {
    throw new Error(`${data.error.code}: ${data.error.message}`);
  }
  return data;
}


export async function run(label, handler) {
  try {
    state.running = true;
    setStatus(label, "running");
    await handler();
    setStatus("Ready", "idle");
  } catch (error) {
    setStatus(error.message || String(error), "error");
  } finally {
    state.running = false;
    renderCallback();
  }
}


export function startProgressPolling() {
  stopProgressPolling();
  state.lastProgressMessage = "";
  progressTimer = window.setInterval(pollProgress, 2000);
  pollProgress();
}


export function stopProgressPolling() {
  if (progressTimer) window.clearInterval(progressTimer);
  progressTimer = null;
}


export async function pollProgress() {
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
    if (progress.stage === "materials_search") {
      await reviewCallback();
    }
  } catch {
    return;
  }
}
