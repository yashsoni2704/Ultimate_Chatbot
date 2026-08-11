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

// Greeting chip
const userGreeting      = document.getElementById("userGreeting");
const userGreetingAvatar= document.getElementById("userGreetingAvatar");
const userGreetingName  = document.getElementById("userGreetingName");

// Autoplay toggle
const autoplayBtn   = document.getElementById("autoplayBtn");
const darkModeBtn   = document.getElementById("darkModeBtn");

// Lead capture modal
const leadModal      = document.getElementById("leadModal");
const leadModalClose = document.getElementById("leadModalClose");
const leadSkipBtn    = document.getElementById("leadSkipBtn");
const leadForm       = document.getElementById("leadForm");
const leadName       = document.getElementById("leadName");
const leadEmail      = document.getElementById("leadEmail");
const leadPhone      = document.getElementById("leadPhone");
const leadError      = document.getElementById("leadError");
const leadSubmitBtn  = document.getElementById("leadSubmitBtn");

let msgCounter       = 0;
let questionCount    = 0;          // messages sent this session
let leadFormShown    = false;      // only show once per session
let leadFormDismissed= false;      // user skipped — don't re-show

// ── Visitor UUID (persisted in localStorage) ──────────────────────────────
const LS_KEY          = "docmind_visitor_id";
const LS_AUTOPLAY_KEY = "docmind_autoplay";
let visitorId   = "";
let visitorName = "";

// ── Autoplay state ────────────────────────────────────────────────────────
let autoplayEnabled = localStorage.getItem(LS_AUTOPLAY_KEY) === "true";

// ── Dark mode state ───────────────────────────────────────────────────────
const LS_DARK_KEY   = "docmind_darkmode";
let darkModeEnabled = localStorage.getItem(LS_DARK_KEY) === "true";

// ── TTS language — resolved once at startup ───────────────────────────────
// Supported BCP-47 tags → Web Speech API lang codes.
// If the browser's language isn't in this map we fall back to en-US.
const SUPPORTED_LANGS = {
    "en":  "en-US",
    "hi":  "hi-IN",
    "es":  "es-ES",
    "fr":  "fr-FR",
    "de":  "de-DE",
    "pt":  "pt-BR",
    "ar":  "ar-SA",
    "ja":  "ja-JP",
    "zh":  "zh-CN",
    "it":  "it-IT",
    "ko":  "ko-KR",
    "ru":  "ru-RU",
};
let ttsLang = "en-US";   // resolved in detectTTSLanguage()

// ===============================
// On Page Load
// ===============================

window.addEventListener("load", () => {
    questionInput.focus();
    detectTTSLanguage();     // resolve browser language → ttsLang
    initAutoplay();          // restore toggle state + wire button
    initDarkMode();          // restore dark mode + wire button
    initVisitor();           // UUID + name handshake
    loadKnowledgeBase();
    startKbPolling();
    wireLeadModal();
});

// ===============================
// TTS Language Detection
// Runs once at page load — reads navigator.languages / navigator.language,
// matches against SUPPORTED_LANGS, falls back to en-US if not found.
// ===============================

function detectTTSLanguage() {
    const preferred = (navigator.languages && navigator.languages.length)
        ? [...navigator.languages]
        : [navigator.language || "en"];

    for (const lang of preferred) {
        // Try full tag first (e.g. "hi-IN"), then base code (e.g. "hi")
        const full = lang.toLowerCase().replace("_", "-");
        const base = full.split("-")[0];

        if (SUPPORTED_LANGS[full]) {
            ttsLang = SUPPORTED_LANGS[full];
            console.log(`[TTS] Language detected: ${lang} → ${ttsLang}`);
            return;
        }
        if (SUPPORTED_LANGS[base]) {
            ttsLang = SUPPORTED_LANGS[base];
            console.log(`[TTS] Language detected: ${lang} → ${ttsLang}`);
            return;
        }
    }
    // Nothing matched — stay on en-US
    console.log(`[TTS] No supported language matched (${preferred[0]}) — using en-US`);
}

// ===============================
// Autoplay Toggle
// ===============================

function initAutoplay() {
    _renderToggle(autoplayBtn, autoplayEnabled);
    autoplayBtn.addEventListener("click", () => {
        autoplayEnabled = !autoplayEnabled;
        localStorage.setItem(LS_AUTOPLAY_KEY, autoplayEnabled);
        _renderToggle(autoplayBtn, autoplayEnabled);
    });
}

function _renderToggle(btn, state) {
    btn.setAttribute("aria-checked", state ? "true" : "false");
}

// ===============================
// Dark Mode Toggle
// ===============================

