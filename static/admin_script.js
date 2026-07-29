// ============================================================
//  DocMind Admin Panel — JavaScript
//  Handles: drag-drop, file type detection, upload, KB list, delete
// ============================================================

// ── API base (admin_app.py runs on port 5001, routes prefixed /admin) ──
const API = "";   // same origin — admin_app.py serves this file

// ── DOM refs ──────────────────────────────────────────────────────────────
const dropZone       = document.getElementById("dropZone");
const fileInput      = document.getElementById("fileInput");
const browseBtn      = document.getElementById("browseBtn");
const filePreview    = document.getElementById("filePreview");
const fileTypeIcon   = document.getElementById("fileTypeIcon");
const previewName    = document.getElementById("previewName");
const fileTypeBadge  = document.getElementById("fileTypeBadge");
const previewSize    = document.getElementById("previewSize");
const removeFileBtn  = document.getElementById("removeFileBtn");
const uploadBtn      = document.getElementById("uploadBtn");
const uploadBtnText  = document.getElementById("uploadBtnText");
const progressWrap   = document.getElementById("progressWrap");
const progressBar    = document.getElementById("progressBar");
const progressLabel  = document.getElementById("progressLabel");
const uploadStatus   = document.getElementById("uploadStatus");
const refreshBtn     = document.getElementById("refreshBtn");
const kbLoading      = document.getElementById("kbLoading");
const kbEmpty        = document.getElementById("kbEmpty");
const kbTableWrap    = document.getElementById("kbTableWrap");
const kbTableBody    = document.getElementById("kbTableBody");
const statTotal      = document.getElementById("statTotal");
const statChunks     = document.getElementById("statChunks");
const deleteModal    = document.getElementById("deleteModal");
const deleteFileName = document.getElementById("deleteFileName");
const modalCancel    = document.getElementById("modalCancel");
const modalConfirm   = document.getElementById("modalConfirm");

let selectedFile    = null;
let pendingDelete   = null;   // filename waiting for modal confirmation

// ════════════════════════════════════════════════════════════════════════════
//  FILE TYPE CONFIG
// ════════════════════════════════════════════════════════════════════════════

const FILE_TYPES = {
    pdf:  { label: "PDF",  color: "#ef4444", bg: "rgba(239,68,68,0.15)",   icon: "PDF"  },
    docx: { label: "DOCX", color: "#3b82f6", bg: "rgba(59,130,246,0.15)",  icon: "DOC"  },
    doc:  { label: "DOC",  color: "#3b82f6", bg: "rgba(59,130,246,0.15)",  icon: "DOC"  },
    xlsx: { label: "XLSX", color: "#22c55e", bg: "rgba(34,197,94,0.15)",   icon: "XLS"  },
    xls:  { label: "XLS",  color: "#22c55e", bg: "rgba(34,197,94,0.15)",   icon: "XLS"  },
    pptx: { label: "PPTX", color: "#f97316", bg: "rgba(249,115,22,0.15)",  icon: "PPT"  },
    ppt:  { label: "PPT",  color: "#f97316", bg: "rgba(249,115,22,0.15)",  icon: "PPT"  },
    csv:  { label: "CSV",  color: "#06b6d4", bg: "rgba(6,182,212,0.15)",   icon: "CSV"  },
    txt:  { label: "TXT",  color: "#8b5cf6", bg: "rgba(139,92,246,0.15)",  icon: "TXT"  },
    rtf:  { label: "RTF",  color: "#ec4899", bg: "rgba(236,72,153,0.15)",  icon: "RTF"  },
};

function getFileType(filename) {
    // URL entries
    if (filename.startsWith("http://") || filename.startsWith("https://")) {
        return { label: "URL", color: "#f59e0b", bg: "rgba(245,158,11,0.15)", icon: "URL" };
    }
    const ext = filename.split(".").pop().toLowerCase();
    return FILE_TYPES[ext] || { label: ext.toUpperCase(), color: "#94a3b8", bg: "rgba(148,163,184,0.15)", icon: ext.toUpperCase() };
}

