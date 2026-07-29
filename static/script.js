// ===============================
// Elements
// ===============================

const documentStatus  = document.getElementById("documentStatus");
const docBadgeText    = document.getElementById("docBadgeText");
const askBtn          = document.getElementById("askBtn");
const questionInput   = document.getElementById("question");
const chatBox         = document.getElementById("chatBox");
const clearBtn        = document.getElementById("clearBtn");
const kbLoading       = document.getElementById("kbLoading");
const kbEmpty         = document.getElementById("kbEmpty");
const kbList          = document.getElementById("kbList");
const kbCount         = document.getElementById("kbCount");
const welcomeState    = document.getElementById("welcomeState");
const welcomeTitle    = document.getElementById("welcomeTitle");
const welcomeSubtitle = document.getElementById("welcomeSubtitle");

let msgCounter = 0;

// ===============================
// On Page Load
// ===============================

window.addEventListener("load", () => {
    questionInput.focus();
    loadKnowledgeBase();
    startKbPolling();
});

// ===============================
// Knowledge Base Polling
// ===============================

let _kbPollInterval = null;
let _kbLastCount    = -1;   // track doc count to detect changes

function startKbPolling() {
    // Poll every 10 seconds, but only when the tab is visible
    _kbPollInterval = setInterval(() => {
        if (document.visibilityState === "hidden") return;
        _pollKnowledgeBase();
    }, 10000);
}

function _pollKnowledgeBase() {
    fetch("/documents")
        .then(r => r.json())
        .then(data => {
            const docs  = data.documents || [];
            const count = docs.length;
            // Only re-render if something actually changed
            if (count !== _kbLastCount) {
                _kbLastCount = count;
                loadKnowledgeBase();
            }
        })
        .catch(() => { /* silent — network blip, try again next tick */ });
}

// ===============================
// Knowledge Base — load & render
// ===============================

function loadKnowledgeBase() {
    kbLoading.style.display = "flex";
    kbEmpty.style.display   = "none";
    kbList.style.display    = "none";

    fetch("/documents")
        .then(r => r.json())
        .then(data => {
            kbLoading.style.display = "none";

            const docs = data.documents || [];
            _kbLastCount = docs.length;   // keep poll tracker in sync
            kbCount.textContent = docs.length + (docs.length === 1 ? " doc" : " docs");

            if (docs.length === 0) {
                kbEmpty.style.display = "flex";
                // Update header badge
                docBadgeText.textContent = "No documents loaded";
                documentStatus.classList.remove("loaded");
                // Update welcome message
                welcomeTitle.textContent    = "No documents loaded yet";
                welcomeSubtitle.textContent = "Ask your admin to upload documents to the knowledge base.";
                return;
            }

            // Build list
            kbList.innerHTML = "";
            docs.forEach(doc => renderKbItem(doc));
            kbList.style.display = "flex";

            // Update header badge
            docBadgeText.textContent = docs.length + (docs.length === 1 ? " document" : " documents") + " available";
            documentStatus.classList.add("loaded");

            // Update welcome message
            welcomeTitle.textContent    = "Ask me anything";
            welcomeSubtitle.textContent = "I'll answer based on the " + docs.length + " document" + (docs.length === 1 ? "" : "s") + " in the knowledge base.";
        })
        .catch(() => {
            kbLoading.style.display = "none";
            kbEmpty.style.display   = "flex";
            kbCount.textContent     = "0 docs";
            docBadgeText.textContent = "Knowledge base unavailable";
        });
}