const MOON_SVG = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>`;
const SUN_SVG  = `<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>`;

function initDarkMode() {
    if (darkModeEnabled) document.body.classList.add("dark-mode");
    _renderToggle(darkModeBtn, darkModeEnabled);
    _swapDarkIcon(darkModeEnabled);

    darkModeBtn.addEventListener("click", () => {
        darkModeEnabled = !darkModeEnabled;
        localStorage.setItem(LS_DARK_KEY, darkModeEnabled);
        document.body.classList.toggle("dark-mode", darkModeEnabled);
        _renderToggle(darkModeBtn, darkModeEnabled);
        _swapDarkIcon(darkModeEnabled);
    });
}

function _swapDarkIcon(isDark) {
    const icon = document.getElementById("darkModeIcon");
    if (!icon) return;
    icon.innerHTML = isDark ? SUN_SVG : MOON_SVG;
}

// ===============================
// UUID / Visitor Handshake
// ===============================

async function initVisitor() {
    try {
        // Read stored UUID (may be empty on first visit)
        const storedId = localStorage.getItem(LS_KEY) || "";

        const res  = await fetch("/init-session", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ visitor_id: storedId }),
        });
        const data = await res.json();

        if (data.status === "success") {
            visitorId = data.visitor_id;

            // Persist UUID so every future visit reuses the same identity
            localStorage.setItem(LS_KEY, visitorId);

            // If backend has a name or email, mark as already identified
            if (data.name) {
                visitorName = data.name;
                showGreeting(visitorName);
                leadFormShown     = true;
                leadFormDismissed = true;
            } else {
                // Check if they filled the dislike contact form in a previous session
                try {
                    const r = await fetch("/get-user-info");
                    const d = await r.json();
                    if (d.user_info && (d.user_info.name || d.user_info.email)) {
                        leadFormShown     = true;
                        leadFormDismissed = true;
                        if (d.user_info.name) {
                            visitorName = d.user_info.name;
                            showGreeting(visitorName);
                        }
                    }
                } catch (_) {}
            }
        }
    } catch (e) {
        // Non-fatal — chat still works without tracking
        console.warn("initVisitor failed:", e);
    }
}

// ===============================
// Greeting Chip
// ===============================

function showGreeting(name) {
    if (!name) return;
    const display = name.trim();
    const initial = display.charAt(0).toUpperCase();

    userGreetingAvatar.textContent = initial;
    userGreetingName.textContent   = "Hi, " + display + "!";
    userGreeting.style.display     = "flex";

    // Animate in
    userGreeting.classList.remove("greeting-in");
    void userGreeting.offsetWidth;   // reflow to restart animation
    userGreeting.classList.add("greeting-in");
}

// ===============================
// Lead-Capture Modal Logic
// ===============================

function wireLeadModal() {
    if (leadModalClose) leadModalClose.addEventListener("click", dismissLeadModal);
    if (leadSkipBtn)    leadSkipBtn.addEventListener("click",    dismissLeadModal);
    if (leadModal)      leadModal.addEventListener("click", (e) => {
        if (e.target === leadModal) dismissLeadModal();
    });
    if (leadForm) leadForm.addEventListener("submit", submitLeadForm);

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && leadModal && leadModal.style.display !== "none") {
            dismissLeadModal();
        }
    });
}

async function maybeShowLeadForm() {
    if (leadFormShown || leadFormDismissed) return;
    // Show after the 3rd question
    if (questionCount < 3) return;

    // Don't show if user already gave details (from dislike contact form or previous session)
    try {
        const res  = await fetch("/get-user-info");
        const data = await res.json();
        if (data.user_info && (data.user_info.name || data.user_info.email)) {
            // Already have their details — no need to ask again
            leadFormShown     = true;
            leadFormDismissed = true;
            // Show greeting if we have a name and haven't shown it yet
            if (data.user_info.name && !visitorName) {
                visitorName = data.user_info.name;
                showGreeting(visitorName);
            }
            return;
        }
    } catch (_) {}

    leadFormShown = true;
    showLeadModal();
}

function showLeadModal() {
    if (!leadModal) return;
    leadModal.style.display = "flex";
    // Small delay so the transition feels smooth after the bot reply appears
    requestAnimationFrame(() => {
        leadModal.classList.add("lead-modal-visible");
        setTimeout(() => { if (leadName) leadName.focus(); }, 120);
    });
}

function dismissLeadModal() {
    if (!leadModal) return;
    leadFormDismissed = true;
    leadModal.classList.remove("lead-modal-visible");
    setTimeout(() => { leadModal.style.display = "none"; }, 280);
}

async function submitLeadForm(e) {
    e.preventDefault();

    const name  = (leadName?.value  || "").trim();
    const email = (leadEmail?.value || "").trim();
    const phone = (leadPhone?.value || "").trim();

    if (!name && !email && !phone) {
        showLeadError("Please fill in at least one field.");
        return;
    }

    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showLeadError("Please enter a valid email address.");
        return;
    }

    hideLeadError();
    setLeadSubmitting(true);

    try {
        const res  = await fetch("/update-visitor", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ visitor_id: visitorId, name, email, phone }),
        });
        const data = await res.json();

        if (data.status === "success") {
            visitorName = name || visitorName;
            if (visitorName) showGreeting(visitorName);
            dismissLeadModal();
        } else {
            showLeadError(data.message || "Something went wrong. Please try again.");
        }
    } catch (err) {
        showLeadError("Network error. Please try again.");
    } finally {
        setLeadSubmitting(false);
    }
}

function showLeadError(msg) {
    if (!leadError) return;
    leadError.textContent   = msg;
    leadError.style.display = "block";
}

function hideLeadError() {
    if (!leadError) return;
    leadError.textContent   = "";
    leadError.style.display = "none";
}

function setLeadSubmitting(loading) {
    if (!leadSubmitBtn) return;
    leadSubmitBtn.disabled   = loading;
    leadSubmitBtn.innerHTML  = loading
        ? `<span class="lead-btn-spinner"></span> Saving…`
        : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Save &amp; Continue`;
}