function formatBytes(bytes) {
    if (bytes < 1024)       return bytes + " B";
    if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
}

function formatDate(raw) {
    try {
        const d = new Date(String(raw).replace(" ", "T"));
        if (isNaN(d.getTime())) return raw;
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    } catch { return raw; }
}

function escHtml(str) {
    return String(str)
        .replace(/&/g,"&amp;")
        .replace(/</g,"&lt;")
        .replace(/>/g,"&gt;")
        .replace(/"/g,"&quot;");
}

// ════════════════════════════════════════════════════════════════════════════
//  DRAG & DROP
// ════════════════════════════════════════════════════════════════════════════

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-active");
});

dropZone.addEventListener("dragleave", (e) => {
    if (!dropZone.contains(e.relatedTarget)) {
        dropZone.classList.remove("drag-active");
    }
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-active");
    if (e.dataTransfer.files.length > 0) {
        handleFileSelected(e.dataTransfer.files[0]);
    }
});

browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
});

dropZone.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) handleFileSelected(e.target.files[0]);
});

// ════════════════════════════════════════════════════════════════════════════
//  HANDLE FILE SELECTION
// ════════════════════════════════════════════════════════════════════════════

function handleFileSelected(file) {
    const ft = getFileType(file.name);
    const allowedExts = ["pdf","docx","doc","xlsx","xls","pptx","ppt","csv","txt","rtf"];
    const ext = file.name.split(".").pop().toLowerCase();

    if (!allowedExts.includes(ext)) {
        showUploadStatus(`❌ Unsupported file type ".${ext}". Supported: ${allowedExts.join(", ").toUpperCase()}`, "error");
        return;
    }

    selectedFile = file;
    hideUploadStatus();

    // Update file preview
    fileTypeIcon.style.background  = ft.bg;
    fileTypeIcon.style.color       = ft.color;
    fileTypeIcon.style.border      = `1px solid ${ft.color}44`;
    fileTypeIcon.textContent       = ft.icon;

    previewName.textContent        = file.name;
    fileTypeBadge.textContent      = ft.label;
    fileTypeBadge.style.background = ft.bg;
    fileTypeBadge.style.color      = ft.color;
    fileTypeBadge.style.borderColor= ft.color + "44";
    previewSize.textContent        = formatBytes(file.size);

    filePreview.style.display  = "flex";
    uploadBtn.disabled         = false;
    uploadBtnText.textContent  = `Upload ${file.name}`;
}

removeFileBtn.addEventListener("click", clearSelectedFile);

function clearSelectedFile() {
    selectedFile             = null;
    fileInput.value          = "";
    filePreview.style.display = "none";
    uploadBtn.disabled       = true;
    uploadBtnText.textContent = "Select a file to upload";
    hideUploadStatus();
}

// ════════════════════════════════════════════════════════════════════════════
//  UPLOAD
// ════════════════════════════════════════════════════════════════════════════

uploadBtn.addEventListener("click", uploadFile);

async function uploadFile() {
    if (!selectedFile) return;

    // UI — start
    uploadBtn.disabled = true;
    uploadBtn.classList.add("loading");
    uploadBtnText.textContent = "Uploading…";
    showProgress(0, "Uploading file…");
    hideUploadStatus();

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
        // Simulate progress during upload
        let fakeProgress = 0;
        const progressInterval = setInterval(() => {
            fakeProgress = Math.min(fakeProgress + Math.random() * 12, 75);
            setProgress(fakeProgress, "Processing document…");
        }, 350);

        const response = await fetch(`${API}/admin/load-document`, {
            method: "POST",
            body: formData,
        });

        clearInterval(progressInterval);

        const result = await response.json();

        if (result.status === "success") {
            setProgress(100, "Done!");
            setTimeout(() => hideProgress(), 800);
            showUploadStatus(`✅ ${result.message}`, "success");
            clearSelectedFile();
            loadKnowledgeBase();
        } else {
            hideProgress();
            showUploadStatus(`❌ ${result.message}`, "error");
            // re-enable so user can retry
            uploadBtn.disabled = false;
            uploadBtnText.textContent = `Upload ${selectedFile.name}`;
        }
    } catch (err) {
        hideProgress();
        showUploadStatus(`❌ Network error: ${err.message}`, "error");
        uploadBtn.disabled = false;
        uploadBtnText.textContent = `Upload ${selectedFile ? selectedFile.name : "file"}`;
    }

    uploadBtn.classList.remove("loading");
}