function renderKbItem(doc) {
    const name   = typeof doc === "string" ? doc : (doc.filename || doc.name || "Unknown");
    const chunks = typeof doc === "object" ? (doc.chunks || null) : null;
    const date   = typeof doc === "object" ? (doc.ingested_at || doc.date || null) : null;

    const li = document.createElement("li");
    li.className = "kb-item";

    li.innerHTML = `
        <div class="kb-item-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
            </svg>
        </div>
        <div class="kb-item-body">
            <p class="kb-item-name" title="${escHtml(name)}">${escHtml(name)}</p>
            <div class="kb-item-meta">
                ${chunks ? `<span class="kb-item-chunks">${chunks} chunks</span><span class="kb-item-dot"></span>` : ""}
                ${date   ? `<span class="kb-item-date">${formatDate(date)}</span>` : ""}
            </div>
        </div>`;

    kbList.appendChild(li);
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatDate(raw) {
    try {
        const d = new Date(String(raw).replace(" ", "T"));
        if (isNaN(d.getTime())) return raw;
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    } catch { return raw; }
}

// ===============================
// Clear Chat
// ===============================

clearBtn.addEventListener("click", () => {
    chatBox.innerHTML = "";
    chatBox.appendChild(welcomeState);
    welcomeState.style.display = "flex";
});

// ===============================
// Auto-scroll
// ===============================

function autoScrollChat() {
    requestAnimationFrame(() => { chatBox.scrollTop = chatBox.scrollHeight; });
}

// ===============================
// Send Message
// ===============================

askBtn.addEventListener("click", sendMessage);
questionInput.addEventListener("keypress", (e) => { if (e.key === "Enter" && !askBtn.disabled) sendMessage(); });

function sendMessage() {
    const question = questionInput.value.trim();
    if (!question) return;

    // Hide welcome state on first message
    if (welcomeState) welcomeState.style.display = "none";

    addUserMessage(question);
    questionInput.value = "";

    // ── Disable send while answer is in progress, keep input typeable ──
    askBtn.disabled           = true;
    questionInput.placeholder = "Ask anything about your documents…";

    addLoading();

    fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question })
    })
    .then(r => r.json())
    .then(result => {
        removeLoading();
        addBotMessage(result.status === "success" ? result.answer : "❌ " + result.message);
        _enableInput();
        setTimeout(() => { autoScrollChat(); questionInput.focus(); }, 100);
    })
    .catch(err => {
        removeLoading();
        addBotMessage("❌ " + err.message);
        _enableInput();
        setTimeout(() => { autoScrollChat(); questionInput.focus(); }, 100);
    });
}

function _enableInput() {
    askBtn.disabled           = false;
    questionInput.placeholder = "Ask anything about your documents…";
}

// ===============================
// Chat Messages
// ===============================

function addUserMessage(text) {
    const div = document.createElement("div");
    div.className = "user-message";
    div.textContent = text;
    chatBox.appendChild(div);
    autoScrollChat();
}

function addBotMessage(rawText) {
    msgCounter++;
    const speechId = "speech_" + msgCounter;

    let bodyHtml;
    if (typeof marked !== "undefined") {
        marked.setOptions({ breaks: true, gfm: true });
        bodyHtml = marked.parse(rawText);
    } else {
        bodyHtml = rawText
            .split(/\n\n+/)
            .map(p => "<p>" + p.replace(/\n/g, "<br>").trim() + "</p>")
            .join("");
    }

    const card = document.createElement("div");
    card.className = "bot-message";

    card.innerHTML = `
        <div class="bot-message-header">
            <div class="bot-avatar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7H3a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2z"/>
                    <path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>
                    <circle cx="9" cy="17" r="1"/><circle cx="15" cy="17" r="1"/>
                </svg>
            </div>
            <span class="bot-label">AI</span>
        </div>
        <div class="bot-message-body" id="${speechId}">${bodyHtml}</div>
        <div class="bot-message-footer">
            <button class="play-btn" onclick="speakMessage('${speechId}', this)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
                </svg>
                Play
            </button>
        </div>`;

    chatBox.appendChild(card);

    if (typeof hljs !== "undefined") {
        card.querySelectorAll("pre code").forEach(block => hljs.highlightElement(block));
    }

    autoScrollChat();
}

// ===============================
// Loading indicator
// ===============================

function addLoading() {
    const div = document.createElement("div");
    div.className = "loading";
    div.id = "loading";
    div.innerHTML = `
        <div class="typing-dots">
            <span></span><span></span><span></span>
        </div>
        <span class="loading-label">Thinking…</span>`;
    chatBox.appendChild(div);
    autoScrollChat();
}

function removeLoading() {
    const el = document.getElementById("loading");
    if (el) el.remove();
}

// ===============================
// Text-to-Speech
// ===============================

function speakMessage(id, btn) {
    const el = document.getElementById(id);
    if (!el) return;

    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
        document.querySelectorAll(".play-btn.playing").forEach(b => _setBtnIdle(b));
        return;
    }

    const utterance = new SpeechSynthesisUtterance(el.innerText);
    utterance.lang  = "en-US";
    utterance.rate  = 1;
    utterance.pitch = 1;

    _setBtnPlaying(btn);
    utterance.onend  = () => _setBtnIdle(btn);
    utterance.onerror = () => _setBtnIdle(btn);

    window.speechSynthesis.speak(utterance);
}

function _setBtnPlaying(btn) {
    btn.classList.add("playing");
    btn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="6" y="4" width="4" height="16"/>
            <rect x="14" y="4" width="4" height="16"/>
        </svg>
        Stop`;
}

function _setBtnIdle(btn) {
    btn.classList.remove("playing");
    btn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
        Play`;
}
