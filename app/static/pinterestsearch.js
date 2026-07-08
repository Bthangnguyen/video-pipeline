const message = document.getElementById("message");
const results = document.getElementById("results");
const sessionState = document.getElementById("session-state");

document.getElementById("session-check").addEventListener("click", checkSession);
document.getElementById("search").addEventListener("click", search);
document.getElementById("keyword").addEventListener("keydown", (event) => {
  if (event.key === "Enter") search();
});

async function checkSession() {
  sessionState.textContent = "Checking...";
  const response = await fetch("/api/pinterest/session/check", { method: "POST" });
  const data = await response.json();
  sessionState.textContent = `${data.state}: ${data.message}`;
}

async function search() {
  const keyword = document.getElementById("keyword").value.trim();
  const mediaType = document.getElementById("media-type").value;
  const aspectRatio = document.getElementById("aspect-ratio").value;
  const limit = Number(document.getElementById("limit").value || 12);
  if (!keyword) {
    message.textContent = "Enter a keyword first.";
    return;
  }

  message.textContent = "Searching Pinterest...";
  results.innerHTML = "";
  const response = await fetch("/api/pinterest/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      keyword,
      media_type: mediaType,
      aspect_ratio: aspectRatio,
      limit,
    }),
  });
  const data = await response.json();
  if (!data.success) {
    message.textContent = `${data.error.code}: ${data.error.message}`;
    return;
  }
  message.textContent = `Found ${data.items.length} ${data.media_type} result(s) for ${data.keyword}`;
  renderResults(data.items);
}

function renderResults(items) {
  results.innerHTML = items.map((item) => `
    <article class="card">
      ${renderMedia(item)}
      <div class="card-body">
        <h2>${escapeHtml(item.title || item.pin_id || "Pinterest result")}</h2>
        <div class="meta">
          <span>${escapeHtml(item.media_type)}</span>
          <span>${escapeHtml(item.aspect_ratio || `${item.width}x${item.height}`)}</span>
        </div>
        <div class="actions">
          <a class="download-video" href="${item.source_url}" target="_blank" rel="noreferrer">Open pin</a>
        </div>
      </div>
    </article>
  `).join("");
}

function renderMedia(item) {
  if (item.media_type === "video") {
    return `<video controls preload="metadata" poster="${item.cover_url}" src="${item.media_url}"></video>`;
  }
  return `<img src="${item.cover_url}" alt="${escapeHtml(item.title || "Pinterest result")}">`;
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