// ── progress helpers ─────────────────────────────────────────────────────────
function showProgress(pct, label) {
    progressWrap.style.display = "flex";
    setProgress(pct, label);
}
function setProgress(pct, label) {
    progressBar.style.width    = pct + "%";
    progressLabel.textContent  = label || "Processing…";
}
function hideProgress() {
    progressBar.style.width    = "0%";
    progressWrap.style.display = "none";
}

// ── status helpers ────────────────────────────────────────────────────────────
function showUploadStatus(msg, type) {
    uploadStatus.textContent  = msg;
    uploadStatus.className    = "upload-status " + type;
    uploadStatus.style.display = "block";
}
function hideUploadStatus() {
    uploadStatus.style.display = "none";
    uploadStatus.textContent   = "";
    uploadStatus.className     = "upload-status";
}

// ════════════════════════════════════════════════════════════════════════════
//  KNOWLEDGE BASE — load & render
// ════════════════════════════════════════════════════════════════════════════

let _adminKbLastCount = -1;   // track doc count to detect changes for polling

async function loadKnowledgeBase() {
    kbLoading.style.display   = "flex";
    kbEmpty.style.display     = "none";
    kbTableWrap.style.display = "none";
    refreshBtn.classList.add("spinning");

    try {
        const res  = await fetch(`${API}/admin/documents`);
        const data = await res.json();
        const docs = data.documents || [];
        _adminKbLastCount = docs.length;   // keep poll tracker in sync
        renderKnowledgeBase(docs);
    } catch (err) {
        renderKnowledgeBase([]);
    } finally {
        kbLoading.style.display = "none";
        refreshBtn.classList.remove("spinning");
    }
}

// ── Polling ───────────────────────────────────────────────────────────────
// Silently check every 10 s; only re-render if the count changes
function startAdminKbPolling() {
    setInterval(async () => {
        if (document.visibilityState === "hidden") return;
        try {
            const res  = await fetch(`${API}/admin/documents`);
            const data = await res.json();
            const docs = data.documents || [];
            if (docs.length !== _adminKbLastCount) {
                _adminKbLastCount = docs.length;
                renderKnowledgeBase(docs);
                // Update sidebar stats without full spinner
                const totalChunks = docs.reduce((sum, d) => sum + (d.chunks || 0), 0);
                statTotal.textContent  = docs.length;
                statChunks.textContent = totalChunks > 999
                    ? (totalChunks / 1000).toFixed(1) + "k"
                    : totalChunks;
            }
        } catch (_) { /* silent — network blip */ }
    }, 10000);
}

