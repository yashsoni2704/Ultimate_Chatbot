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

            // If backend has a name, show greeting immediately
            if (data.name) {
                visitorName = data.name;
                showGreeting(visitorName);
                leadFormShown    = true;   // already identified — no need to ask
                leadFormDismissed= true;
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

function maybeShowLeadForm() {
    if (leadFormShown || leadFormDismissed) return;
    // Show after the 3rd question
    if (questionCount < 3) return;

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

    addLoading();

    fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, visitor_id: visitorId })
    })
    .then(r => r.json())
    .then(result => {
        removeLoading();
        addBotMessage(result.status === "success" ? result.answer : "❌ " + result.message);
        _enableInput();
        setTimeout(() => {
            autoScrollChat();
            questionInput.focus();
            // Try to show lead form after bot response (feels more natural)
            maybeShowLeadForm();
        }, 120);
    })
    .catch(err => {
        removeLoading();
        addBotMessage("❌ " + err.message);
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

    // ── Autoplay ──────────────────────────────────────────────
    if (autoplayEnabled) {
        // Small delay so the card is painted first
        setTimeout(() => {
            const playBtn = card.querySelector(".play-btn");
            speakMessage(speechId, playBtn);
        }, 150);
    }
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
        if (inField && chatInput.value.length > 0 && !isRecording) return;
        if (active && active.closest(".lead-modal")) return;

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
