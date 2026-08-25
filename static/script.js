// Video Agent — frontend logic. Vanilla JS, no build step.

const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const languageSelect = document.getElementById("language-select");
const analyzeBtn = document.getElementById("analyze-btn");

const statusZone = document.getElementById("status-zone");
const statusTitle = document.getElementById("status-title");
const statusSub = document.getElementById("status-sub");

const errorZone = document.getElementById("error-zone");
const errorMessage = document.getElementById("error-message");

const resultsZone = document.getElementById("results-zone");
const sourceBadge = document.getElementById("source-badge");
const videoTitleEl = document.getElementById("video-title");
const shortSummaryEl = document.getElementById("short-summary-text");
const detailedSummaryEl = document.getElementById("detailed-summary-text");
const keyPointsEl = document.getElementById("key-points-list");
const keywordsEl = document.getElementById("keywords-list");
const transcriptEl = document.getElementById("transcript-text");

const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const askAnswer = document.getElementById("ask-answer");

const STATUS_STEPS = [
  { title: "Fetching transcript…", sub: "Checking for captions first — it's the fast path." },
  { title: "Reading the whole thing…", sub: "Summarizing and pulling out the key points." },
  { title: "Almost done…", sub: "Finishing up keywords and formatting your results." },
];

let statusTimer = null;
const ANALYZE_TIMEOUT_MS = 120000;

function normalizeYouTubeUrl(value) {
  if (value.startsWith("//")) return `https:${value}`;
  if (!/^https?:\/\//i.test(value)) return `https://${value}`;
  return value;
}

function showStatus() {
  hide(errorZone);
  hide(resultsZone);
  statusZone.hidden = false;

  let step = 0;
  statusTitle.textContent = STATUS_STEPS[0].title;
  statusSub.textContent = STATUS_STEPS[0].sub;

  statusTimer = setInterval(() => {
    step = (step + 1) % STATUS_STEPS.length;
    statusTitle.textContent = STATUS_STEPS[step].title;
    statusSub.textContent = STATUS_STEPS[step].sub;
  }, 3200);
}

function hideStatus() {
  clearInterval(statusTimer);
  statusZone.hidden = true;
}

function hide(el) { el.hidden = true; }
function show(el) { el.hidden = false; }

function showError(message) {
  hideStatus();
  hide(resultsZone);
  errorMessage.textContent = message;
  show(errorZone);
}

function renderResults(data) {
  hideStatus();
  hide(errorZone);

  videoTitleEl.textContent = data.video_title || "Untitled video";
  sourceBadge.textContent = data.source_used === "captions" ? "captions" : "transcribed audio";

  shortSummaryEl.textContent = data.short_summary || "—";
  detailedSummaryEl.textContent = data.detailed_summary || "—";

  keyPointsEl.innerHTML = "";
  (data.key_points || []).forEach((point) => {
    const li = document.createElement("li");
    li.textContent = point;
    keyPointsEl.appendChild(li);
  });
  if (!data.key_points || data.key_points.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No distinct key points were found.";
    keyPointsEl.appendChild(li);
  }

  keywordsEl.innerHTML = "";
  (data.keywords || []).forEach((kw) => {
    const pill = document.createElement("span");
    pill.className = "keyword-pill";
    pill.textContent = kw;
    keywordsEl.appendChild(pill);
  });

  transcriptEl.textContent = data.transcript_preview || "No transcript preview available.";

  hide(askAnswer);
  askForm.reset();

  show(resultsZone);
  resultsZone.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const url = normalizeYouTubeUrl(urlInput.value.trim());
  const language = languageSelect.value;
  if (!url) return;

  analyzeBtn.disabled = true;
  showStatus();

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), ANALYZE_TIMEOUT_MS);
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, language }),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    const data = await res.json();

    if (!res.ok) {
      showError(data.detail || "Something went wrong on the server.");
      return;
    }

    if (data.status === "error") {
      showError(data.error || "Couldn't analyze this video.");
      return;
    }

    renderResults(data);
  } catch (err) {
    if (err.name === "AbortError") {
      showError("Analysis is taking too long. Try a shorter video or try again.");
    } else {
      showError("The analysis request failed. Check the server logs and try again.");
    }
  } finally {
    analyzeBtn.disabled = false;
  }
});

// Copy buttons — works for text content and list/pill containers alike.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".copy-btn");
  if (!btn) return;

  const targetId = btn.dataset.copyTarget;
  const target = document.getElementById(targetId);
  if (!target) return;

  const text = target.tagName === "UL" || target.classList.contains("keyword-pills")
    ? Array.from(target.children).map((c) => c.textContent.trim()).join(target.tagName === "UL" ? "\n" : ", ")
    : target.textContent.trim();

  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = "Copied";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove("copied");
    }, 1500);
  } catch {
    btn.textContent = "Press Ctrl+C";
  }
});

// Optional: ask a follow-up question about the last-analyzed video.
askForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = askInput.value.trim();
  if (!question) return;

  const submitBtn = askForm.querySelector("button");
  submitBtn.disabled = true;
  askAnswer.hidden = false;
  askAnswer.textContent = "Thinking…";

  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();

    if (!res.ok) {
      askAnswer.textContent = data.detail || "Couldn't answer that.";
      return;
    }
    askAnswer.textContent = data.answer;
  } catch {
    askAnswer.textContent = "Couldn't reach the server.";
  } finally {
    submitBtn.disabled = false;
  }
});