function renderKnowledgeBase(docs) {
    // Update sidebar stats
    const totalChunks = docs.reduce((sum, d) => sum + (d.chunks || 0), 0);
    statTotal.textContent  = docs.length;
    statChunks.textContent = totalChunks > 999
        ? (totalChunks / 1000).toFixed(1) + "k"
        : totalChunks;

    if (docs.length === 0) {
        kbEmpty.style.display     = "flex";
        kbTableWrap.style.display = "none";
        return;
    }

    kbEmpty.style.display     = "none";
    kbTableWrap.style.display = "block";
    kbTableBody.innerHTML     = "";

    docs.forEach(doc => {
        const filename = doc.filename || doc.name || "Unknown";
        const ft       = getFileType(filename);
        const isUrl    = filename.startsWith("http://") || filename.startsWith("https://");

        // Display name: for URLs show domain + path, truncated
        let displayName = filename;
        if (isUrl) {
            try {
                const u = new URL(filename);
                displayName = u.hostname + (u.pathname !== "/" ? u.pathname : "");
            } catch (_) { displayName = filename; }
        }

        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>
                <div class="td-filename">
                    <div class="td-file-icon"
                         style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">
                        ${ft.icon}
                    </div>
                    ${isUrl
                        ? `<a class="td-file-name td-url-link" href="${escHtml(filename)}" target="_blank" rel="noopener" title="${escHtml(filename)}">${escHtml(displayName)}</a>`
                        : `<span class="td-file-name" title="${escHtml(filename)}">${escHtml(filename)}</span>`
                    }
                </div>
            </td>
            <td>
                <span class="type-badge"
                      style="background:${ft.bg};color:${ft.color};border-color:${ft.color}44;">
                    ${ft.label}
                </span>
            </td>
            <td><span class="chunks-badge">${doc.chunks || "—"}</span></td>
            <td><span class="date-text">${formatDate(doc.ingested_at || doc.date || "—")}</span></td>
            <td>
                <button class="delete-btn" data-filename="${escHtml(filename)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6l-1 14H6L5 6"/>
                        <path d="M10 11v6M14 11v6"/>
                        <path d="M9 6V4h6v2"/>
                    </svg>
                    Remove
                </button>
            </td>`;

        kbTableBody.appendChild(tr);
    });

    // Attach delete button handlers
    kbTableBody.querySelectorAll(".delete-btn").forEach(btn => {
        btn.addEventListener("click", () => openDeleteModal(btn.dataset.filename));
    });
}

// ════════════════════════════════════════════════════════════════════════════
//  DELETE MODAL
// ════════════════════════════════════════════════════════════════════════════

function openDeleteModal(filename) {
    pendingDelete              = filename;
    deleteFileName.textContent = filename;
    deleteModal.style.display  = "flex";
}

function closeDeleteModal() {
    pendingDelete              = null;
    deleteModal.style.display  = "none";
}

modalCancel.addEventListener("click", closeDeleteModal);

deleteModal.addEventListener("click", (e) => {
    if (e.target === deleteModal) closeDeleteModal();
});

modalConfirm.addEventListener("click", async () => {
    if (!pendingDelete) return;

    const filename = pendingDelete;
    closeDeleteModal();

    // Show removing state
    showUploadStatus(`⏳ Removing '${filename}' from knowledge base — please wait…`, "info");

    // Disable the confirm button during rebuild to prevent double-clicks
    modalConfirm.disabled = true;

    try {
        const res  = await fetch(`${API}/admin/delete-document`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename }),
        });
        const data = await res.json();

        if (data.status === "success") {
            showUploadStatus(`🗑️ ${data.message}`, "success");
            loadKnowledgeBase();
        } else {
            showUploadStatus(`❌ ${data.message}`, "error");
        }
    } catch (err) {
        showUploadStatus(`❌ Network error: ${err.message}`, "error");
    } finally {
        modalConfirm.disabled = false;
    }
});

// ════════════════════════════════════════════════════════════════════════════
//  SCRAPE WEBSITE
// ════════════════════════════════════════════════════════════════════════════

const scrapeUrl         = document.getElementById("scrapeUrl");
const scrapeBtn         = document.getElementById("scrapeBtn");
const scrapeBtnText     = document.getElementById("scrapeBtnText");
const scrapeProgressWrap= document.getElementById("scrapeProgressWrap");
const scrapeProgressBar = document.getElementById("scrapeProgressBar");
const scrapeProgressLbl = document.getElementById("scrapeProgressLabel");
const scrapeStatus      = document.getElementById("scrapeStatus");

scrapeBtn.addEventListener("click", scrapeWebsite);
scrapeUrl.addEventListener("keypress", (e) => { if (e.key === "Enter") scrapeWebsite(); });

async function scrapeWebsite() {
    const url = scrapeUrl.value.trim();

    if (!url) {
        showScrapeStatus("❌ Please enter a URL.", "error");
        return;
    }
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
        showScrapeStatus("❌ URL must start with http:// or https://", "error");
        return;
    }

    // UI — start
    scrapeBtn.disabled   = true;
    scrapeBtn.classList.add("loading");
    scrapeBtnText.textContent = "Scraping…";
    showScrapeProgress(0, "Launching browser…");
    hideScrapeStatus();

    // Animate progress bar while waiting (scraping takes 15-60s)
    let fakeProgress = 0;
    const progressInterval = setInterval(() => {
        // Slow climb: 0→40% fast, 40→80% slow, stall at 80% until done
        const increment = fakeProgress < 40 ? 3 : fakeProgress < 80 ? 0.6 : 0;
        fakeProgress = Math.min(fakeProgress + increment, 80);
        const labels = [
            "Launching browser…",
            "Rendering JavaScript…",
            "Scrolling page…",
            "Expanding hidden content…",
            "Extracting text…",
            "Cleaning and chunking…",
            "Generating embeddings…",
        ];
        const labelIdx = Math.floor((fakeProgress / 80) * (labels.length - 1));
        setScrapeProgress(fakeProgress, labels[labelIdx]);
    }, 600);

    try {
        const res  = await fetch(`${API}/admin/load-url`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });

        clearInterval(progressInterval);
        const data = await res.json();

        if (data.status === "success") {
            setScrapeProgress(100, "Done!");
            setTimeout(() => hideScrapeProgress(), 800);
            showScrapeStatus(`✅ ${data.message}`, "success");
            scrapeUrl.value = "";
            loadKnowledgeBase();
        } else {
            hideScrapeProgress();
            showScrapeStatus(`❌ ${data.message}`, "error");
        }
    } catch (err) {
        clearInterval(progressInterval);
        hideScrapeProgress();
        showScrapeStatus(`❌ Network error: ${err.message}`, "error");
    } finally {
        scrapeBtn.disabled = false;
        scrapeBtn.classList.remove("loading");
        scrapeBtnText.textContent = "Scrape & Ingest";
    }
}

// ── Scrape progress helpers ───────────────────────────────────────────────
function showScrapeProgress(pct, label) {
    scrapeProgressWrap.style.display = "flex";
    setScrapeProgress(pct, label);
}
function setScrapeProgress(pct, label) {
    scrapeProgressBar.style.width   = pct + "%";
    scrapeProgressLbl.textContent   = label || "Processing…";
}
function hideScrapeProgress() {
    scrapeProgressBar.style.width   = "0%";
    scrapeProgressWrap.style.display = "none";
}

// ── Scrape status helpers ─────────────────────────────────────────────────
function showScrapeStatus(msg, type) {
    scrapeStatus.textContent   = msg;
    scrapeStatus.className     = "upload-status " + type;
    scrapeStatus.style.display = "block";
}
function hideScrapeStatus() {
    scrapeStatus.style.display = "none";
    scrapeStatus.textContent   = "";
    scrapeStatus.className     = "upload-status";
}

// ════════════════════════════════════════════════════════════════════════════
//  REFRESH BUTTON
// ════════════════════════════════════════════════════════════════════════════

refreshBtn.addEventListener("click", loadKnowledgeBase);

// ════════════════════════════════════════════════════════════════════════════
//  INIT
// ════════════════════════════════════════════════════════════════════════════

window.addEventListener("load", () => {
    loadKnowledgeBase();
    startAdminKbPolling();
});


// ════════════════════════════════════════════════════════════════════════════
//  SECTION NAVIGATION
// ════════════════════════════════════════════════════════════════════════════

const SECTIONS = ["kb", "chats", "visitors", "bookings"];
const PAGE_TITLES = {
    kb:       ["Knowledge Base Manager",    "Upload documents to expand what the chatbot knows"],
    chats:    ["Chat Logs",                 "All conversations recorded from users"],
    visitors: ["Visitors",                  "IP, geo, browser and device data for every visitor"],
    bookings: ["Bookings",                  "Test-drive and service slot bookings"],
};

function showSection(name) {
    // Hide all sections
    SECTIONS.forEach(s => {
        const el = document.getElementById("section-" + s);
        if (el) el.style.display = "none";
    });

    // Show chosen
    const target = document.getElementById("section-" + name);
    if (target) target.style.display = "block";

    // Update header
    const titles = PAGE_TITLES[name] || ["Admin Panel", ""];
    const titleEl    = document.getElementById("pageTitle");
    const subtitleEl = document.getElementById("pageSubtitle");
    if (titleEl)    titleEl.textContent    = titles[0];
    if (subtitleEl) subtitleEl.textContent = titles[1];

    // Update sidebar nav active state
    document.querySelectorAll(".nav-link").forEach(a => a.classList.remove("active"));
    const activeLink = document.querySelector(`.nav-link[href="#${name}"]`);
    if (activeLink) activeLink.classList.add("active");

    // Lazy-load data for the newly shown section
    if (name === "chats")    loadChats();
    if (name === "visitors") loadVisitors();
    if (name === "bookings") loadBookings();
}


// ════════════════════════════════════════════════════════════════════════════
//  DASHBOARD STATS (sidebar counters)
// ════════════════════════════════════════════════════════════════════════════

async function loadDashboardStats() {
    try {
        const res  = await fetch(`${API}/admin/api/stats`);
        const data = await res.json();
        if (data.status !== "success") return;
        const s = data.stats;

        const el = (id) => document.getElementById(id);
        if (el("statChats"))    el("statChats").textContent    = s.total_chats    ?? "—";
        if (el("statVisitors")) el("statVisitors").textContent = s.total_visitors ?? "—";
    } catch (_) { /* non-fatal */ }
}


// ════════════════════════════════════════════════════════════════════════════
//  CHAT LOGS
// ════════════════════════════════════════════════════════════════════════════

const chatsLoading      = document.getElementById("chatsLoading");
const chatsEmpty        = document.getElementById("chatsEmpty");
const chatsTableWrap    = document.getElementById("chatsTableWrap");
const chatsTableBody    = document.getElementById("chatsTableBody");
const refreshChatsBtn   = document.getElementById("refreshChatsBtn");
const chatsPagination   = document.getElementById("chatsPagination");
const prevChatsPageBtn  = document.getElementById("prevChatsPageBtn");
const nextChatsPageBtn  = document.getElementById("nextChatsPageBtn");
const chatsPageInfo     = document.getElementById("chatsPageInfo");
let chatsCurrentPage    = 1;
let chatsTotalPages     = 1;

if (refreshChatsBtn) refreshChatsBtn.addEventListener("click", () => loadChats(chatsCurrentPage));
if (prevChatsPageBtn) prevChatsPageBtn.addEventListener("click", () => loadChats(Math.max(1, chatsCurrentPage - 1)));
if (nextChatsPageBtn) nextChatsPageBtn.addEventListener("click", () => loadChats(Math.min(chatsTotalPages, chatsCurrentPage + 1)));

async function loadChats(page = chatsCurrentPage) {
    if (!chatsLoading) return;
    page = Number(page) || 1;
    chatsLoading.style.display   = "flex";
    chatsEmpty.style.display     = "none";
    chatsTableWrap.style.display = "none";
    if (chatsPagination) chatsPagination.style.display = "none";
    if (refreshChatsBtn) refreshChatsBtn.classList.add("spinning");

    try {
        const res  = await fetch(`${API}/admin/api/chat-logs?page=${page}`);
        const data = await res.json();
        const logs = data.logs || [];
        const limit = Number(data.limit || 10);
        const total = Number.isFinite(data.total) ? data.total : logs.length;

        chatsCurrentPage = page;
        chatsTotalPages  = Math.max(Math.ceil(total / limit), 1);

        chatsLoading.style.display = "none";

        if (total === 0) {
            chatsEmpty.style.display = "flex";
            if (chatsPagination) chatsPagination.style.display = "none";
            return;
        }

        chatsTableBody.innerHTML = "";
        logs.forEach(log => {
            const tr = document.createElement("tr");

            const typeColor = {
                rag:       "#6366f1",
                faq:       "#22c55e",
                smalltalk: "#f59e0b",
            }[log.response_type] || "#94a3b8";

            const visitorLabel = log.user_email
                ? escHtml(log.user_email)
                : log.visitor_id
                    ? `<span style="font-family:monospace;font-size:11px;opacity:.7">${escHtml(log.visitor_id.slice(0, 8))}…</span>`
                    : "—";

            tr.innerHTML = `
                <td><span class="date-text">${formatDate(log.created_at)}</span></td>
                <td>${visitorLabel}</td>
                <td class="td-truncate" title="${escHtml(log.query || "")}">${escHtml((log.query || "").slice(0, 80))}${(log.query || "").length > 80 ? "…" : ""}</td>
                <td class="td-truncate" title="${escHtml(log.answer || "")}">${escHtml((log.answer || "").slice(0, 100))}${(log.answer || "").length > 100 ? "…" : ""}</td>
                <td><span class="type-badge" style="background:${typeColor}22;color:${typeColor};border-color:${typeColor}44;">${escHtml(log.response_type || "—")}</span></td>`;

            chatsTableBody.appendChild(tr);
        });

        chatsTableWrap.style.display = "block";

        if (chatsPageInfo) chatsPageInfo.textContent = `Page ${chatsCurrentPage} of ${chatsTotalPages}`;
        if (prevChatsPageBtn) prevChatsPageBtn.disabled = chatsCurrentPage <= 1;
        if (nextChatsPageBtn) nextChatsPageBtn.disabled = chatsCurrentPage >= chatsTotalPages;
        if (chatsPagination) chatsPagination.style.display = "flex";
    } catch (err) {
        chatsLoading.style.display = "none";
        chatsEmpty.style.display   = "flex";
        if (chatsPagination) chatsPagination.style.display = "none";
    } finally {
        if (refreshChatsBtn) refreshChatsBtn.classList.remove("spinning");
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  VISITORS
// ════════════════════════════════════════════════════════════════════════════

const visitorsLoading    = document.getElementById("visitorsLoading");
const visitorsEmpty      = document.getElementById("visitorsEmpty");
const visitorsTableWrap  = document.getElementById("visitorsTableWrap");
const visitorsTableBody  = document.getElementById("visitorsTableBody");
const refreshVisitorsBtn = document.getElementById("refreshVisitorsBtn");

if (refreshVisitorsBtn) refreshVisitorsBtn.addEventListener("click", loadVisitors);

async function loadVisitors() {
    if (!visitorsLoading) return;
    visitorsLoading.style.display   = "flex";
    visitorsEmpty.style.display     = "none";
    visitorsTableWrap.style.display = "none";
    if (refreshVisitorsBtn) refreshVisitorsBtn.classList.add("spinning");

    try {
        const res      = await fetch(`${API}/admin/api/visitors?limit=200`);
        const data     = await res.json();
        const visitors = data.visitors || [];

        visitorsLoading.style.display = "none";

        if (visitors.length === 0) {
            visitorsEmpty.style.display = "flex";
            return;
        }

        visitorsTableBody.innerHTML = "";
        visitors.forEach(v => {
            const tr = document.createElement("tr");

            const location = [v.city, v.region, v.country].filter(Boolean).join(", ") || "—";
            const browserOs = [v.browser, v.os].filter(Boolean).join(" / ") || "—";

            tr.innerHTML = `
                <td><code style="font-size:12px;">${escHtml(v.ip_address || "—")}</code></td>
                <td>${escHtml(location)}</td>
                <td>${escHtml(browserOs)}</td>
                <td><span class="type-badge" style="background:rgba(99,102,241,.15);color:#6366f1;border-color:#6366f144;">${escHtml(v.device_type || "—")}</span></td>
                <td style="font-size:12px;opacity:.75;">${escHtml(v.isp || "—")}</td>
                <td><span class="date-text">${formatDate(v.first_visit)}</span></td>
                <td><span class="date-text">${formatDate(v.last_visit)}</span></td>`;

            visitorsTableBody.appendChild(tr);
        });

        visitorsTableWrap.style.display = "block";
    } catch (err) {
        visitorsLoading.style.display = "none";
        visitorsEmpty.style.display   = "flex";
    } finally {
        if (refreshVisitorsBtn) refreshVisitorsBtn.classList.remove("spinning");
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  BOOKINGS
// ════════════════════════════════════════════════════════════════════════════

const bookingsLoading    = document.getElementById("bookingsLoading");
const bookingsEmpty      = document.getElementById("bookingsEmpty");
const bookingsTableWrap  = document.getElementById("bookingsTableWrap");
const bookingsTableBody  = document.getElementById("bookingsTableBody");
const refreshBookingsBtn = document.getElementById("refreshBookingsBtn");

if (refreshBookingsBtn) refreshBookingsBtn.addEventListener("click", loadBookings);

async function loadBookings() {
    if (!bookingsLoading) return;
    bookingsLoading.style.display   = "flex";
    bookingsEmpty.style.display     = "none";
    bookingsTableWrap.style.display = "none";
    if (refreshBookingsBtn) refreshBookingsBtn.classList.add("spinning");

    try {
        const res      = await fetch(`${API}/admin/api/bookings`);
        const data     = await res.json();
        const bookings = data.bookings || [];

        bookingsLoading.style.display = "none";

        if (bookings.length === 0) {
            bookingsEmpty.style.display = "flex";
            return;
        }

        bookingsTableBody.innerHTML = "";
        bookings.forEach(b => {
            const tr = document.createElement("tr");

            const statusColor = {
                confirmed: "#22c55e",
                pending:   "#f59e0b",
                cancelled: "#ef4444",
            }[b.status?.toLowerCase()] || "#94a3b8";

            tr.innerHTML = `
                <td><span style="font-family:monospace;font-size:11px;opacity:.7">${escHtml((b.user_id || "—").slice(0, 12))}…</span></td>
                <td><strong>${escHtml(b.vehicle_model || "—")}</strong></td>
                <td>${escHtml(b.booking_date || "—")}</td>
                <td>${escHtml(b.time_slot || "—")}</td>
                <td><span class="type-badge" style="background:${statusColor}22;color:${statusColor};border-color:${statusColor}44;">${escHtml(b.status || "—")}</span></td>
                <td><span class="date-text">${formatDate(b.created_at)}</span></td>`;

            bookingsTableBody.appendChild(tr);
        });

        bookingsTableWrap.style.display = "block";
    } catch (err) {
        bookingsLoading.style.display = "none";
        bookingsEmpty.style.display   = "flex";
    } finally {
        if (refreshBookingsBtn) refreshBookingsBtn.classList.remove("spinning");
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  OVERRIDE INIT — also load stats
// ════════════════════════════════════════════════════════════════════════════

// Patch the existing window load listener to also fetch stats
const _origLoad = window.onload;
window.addEventListener("load", () => {
    loadDashboardStats();
    // Show KB section by default
    showSection("kb");
});