// ===============================
// Knowledge Base Polling
// ===============================

let _kbPollInterval = null;
let _kbLastCount    = -1;

function startKbPolling() {
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
            if (count !== _kbLastCount) {
                _kbLastCount = count;
                loadKnowledgeBase();
            }
        })
        .catch(() => {});
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
            _kbLastCount = docs.length;
            kbCount.textContent = docs.length + (docs.length === 1 ? " doc" : " docs");

            if (docs.length === 0) {
                kbEmpty.style.display = "flex";
                docBadgeText.textContent = "No documents loaded";
                documentStatus.classList.remove("loaded");
                welcomeTitle.textContent    = "No documents loaded yet";
                welcomeSubtitle.textContent = "Ask your admin to upload documents to the knowledge base.";
                return;
            }

            kbList.innerHTML = "";
            docs.forEach(doc => renderKbItem(doc));
            kbList.style.display = "flex";

            docBadgeText.textContent = docs.length + (docs.length === 1 ? " document" : " documents") + " available";
            documentStatus.classList.add("loaded");

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
    questionCount++;

    askBtn.disabled           = true;
    questionInput.placeholder = "Ask anything about your documents…";

    const t_start = Date.now();
    addLoading();

    fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, visitor_id: visitorId })
    })
    .then(r => r.json())
    .then(result => {
        const elapsed_ms = result.elapsed_ms || (Date.now() - t_start);
        removeLoading();
        addBotMessage(
            result.status === "success" ? result.answer : "❌ " + result.message,
            elapsed_ms,
            result.chat_log_id || "",
            question
        );
        _enableInput();
        setTimeout(() => {
            autoScrollChat();
            questionInput.focus();
            maybeShowLeadForm();
        }, 120);
    })
    .catch(err => {
        removeLoading();
        addBotMessage("❌ " + err.message, null, "", question);
        _enableInput();
        setTimeout(() => {
            autoScrollChat();
            questionInput.focus();
            maybeShowLeadForm();
        }, 120);
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

function addBotMessage(rawText, elapsed_ms, chatLogId, rawQuestion) {
    msgCounter++;
    const speechId   = "speech_"    + msgCounter;
    const feedbackId = "feedback_"  + msgCounter;

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

    const timingHtml = (elapsed_ms != null)
        ? `<span class="answer-timing">⏱ ${elapsed_ms >= 1000 ? (elapsed_ms / 1000).toFixed(1) + "s" : elapsed_ms + "ms"}</span>`
        : "";

    // Wrap any markdown tables in a scrollable div for clean overflow on small screens
    bodyHtml = bodyHtml.replace(/<table/g, '<div class="table-wrap"><table').replace(/<\/table>/g, '</table></div>');

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
            ${timingHtml}
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
            <div class="feedback-group" id="${feedbackId}">
                <button class="feedback-btn like-btn" title="Helpful" aria-label="Like">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/>
                        <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                    </svg>
                    <span class="feedback-count"></span>
                </button>
                <button class="feedback-btn dislike-btn" title="Not helpful" aria-label="Dislike">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/>
                        <path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>
                    </svg>
                    <span class="feedback-count"></span>
                </button>
            </div>
        </div>`;

    // Store chat_log_id on the card — set after /chat response arrives
    card.dataset.chatLogId  = chatLogId || "";
    card.dataset.question   = rawQuestion || "";
    card.dataset.feedbackId = feedbackId;

    chatBox.appendChild(card);

    // Wire like/dislike buttons
    _wireFeedbackButtons(card, rawText);

    if (typeof hljs !== "undefined") {
        card.querySelectorAll("pre code").forEach(block => hljs.highlightElement(block));
    }

    autoScrollChat();

    // ── Autoplay ──────────────────────────────────────────────
    if (autoplayEnabled) {
        setTimeout(() => {
            const playBtn = card.querySelector(".play-btn");
            speakMessage(speechId, playBtn);
        }, 150);
    }

    return card;   // return so caller can set chat_log_id after the response arrives
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
    utterance.lang  = ttsLang;   // browser-detected language (en-US fallback)
    utterance.rate  = 1;
    utterance.pitch = 1;

    _setBtnPlaying(btn);
    utterance.onend   = () => _setBtnIdle(btn);
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


// ===============================================================
// MIC / VOICE INPUT  — Web Speech API (browser-native)
//
// - Hold Space 3s → ring fills → mic activates
// - Release Space before 3s → cancel
// - Speech prints into input in real time
// - MIC_SILENCE_TIMEOUT seconds (from .env) of silence → mic closes
// - Click Send when ready
// ===============================================================

(function () {
    "use strict";

    const micWrapper     = document.getElementById("micWrapper");
    const micBtn         = document.getElementById("micBtn");
    const micRingFill    = document.getElementById("micRingFill");
    const micStatusLabel = document.getElementById("micStatusLabel");
    const chatInput      = document.getElementById("question");

    if (!micWrapper || !micBtn || !micRingFill || !chatInput) return;

    // ── Browser support ──────────────────────────────────────────
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        micBtn.title         = "Voice input not supported in this browser";
        micBtn.style.opacity = "0.4";
        micBtn.style.cursor  = "not-allowed";
        return;
    }

    // ── Tuning ───────────────────────────────────────────────────
    const RING_CIRC = 119.4;
    const HOLD_MS   = 3000;
    const TICK_MS   = 50;

    // Silence timeout — loaded from .env via /client-config, default 3s
    let SILENCE_MS = 3000;
    fetch("/client-config")
        .then(r => r.json())
        .then(d => { if (d.mic_silence_timeout) SILENCE_MS = d.mic_silence_timeout * 1000; })
        .catch(() => {});

    // ── State ────────────────────────────────────────────────────
    let countdownTimer = null;
    let countdownStart = null;
    let spaceHeld      = false;
    let isRecording    = false;
    let silenceTimer   = null;
    let recognition    = null;
    let committed      = "";   // text already permanently in input

    // ── UI ───────────────────────────────────────────────────────
    function showStatus(msg) {
        if (!micStatusLabel) return;
        micStatusLabel.textContent = msg;
        micStatusLabel.classList.remove("hidden");
    }
    function hideStatus() {
        if (!micStatusLabel) return;
        micStatusLabel.textContent = "";
        micStatusLabel.classList.add("hidden");
    }
    function setRing(frac) {
        micRingFill.style.strokeDashoffset = RING_CIRC * (1 - Math.min(frac, 1));
    }
    function clearRing() {
        micRingFill.style.strokeDashoffset = RING_CIRC;
        micWrapper.classList.remove("counting");
    }

    // ── Silence timer ────────────────────────────────────────────
    // Reset every time a final word arrives.
    // When it fires, we own the stop — not the browser.
    function armSilence() {
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {
            if (isRecording) stopRecording();
        }, SILENCE_MS);
    }

    // ── Recognition — attach & restart loop ──────────────────────
    // The browser's SpeechRecognition fires onend after its own
    // short silence (~1-2s). We restart immediately so our own
    // SILENCE_MS timer is the only thing that actually stops the mic.
    function attachRecognition() {
        if (!isRecording) return;

        recognition = new SpeechRecognition();
        recognition.continuous     = true;
        recognition.interimResults = true;
        recognition.lang           = "en-US";

        recognition.onresult = (e) => {
            let interim   = "";
            let finalPart = "";

            for (let i = e.resultIndex; i < e.results.length; i++) {
                const t = e.results[i][0].transcript;
                if (e.results[i].isFinal) finalPart += t;
                else                      interim   += t;
            }

            // Any speech activity (interim or final) resets the silence clock
            armSilence();

            if (finalPart) {
                const sep = committed.trimEnd() ? " " : "";
                committed = committed.trimEnd() + sep + finalPart.trim();
                chatInput.value = committed;
            }
            if (interim) {
                const sep = committed.trimEnd() ? " " : "";
                chatInput.value = committed.trimEnd() + sep + interim;
            }
        };
        recognition.onerror = (e) => {
            if (e.error === "aborted") return;       // we called stop() ourselves
            if (e.error === "no-speech") {
                restartRecognition();                // browser timed out — restart
                return;
            }
            console.warn("[mic] error:", e.error);
            stopRecording();
        };

        recognition.onend = () => {
            // Browser ended its session — restart to keep ours alive
            restartRecognition();
        };

        try { recognition.start(); } catch (_) {}
    }

    function restartRecognition() {
        if (!isRecording) return;
        setTimeout(attachRecognition, 150);   // brief gap avoids "already started"
    }

    // ── Start / stop ─────────────────────────────────────────────
    function startRecording() {
        if (isRecording) return;
        isRecording = true;
        committed   = chatInput.value;   // keep any text already typed

        micWrapper.classList.remove("counting");
        micWrapper.classList.add("recording");
        showStatus("🎙 Listening…");

        attachRecognition();
        // Do NOT arm silence here — only start the clock once speech begins
    }

    function stopRecording() {
        if (!isRecording) return;
        isRecording = false;

        clearTimeout(silenceTimer);
        micWrapper.classList.remove("recording");
        hideStatus();

        if (recognition) {
            recognition.onend   = null;    // prevent auto-restart
            recognition.onerror = null;
            try { recognition.stop(); } catch (_) {}
            recognition = null;
        }

        // Log to server
        const finalText = chatInput.value.trim();
        if (finalText) {
            fetch("/log-voice", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ text: finalText })
            }).catch(() => {});
        }
    }

    // ── 3-second countdown ───────────────────────────────────────
    function beginCountdown() {
        countdownStart = Date.now();
        micWrapper.classList.add("counting");
        showStatus("Hold Space…");

        countdownTimer = setInterval(() => {
            const frac = (Date.now() - countdownStart) / HOLD_MS;
            setRing(frac);
            if (frac >= 1) {
                clearInterval(countdownTimer);
                countdownTimer = null;
                clearRing();
                startRecording();
            }
        }, TICK_MS);
    }

    function cancelCountdown() {
        clearInterval(countdownTimer);
        countdownTimer = null;
        clearRing();
        hideStatus();
    }

    // ── Spacebar ─────────────────────────────────────────────────
    document.addEventListener("keydown", (e) => {
        if (e.code !== "Space" || e.repeat) return;

        const active  = document.activeElement;
        const inField = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");

        // Block countdown whenever ANY input/textarea has focus — user is typing
        if (inField && !isRecording) return;

        // Also block if focus is inside any modal
        if (active && (
            active.closest(".lead-modal") ||
            active.closest(".support-modal") ||
            active.closest(".dissat-inline-form")
        )) return;

        e.preventDefault();
        if (isRecording)  { stopRecording();  return; }
        if (!spaceHeld)   { spaceHeld = true; beginCountdown(); }
    });

    document.addEventListener("keyup", (e) => {
        if (e.code !== "Space") return;
        spaceHeld = false;
        if (countdownTimer) cancelCountdown();   // released before 3s → cancel
    });

    document.addEventListener("keypress", (e) => {
        if (e.code === "Space" && (isRecording || countdownTimer)) e.preventDefault();
    });

    // ── Mic button ───────────────────────────────────────────────
    micBtn.addEventListener("click", () => {
        if (countdownTimer)   cancelCountdown();
        else if (isRecording) stopRecording();
        else                  startRecording();
    });

}());


// ===============================================================
// SATISFACTION & LLM SWITCHING SYSTEM
// ===============================================================

// ── State ────────────────────────────────────────────────────────
let _currentLlmMode  = "primary";   // "primary" | "secondary"
let _supportEmail    = "yashrakeshsoni@gmail.com";

// ── DOM refs ─────────────────────────────────────────────────────
const supportModal       = document.getElementById("supportModal");
const supportModalClose  = document.getElementById("supportModalClose");
const supportCancelBtn   = document.getElementById("supportCancelBtn");
const supportForm        = document.getElementById("supportForm");
const supportName        = document.getElementById("supportName");
const supportEmail       = document.getElementById("supportEmail");
const supportPhone       = document.getElementById("supportPhone");
const supportError       = document.getElementById("supportError");
const supportSubmitBtn   = document.getElementById("supportSubmitBtn");
const supportAlreadyFilled = document.getElementById("supportAlreadyFilled");
const supportFilledName  = document.getElementById("supportFilledName");
const supportFilledEmail = document.getElementById("supportFilledEmail");
const supportEmailChip   = document.getElementById("supportEmailChip");
const supportEmailText   = document.getElementById("supportEmailText");

// ── Wire support modal ───────────────────────────────────────────
if (supportModalClose) supportModalClose.addEventListener("click", closeSupportModal);
if (supportCancelBtn)  supportCancelBtn.addEventListener("click",  closeSupportModal);
if (supportModal)      supportModal.addEventListener("click", (e) => {
    if (e.target === supportModal) closeSupportModal();
});
if (supportForm) supportForm.addEventListener("submit", submitSupportForm);

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && supportModal &&
        supportModal.classList.contains("support-modal-visible")) {
        closeSupportModal();
    }
});

// ── Open / close ─────────────────────────────────────────────────
function openSupportModal(email) {
    if (!supportModal) return;

    // Update email chip
    const resolvedEmail = email || _supportEmail;
    if (supportEmailChip) supportEmailChip.href = "mailto:" + resolvedEmail;
    if (supportEmailText) supportEmailText.textContent = resolvedEmail;

    // Check if user already filled the form
    fetch("/get-user-info")
        .then(r => r.json())
        .then(data => {
            const info = data.user_info;
            if (info && (info.name || info.email)) {
                // Show personalised message
                _showAlreadyFilledState(info);
            } else {
                // Show fresh form
                _showFreshFormState();
            }
            // Reveal modal
            supportModal.classList.add("support-modal-visible");
            setTimeout(() => {
                if (supportName && supportForm.style.display !== "none") supportName.focus();
            }, 200);
        })
        .catch(() => {
            _showFreshFormState();
            supportModal.classList.add("support-modal-visible");
        });
}

function closeSupportModal() {
    if (!supportModal) return;
    supportModal.classList.remove("support-modal-visible");
}

function _showAlreadyFilledState(info) {
    if (!supportAlreadyFilled || !supportForm) return;
    if (supportFilledName)  supportFilledName.textContent  = "Hello " + (info.name || "there") + "! 👋";
    if (supportFilledEmail) supportFilledEmail.textContent = info.email || "";
    supportAlreadyFilled.style.display = "flex";
    supportForm.style.display          = "none";
}

function _showFreshFormState() {
    if (!supportAlreadyFilled || !supportForm) return;
    supportAlreadyFilled.style.display = "none";
    supportForm.style.display          = "flex";
}

// ── Submit support form ──────────────────────────────────────────
async function submitSupportForm(e) {
    e.preventDefault();

    const name  = (supportName?.value  || "").trim();
    const email = (supportEmail?.value || "").trim();
    const phone = (supportPhone?.value || "").trim();

    if (!name && !email) {
        _showSupportError("Please enter your name or email.");
        return;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        _showSupportError("Please enter a valid email address.");
        return;
    }

    _hideSupportError();
    _setSupportSubmitting(true);

    try {
        const res  = await fetch("/submit-contact-form", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ name, email, phone }),
        });
        const data = await res.json();

        if (data.status === "success") {
            // Switch to personalised state
            _showAlreadyFilledState({ name, email });
            // Update greeting chip if name provided
            if (name) showGreeting(name);
        } else {
            _showSupportError(data.message || "Something went wrong. Please try again.");
        }
    } catch (err) {
        _showSupportError("Network error. Please try again.");
    } finally {
        _setSupportSubmitting(false);
    }
}

function _showSupportError(msg) {
    if (!supportError) return;
    supportError.textContent   = msg;
    supportError.style.display = "block";
}
function _hideSupportError() {
    if (!supportError) return;
    supportError.textContent   = "";
    supportError.style.display = "none";
}
function _setSupportSubmitting(loading) {
    if (!supportSubmitBtn) return;
    supportSubmitBtn.disabled  = loading;
    supportSubmitBtn.innerHTML = loading
        ? `<span class="lead-btn-spinner"></span> Sending…`
        : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Send Request`;
}

// ── Satisfaction prompt — render below a bot message ─────────────
function showSatisfactionPrompt(email) {
    // Remove any existing prompt first (only one at a time)
    const old = document.querySelector(".satisfaction-prompt");
    if (old) old.remove();

    const prompt = document.createElement("div");
    prompt.className = "satisfaction-prompt";

    prompt.innerHTML = `
        <div class="satisfaction-prompt-text">
            <span class="sat-emoji">😊</span>
            Are you satisfied with this answer?
        </div>
        <div class="satisfaction-prompt-actions">
            <button class="sat-btn sat-btn-yes" id="satBtnYes">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14">
                    <polyline points="20 6 9 17 4 12"/>
                </svg>
                Yes, helpful!
            </button>
            <button class="sat-btn sat-btn-no" id="satBtnNo">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                No, try better
            </button>
            <button class="sat-btn sat-btn-skip" id="satBtnSkip">Skip</button>
        </div>`;

    chatBox.appendChild(prompt);
    autoScrollChat();

    // Auto-dismiss after 12 seconds if user does nothing
    const autoDismiss = setTimeout(() => {
        if (prompt.isConnected) prompt.remove();
    }, 12000);

    // Yes — satisfied, keep current LLM
    prompt.querySelector("#satBtnYes").addEventListener("click", () => {
        clearTimeout(autoDismiss);
        prompt.remove();
        _handleSatisfaction(true, email);
    });

    // No — not satisfied, try switching LLM
    prompt.querySelector("#satBtnNo").addEventListener("click", () => {
        clearTimeout(autoDismiss);
        prompt.remove();
        _handleSatisfaction(false, email);
    });

    // Skip — dismiss silently
    prompt.querySelector("#satBtnSkip").addEventListener("click", () => {
        clearTimeout(autoDismiss);
        prompt.remove();
    });
}

// ── Handle satisfaction API call ─────────────────────────────────
async function _handleSatisfaction(satisfied, email) {
    try {
        const res  = await fetch("/submit-satisfaction", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ satisfied }),
        });
        const data = await res.json();

        if (data.status !== "success") return;

        const newMode    = data.llm_mode    || _currentLlmMode;
        const showContact = data.show_contact || false;
        const resolvedEmail = data.support_email || email || _supportEmail;

        if (resolvedEmail) _supportEmail = resolvedEmail;

        // If LLM was switched, show a badge in the chat
        if (!satisfied && newMode !== _currentLlmMode) {
            _currentLlmMode = newMode;
            _showLlmSwitchBadge(newMode);
        }

        // If still unsatisfied after secondary, show contact modal
        if (showContact) {
            setTimeout(() => openSupportModal(resolvedEmail), 400);
        }

    } catch (err) {
        console.warn("Satisfaction submit failed:", err);
    }
}

