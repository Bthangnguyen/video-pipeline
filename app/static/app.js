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
  const response = await fetch("/api/douyin/session/check", { method: "POST" });
  const data = await response.json();
  sessionState.textContent = `${data.state}: ${data.message}`;
}

async function search() {
  const keyword = document.getElementById("keyword").value.trim();
  const translate = document.getElementById("translate").checked;
  const limit = Number(document.getElementById("limit").value || 12);
  if (!keyword) {
    message.textContent = "Enter a keyword first.";
    return;
  }

  message.textContent = "Searching...";
  results.innerHTML = "";
  const response = await fetch("/api/douyin/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      keyword,
      translate_to_chinese: translate,
      limit,
      strategy: "auto",
    }),
  });
  const data = await response.json();
  if (!data.success) {
    message.textContent = `${data.error.code}: ${data.error.message}`;
    return;
  }
  message.textContent = `Found ${data.items.length} results for ${data.search_keyword}`;
  renderResults(data.items);
}

function renderResults(items) {
  results.innerHTML = items.map((item) => `
    <article class="card" data-stream="${item.stream_url}">
      <video controls preload="none" poster="${item.cover_url}"></video>
      <div class="card-body">
        <h2>${escapeHtml(item.title || item.description || item.douyin_aweme_id)}</h2>
        <div class="meta">
          <span>@${escapeHtml(item.author_name || "unknown")}</span>
          <span>${formatDuration(item.duration)}</span>
        </div>
        <button class="load-video" type="button">Load video</button>
      </div>
    </article>
  `).join("");

  document.querySelectorAll(".card").forEach((card) => {
    card.querySelector(".load-video").addEventListener("click", () => {
      const video = card.querySelector("video");
      if (!video.src) {
        video.src = card.dataset.stream;
      }
      video.play().catch(() => {
        message.textContent = "Video is loading. Press play again if the browser blocked autoplay.";
      });
    });
  });
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