// ── LLM switch badge in chat ─────────────────────────────────────
function _showLlmSwitchBadge(mode) {
    const badge = document.createElement("div");
    badge.className = "llm-switch-badge";
    badge.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="17 1 21 5 17 9"/>
            <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
            <polyline points="7 23 3 19 7 15"/>
            <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
        </svg>
        Switched to enhanced model for better answers`;
    chatBox.appendChild(badge);
    autoScrollChat();
}

// ── Hook into sendMessage to consume the flags ───────────────────
// Patch the existing .then() handler by overriding sendMessage

const _originalSendMessage = sendMessage;

// Override sendMessage to intercept satisfaction flags from /chat response
(function patchSendMessage() {
    // Remove old listener, re-add with patched handler
    askBtn.removeEventListener("click", sendMessage);
    questionInput.removeEventListener("keypress", _kpHandler);

    window.sendMessage = function sendMessage() {
        const question = questionInput.value.trim();
        if (!question) return;

        if (welcomeState) welcomeState.style.display = "none";

        addUserMessage(question);
        questionInput.value = "";
        questionCount++;

        askBtn.disabled           = true;
        questionInput.placeholder = "Ask anything about your documents…";

        const t_start = Date.now();
        addLoading();

        fetch("/chat", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ question, visitor_id: visitorId }),
        })
        .then(r => r.json())
        .then(result => {
            const elapsed_ms = result.elapsed_ms || (Date.now() - t_start);
            removeLoading();
            const botCard = addBotMessage(
                result.status === "success" ? result.answer : "❌ " + result.message,
                elapsed_ms,
                result.chat_log_id || "",
                question
            );
            _enableInput();

            // Sync LLM mode from server response
            if (result.llm_mode) _currentLlmMode = result.llm_mode;
            if (result.support_email) _supportEmail = result.support_email;

            setTimeout(() => {
                autoScrollChat();
                questionInput.focus();
                maybeShowLeadForm();

                // Show satisfaction prompt if backend signals it
                if (result.show_satisfaction_prompt) {
                    setTimeout(() => {
                        showSatisfactionPrompt(result.support_email || _supportEmail);
                    }, 600);
                }
            }, 120);
        })
        .catch(err => {
            removeLoading();
            addBotMessage("❌ " + err.message, null, "", question);
            _enableInput();
            setTimeout(() => {
                autoScrollChat();
                questionInput.focus();
                maybeShowLeadForm();
            }, 120);
        });
    };

    askBtn.addEventListener("click", window.sendMessage);
    questionInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !askBtn.disabled) window.sendMessage();
    });
}());

// Store keypress handler ref for cleanup (needed by patchSendMessage)
function _kpHandler(e) {
    if (e.key === "Enter" && !askBtn.disabled) sendMessage();
}


// ===============================================================
// LIKE / DISLIKE FEEDBACK SYSTEM
// ===============================================================

// Session-level dislike counter (also confirmed server-side)
let _sessionDislikeCount = 0;
const DISLIKE_THRESHOLD  = 2;

/**
 * Wire like/dislike buttons on a bot message card.
 * chatLogId is set on card.dataset.chatLogId (may be "" until /chat responds).
 */
function _wireFeedbackButtons(card, rawAnswer) {
    const likeBtn    = card.querySelector(".like-btn");
    const dislikeBtn = card.querySelector(".dislike-btn");

    if (!likeBtn || !dislikeBtn) return;

    likeBtn.addEventListener("click",    () => _handleFeedback(card, "like",    rawAnswer));
    dislikeBtn.addEventListener("click", () => _handleFeedback(card, "dislike", rawAnswer));
}

async function _handleFeedback(card, feedback, rawAnswer) {
    const chatLogId = card.dataset.chatLogId || "";
    const question  = card.dataset.question  || "";
    const likeBtn    = card.querySelector(".like-btn");
    const dislikeBtn = card.querySelector(".dislike-btn");

    // Determine previous state
    const wasLiked    = likeBtn.classList.contains("active");
    const wasDisliked = dislikeBtn.classList.contains("active");
    const isSameClick = (feedback === "like" && wasLiked) ||
                        (feedback === "dislike" && wasDisliked);

    // Toggle off if clicking the same button again
    if (isSameClick) {
        likeBtn.classList.remove("active");
        dislikeBtn.classList.remove("active");
        // Still send to backend to flip the record
    }

    // Ripple animation
    const btn = feedback === "like" ? likeBtn : dislikeBtn;
    btn.classList.remove("ripple");
    void btn.offsetWidth;
    btn.classList.add("ripple");
    setTimeout(() => btn.classList.remove("ripple"), 500);

    // Update active state immediately for instant feel
    likeBtn.classList.toggle("active",    feedback === "like"    && !isSameClick);
    dislikeBtn.classList.toggle("active", feedback === "dislike" && !isSameClick);

    // No chat_log_id yet (error case) — still animate, skip API
    if (!chatLogId) return;

    try {
        const res  = await fetch("/chat-feedback", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({
                chat_log_id: chatLogId,
                feedback:    isSameClick ? "like" : feedback,  // flipping same = treat as neutral→like
                question,
                answer: rawAnswer,
            }),
        });
        const data = await res.json();
        if (data.status !== "success") return;

        if (feedback === "dislike" && !isSameClick) {
            _sessionDislikeCount = data.dislike_count || (_sessionDislikeCount + 1);
        }

        // If threshold reached, show inline contact card below this message
        // show_contact can fire on 2nd, 3rd, 4th... dislike — always re-show
        if (data.show_contact && feedback === "dislike" && !isSameClick) {
            const old = document.querySelector(".dissat-contact-card");
            if (old) old.remove();
            _insertDissatCard(card, data.support_email || _supportEmail);
        }

    } catch (err) {
        console.warn("Feedback submit failed:", err);
    }
}

/**
 * Insert inline dissatisfied contact card right after the bot message card.
 * Checks /get-user-info first — shows personalised msg if form already filled.
 */
async function _insertDissatCard(afterCard, email) {
    const resolvedEmail = email || _supportEmail || "yashrakeshsoni@gmail.com";

    // Check if user already filled the form
    let userInfo = null;
    try {
        const r = await fetch("/get-user-info");
        const d = await r.json();
        userInfo = d.user_info || null;
    } catch (_) {}

    const card = document.createElement("div");
    card.className = "dissat-contact-card";

    const alreadyFilled = userInfo && (userInfo.name || userInfo.email);

    card.innerHTML = `
        <div class="dissat-card-header">
            <div class="dissat-card-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M16 16s-1.5-2-4-2-4 2-4 2"/>
                    <line x1="9" y1="9" x2="9.01" y2="9"/>
                    <line x1="15" y1="9" x2="15.01" y2="9"/>
                </svg>
            </div>
            <div class="dissat-card-text">
                <h4>We noticed you're not finding the answers helpful</h4>
                <p>Our team can help you personally. Reach out directly or leave your details.</p>
            </div>
        </div>

        <a href="mailto:${resolvedEmail}" class="dissat-email-row" target="_blank">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
                <polyline points="22,6 12,13 2,6"/>
            </svg>
            <span>${resolvedEmail}</span>
        </a>

        ${alreadyFilled
            ? `<div class="dissat-already-row">
                 <strong>Hello ${userInfo.name || "there"}!</strong>
                 We will contact you at <strong>${userInfo.email || ""}</strong> for personal query resolution.
               </div>`
            : `<button class="dissat-form-toggle" id="dissatFormToggle">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                    <circle cx="12" cy="7" r="4"/>
                </svg>
                Fill contact form for personal assistance
               </button>
               <div class="dissat-inline-form" id="dissatInlineForm" style="display:none;">
                 <div class="lead-field">
                   <label class="lead-label">Name</label>
                   <input type="text" class="lead-input" id="dissatName" placeholder="Your name" autocomplete="name"/>
                 </div>
                 <div class="lead-field">
                   <label class="lead-label">Email</label>
                   <input type="email" class="lead-input" id="dissatEmail" placeholder="your@email.com" autocomplete="email"/>
                 </div>
                 <div class="lead-field">
                   <label class="lead-label">Phone <span style="font-weight:400;color:#b0bec5">(optional)</span></label>
                   <input type="tel" class="lead-input" id="dissatPhone" placeholder="+91 98765 43210" autocomplete="tel"/>
                 </div>
                 <div id="dissatError" class="dissat-error" style="display:none;"></div>
                 <div class="dissat-form-row">
                   <button class="dissat-cancel-btn" id="dissatCancelBtn">Cancel</button>
                   <button class="dissat-submit-btn" id="dissatSubmitBtn">
                     <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                     Submit
                   </button>
                 </div>
               </div>`
        }`;

    // Insert after the bot card
    afterCard.insertAdjacentElement("afterend", card);
    autoScrollChat();

    if (alreadyFilled) return;

    // Wire form toggle
    const toggle     = card.querySelector("#dissatFormToggle");
    const formDiv    = card.querySelector("#dissatInlineForm");
    const cancelBtn  = card.querySelector("#dissatCancelBtn");
    const submitBtn  = card.querySelector("#dissatSubmitBtn");
    const errDiv     = card.querySelector("#dissatError");
    const nameInput  = card.querySelector("#dissatName");
    const emailInput = card.querySelector("#dissatEmail");
    const phoneInput = card.querySelector("#dissatPhone");

    toggle.addEventListener("click", () => {
        formDiv.style.display = formDiv.style.display === "none" ? "flex" : "none";
        toggle.style.display  = "none";
        setTimeout(() => nameInput && nameInput.focus(), 50);
    });

    cancelBtn.addEventListener("click", () => {
        formDiv.style.display = "none";
        toggle.style.display  = "flex";
    });

    submitBtn.addEventListener("click", async () => {
        const name  = (nameInput?.value  || "").trim();
        const email = (emailInput?.value || "").trim();
        const phone = (phoneInput?.value || "").trim();

        if (!name && !email) {
            errDiv.textContent   = "Please enter your name or email.";
            errDiv.style.display = "block";
            return;
        }
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            errDiv.textContent   = "Please enter a valid email address.";
            errDiv.style.display = "block";
            return;
        }
        errDiv.style.display = "none";
        submitBtn.disabled   = true;
        submitBtn.innerHTML  = `<span class="lead-btn-spinner"></span> Sending…`;

        try {
            const res  = await fetch("/submit-contact-form", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ name, email, phone }),
            });
            const data = await res.json();

            if (data.status === "success") {
                // Replace form with personalised confirmation
                formDiv.style.display  = "none";
                if (toggle) toggle.style.display = "none";

                // Insert thank you row
                const thankYou = document.createElement("div");
                thankYou.className = "dissat-already-row";
                thankYou.innerHTML = `<strong>Hello ${name || "there"}.</strong> We will contact you at <strong>${email}</strong> for personal query resolution.`;
                formDiv.insertAdjacentElement("afterend", thankYou);

                // Update greeting chip
                if (name) showGreeting(name);
                autoScrollChat();
            } else {
                errDiv.textContent   = data.message || "Something went wrong.";
                errDiv.style.display = "block";
            }
        } catch (e) {
            errDiv.textContent   = "Network error. Please try again.";
            errDiv.style.display = "block";
        } finally {
            submitBtn.disabled  = false;
            submitBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Send`;
        }
    });
}
