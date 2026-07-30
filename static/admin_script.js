// ============================================================
//  DocMind Admin Panel — JavaScript
// ============================================================

const API = "";  // same origin

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
const statTotal      = document.getElementById("statTotal");
const statChunks     = document.getElementById("statChunks");
const deleteModal    = document.getElementById("deleteModal");
const deleteFileName = document.getElementById("deleteFileName");
const modalCancel    = document.getElementById("modalCancel");
const modalConfirm   = document.getElementById("modalConfirm");

let selectedFile  = null;
let pendingDelete = null;

// ── All ingested docs (split into files + urls) ──────────────────────────
let _allDocs  = [];  // file documents
let _allUrls  = [];  // url entries
let _adminKbLastCount = -1;


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
    if (filename.startsWith("http://") || filename.startsWith("https://")) {
        return { label: "URL", color: "#f59e0b", bg: "rgba(245,158,11,0.15)", icon: "URL" };
    }
    const ext = filename.split(".").pop().toLowerCase();
    return FILE_TYPES[ext] || { label: ext.toUpperCase(), color: "#94a3b8", bg: "rgba(148,163,184,0.15)", icon: ext.toUpperCase() };
}

function formatBytes(bytes) {
    if (bytes < 1024)    return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
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
        .replace(/&/g,"&amp;").replace(/</g,"&lt;")
        .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}


// ════════════════════════════════════════════════════════════════════════════
//  KB TAB SWITCHER
// ════════════════════════════════════════════════════════════════════════════

function switchKbTab(tab) {
    // tab = 'docs' | 'urls'
    const docsPanel = document.getElementById("kbPanelDocs");
    const urlsPanel = document.getElementById("kbPanelUrls");
    const docBtn    = document.getElementById("tabDocBtn");
    const urlBtn    = document.getElementById("tabUrlBtn");

    if (tab === "docs") {
        if (docsPanel) docsPanel.style.display = "block";
        if (urlsPanel) urlsPanel.style.display = "none";
        if (docBtn)    docBtn.classList.add("active");
        if (urlBtn)    urlBtn.classList.remove("active");
    } else {
        if (docsPanel) docsPanel.style.display = "none";
        if (urlsPanel) urlsPanel.style.display = "block";
        if (docBtn)    docBtn.classList.remove("active");
        if (urlBtn)    urlBtn.classList.add("active");
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  DRAG & DROP
// ════════════════════════════════════════════════════════════════════════════

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-active");
});

dropZone.addEventListener("dragleave", (e) => {
    if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove("drag-active");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-active");
    if (e.dataTransfer.files.length > 0) handleFileSelected(e.dataTransfer.files[0]);
});

browseBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => { if (e.target.files.length > 0) handleFileSelected(e.target.files[0]); });

// ════════════════════════════════════════════════════════════════════════════
//  FILE SELECTION
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
    filePreview.style.display      = "flex";
    uploadBtn.disabled             = false;
    uploadBtnText.textContent      = `Upload ${file.name}`;
}

removeFileBtn.addEventListener("click", clearSelectedFile);

function clearSelectedFile() {
    selectedFile              = null;
    fileInput.value           = "";
    filePreview.style.display = "none";
    uploadBtn.disabled        = true;
    uploadBtnText.textContent = "Select a file to upload";
    hideUploadStatus();
}


// ════════════════════════════════════════════════════════════════════════════
//  UPLOAD
// ════════════════════════════════════════════════════════════════════════════

uploadBtn.addEventListener("click", uploadFile);

async function uploadFile() {
    if (!selectedFile) return;
    uploadBtn.disabled = true;
    uploadBtn.classList.add("loading");
    uploadBtnText.textContent = "Uploading…";
    showProgress(0, "Uploading file…");
    hideUploadStatus();
    const formData = new FormData();
    formData.append("file", selectedFile);
    try {
        const response = await fetch(`${API}/admin/load-document`, { method: "POST", credentials: "include", body: formData });
        const result = await response.json();

        if (result.status === "accepted" && result.job_id) {
            // Background job started — poll for completion
            setProgress(5, "File uploaded — processing…");
            await _pollJob(result.job_id, {
                onProgress: (pct, label) => setProgress(pct, label),
                onDone:     (msg) => {
                    setProgress(100, "Done!");
                    setTimeout(() => hideProgress(), 800);
                    showUploadStatus(`✅ ${msg}`, "success");
                    clearSelectedFile();
                    loadKnowledgeBase();
                },
                onError: (msg) => {
                    hideProgress();
                    showUploadStatus(`❌ ${msg}`, "error");
                    uploadBtn.disabled = false;
                    uploadBtnText.textContent = `Upload ${selectedFile ? selectedFile.name : "file"}`;
                },
            });
        } else if (result.status === "success") {
            setProgress(100, "Done!");
            setTimeout(() => hideProgress(), 800);
            showUploadStatus(`✅ ${result.message}`, "success");
            clearSelectedFile();
            loadKnowledgeBase();
        } else {
            hideProgress();
            showUploadStatus(`❌ ${result.message}`, "error");
            uploadBtn.disabled = false;
            uploadBtnText.textContent = `Upload ${selectedFile ? selectedFile.name : "file"}`;
        }
    } catch (err) {
        hideProgress();
        showUploadStatus(`❌ Network error: ${err.message}`, "error");
        uploadBtn.disabled = false;
        uploadBtnText.textContent = `Upload ${selectedFile ? selectedFile.name : "file"}`;
    }
    uploadBtn.classList.remove("loading");
}

function showProgress(pct, label) { progressWrap.style.display = "flex"; setProgress(pct, label); }
function setProgress(pct, label)  { progressBar.style.width = pct + "%"; progressLabel.textContent = label || "Processing…"; }
function hideProgress()           { progressBar.style.width = "0%"; progressWrap.style.display = "none"; }
function showUploadStatus(msg, type) { uploadStatus.textContent = msg; uploadStatus.className = "upload-status " + type; uploadStatus.style.display = "block"; }
function hideUploadStatus()          { uploadStatus.style.display = "none"; uploadStatus.textContent = ""; uploadStatus.className = "upload-status"; }


// ════════════════════════════════════════════════════════════════════════════
//  KNOWLEDGE BASE — load, split & render
// ════════════════════════════════════════════════════════════════════════════

async function loadKnowledgeBase() {
    // Show spinners in both panels
    const docsLoading   = document.getElementById("docsLoading");
    const urlsLoading   = document.getElementById("urlsLoading");
    if (docsLoading) docsLoading.style.display = "flex";
    if (urlsLoading) urlsLoading.style.display = "flex";
    if (refreshBtn)  refreshBtn.classList.add("spinning");

    try {
        const res  = await fetch(`${API}/admin/documents`, { credentials: "include" });
        const data = await res.json();
        const docs = data.documents || [];
        _adminKbLastCount = docs.length;

        // Split into files vs URLs
        _allDocs = docs.filter(d => {
            const name = d.filename || d.name || "";
            return !name.startsWith("http://") && !name.startsWith("https://");
        });
        _allUrls = docs.filter(d => {
            const name = d.filename || d.name || "";
            return name.startsWith("http://") || name.startsWith("https://");
        });

        renderDocsTable(_allDocs);
        renderUrlsTable(_allUrls);
        updateSidebarStats(docs);
    } catch (err) {
        renderDocsTable([]);
        renderUrlsTable([]);
    } finally {
        if (docsLoading) docsLoading.style.display = "none";
        if (urlsLoading) urlsLoading.style.display = "none";
        if (refreshBtn)  refreshBtn.classList.remove("spinning");
    }
}

function updateSidebarStats(docs) {
    const totalChunks = docs.reduce((sum, d) => sum + (d.chunks || 0), 0);
    if (statTotal)  statTotal.textContent  = docs.length;
    if (statChunks) statChunks.textContent = totalChunks > 999
        ? (totalChunks / 1000).toFixed(1) + "k" : totalChunks;
}

// ── Polling ───────────────────────────────────────────────────────────────
function startAdminKbPolling() {
    setInterval(async () => {
        if (document.visibilityState === "hidden") return;
        try {
            const res  = await fetch(`${API}/admin/documents`, { credentials: "include" });
            const data = await res.json();
            const docs = data.documents || [];
            if (docs.length !== _adminKbLastCount) {
                _adminKbLastCount = docs.length;
                _allDocs = docs.filter(d => { const n = d.filename||d.name||""; return !n.startsWith("http"); });
                _allUrls = docs.filter(d => { const n = d.filename||d.name||""; return  n.startsWith("http"); });
                filterDocsTable();
                filterUrlsTable();
                updateSidebarStats(docs);
            }
        } catch (_) {}
    }, 10000);
}


// ════════════════════════════════════════════════════════════════════════════
//  DOCS TABLE  (files only)
// ════════════════════════════════════════════════════════════════════════════

function renderDocsTable(docs) {
    const empty     = document.getElementById("docsEmpty");
    const noResults = document.getElementById("docsNoResults");
    const tableWrap = document.getElementById("docsTableWrap");
    const tbody     = document.getElementById("docsTableBody");
    const countEl   = document.getElementById("docsCount");

    if (countEl) countEl.textContent = _allDocs.length + " document" + (_allDocs.length !== 1 ? "s" : "");

    if (_allDocs.length === 0) {
        if (empty)     empty.style.display     = "flex";
        if (noResults) noResults.style.display = "none";
        if (tableWrap) tableWrap.style.display = "none";
        return;
    }

    if (docs.length === 0) {
        // search returned nothing
        if (empty)     empty.style.display     = "none";
        if (noResults) noResults.style.display = "flex";
        if (tableWrap) tableWrap.style.display = "none";
        return;
    }

    if (empty)     empty.style.display     = "none";
    if (noResults) noResults.style.display = "none";
    if (tableWrap) tableWrap.style.display = "block";
    tbody.innerHTML = "";

    docs.forEach(doc => {
        const filename = doc.filename || doc.name || "Unknown";
        const ft  = getFileType(filename);
        const tr  = document.createElement("tr");
        tr.innerHTML = `
            <td>
                <div class="td-filename">
                    <div class="td-file-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div>
                    <span class="td-file-name" title="${escHtml(filename)}">${escHtml(filename)}</span>
                </div>
            </td>
            <td><span class="type-badge" style="background:${ft.bg};color:${ft.color};border-color:${ft.color}44;">${ft.label}</span></td>
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
        tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".delete-btn").forEach(btn => {
        btn.addEventListener("click", () => openDeleteModal(btn.dataset.filename));
    });
}

// Live search for docs
function filterDocsTable() {
    const q     = (document.getElementById("docsSearchInput")?.value || "").toLowerCase().trim();
    const clear = document.getElementById("docsSearchClear");
    if (clear) clear.style.display = q ? "flex" : "none";
    const filtered = q ? _allDocs.filter(d => (d.filename||d.name||"").toLowerCase().includes(q)) : _allDocs;
    renderDocsTable(filtered);
}

function clearDocsSearch() {
    const inp = document.getElementById("docsSearchInput");
    if (inp) inp.value = "";
    filterDocsTable();
}


// ════════════════════════════════════════════════════════════════════════════
//  URLS TABLE  (URL entries only)
// ════════════════════════════════════════════════════════════════════════════

function renderUrlsTable(urls) {
    const empty     = document.getElementById("urlsEmpty");
    const noResults = document.getElementById("urlsNoResults");
    const tableWrap = document.getElementById("urlsTableWrap");
    const tbody     = document.getElementById("urlsTableBody");
    const countEl   = document.getElementById("urlsCount");

    if (countEl) countEl.textContent = _allUrls.length + " URL" + (_allUrls.length !== 1 ? "s" : "");

    if (_allUrls.length === 0) {
        if (empty)     empty.style.display     = "flex";
        if (noResults) noResults.style.display = "none";
        if (tableWrap) tableWrap.style.display = "none";
        return;
    }

    if (urls.length === 0) {
        if (empty)     empty.style.display     = "none";
        if (noResults) noResults.style.display = "flex";
        if (tableWrap) tableWrap.style.display = "none";
        return;
    }

    if (empty)     empty.style.display     = "none";
    if (noResults) noResults.style.display = "none";
    if (tableWrap) tableWrap.style.display = "block";
    tbody.innerHTML = "";

    urls.forEach(doc => {
        const url = doc.filename || doc.name || "Unknown";
        let displayName = url;
        try {
            const u = new URL(url);
            displayName = u.hostname + (u.pathname !== "/" ? u.pathname : "");
        } catch (_) {}

        const ft = getFileType(url);
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>
                <div class="td-filename">
                    <div class="td-file-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div>
                    <a class="td-file-name td-url-link" href="${escHtml(url)}" target="_blank" rel="noopener" title="${escHtml(url)}">${escHtml(displayName)}</a>
                </div>
            </td>
            <td><span class="chunks-badge">${doc.chunks || "—"}</span></td>
            <td><span class="date-text">${formatDate(doc.ingested_at || doc.date || "—")}</span></td>
            <td>
                <button class="delete-btn" data-filename="${escHtml(url)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6l-1 14H6L5 6"/>
                        <path d="M10 11v6M14 11v6"/>
                        <path d="M9 6V4h6v2"/>
                    </svg>
                    Remove
                </button>
            </td>`;
        tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".delete-btn").forEach(btn => {
        btn.addEventListener("click", () => openDeleteModal(btn.dataset.filename));
    });
}

// Live search for URLs
function filterUrlsTable() {
    const q     = (document.getElementById("urlsSearchInput")?.value || "").toLowerCase().trim();
    const clear = document.getElementById("urlsSearchClear");
    if (clear) clear.style.display = q ? "flex" : "none";
    const filtered = q ? _allUrls.filter(d => (d.filename||d.name||"").toLowerCase().includes(q)) : _allUrls;
    renderUrlsTable(filtered);
}

function clearUrlsSearch() {
    const inp = document.getElementById("urlsSearchInput");
    if (inp) inp.value = "";
    filterUrlsTable();
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
    pendingDelete             = null;
    deleteModal.style.display = "none";
}

modalCancel.addEventListener("click", closeDeleteModal);
deleteModal.addEventListener("click", (e) => { if (e.target === deleteModal) closeDeleteModal(); });

modalConfirm.addEventListener("click", async () => {
    if (!pendingDelete) return;
    const filename = pendingDelete;
    closeDeleteModal();
    showUploadStatus(`⏳ Removing '${filename}'…`, "info");
    modalConfirm.disabled = true;
    try {
        const res  = await fetch(`${API}/admin/delete-document`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
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

if (refreshBtn) refreshBtn.addEventListener("click", loadKnowledgeBase);


// ════════════════════════════════════════════════════════════════════════════
//  JOB POLLING HELPER
// ════════════════════════════════════════════════════════════════════════════

/**
 * Poll /admin/job/<job_id> every 2 seconds until done or error.
 * callbacks: { onProgress(pct, label), onDone(message), onError(message) }
 */
async function _pollJob(jobId, { onProgress, onDone, onError }) {
    const POLL_MS    = 2000;
    const MAX_POLLS  = 600;   // 20 minutes max
    let   polls      = 0;

    return new Promise((resolve) => {
        const timer = setInterval(async () => {
            polls++;
            if (polls > MAX_POLLS) {
                clearInterval(timer);
                onError("Timed out waiting for processing to complete.");
                resolve();
                return;
            }
            try {
                const res  = await fetch(`${API}/admin/job/${jobId}`, { credentials: "include" });
                const data = await res.json();

                if (data.status === "done") {
                    clearInterval(timer);
                    onDone(data.message);
                    resolve();
                } else if (data.status === "error") {
                    clearInterval(timer);
                    onError(data.message);
                    resolve();
                }
                // "running" → keep polling, optionally update progress
            } catch (_) {
                // network blip — keep trying
            }
        }, POLL_MS);
    });
}


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

if (scrapeBtn) scrapeBtn.addEventListener("click", scrapeWebsite);
if (scrapeUrl) scrapeUrl.addEventListener("keypress", (e) => { if (e.key === "Enter") scrapeWebsite(); });

const _GDRIVE_HOSTS = new Set(["drive.google.com","docs.google.com","sheets.google.com","slides.google.com"]);
const _OD_HOSTS     = new Set(["onedrive.live.com","1drv.ms"]);
const _DOC_EXTS     = new Set(["pdf","docx","doc","xlsx","xls","pptx","ppt","csv","txt","rtf"]);

function classifyUrl(url) {
    let parsed;
    try { parsed = new URL(url); } catch (_) { return "webpage"; }
    const host = parsed.hostname.toLowerCase();
    if (_GDRIVE_HOSTS.has(host)) {
        return parsed.pathname.includes("/folders/") ? "gdrive_folder" : "gdrive";
    }
    if (_OD_HOSTS.has(host) || host.endsWith(".sharepoint.com")) return "onedrive";
    const pathExt = parsed.pathname.split(".").pop().toLowerCase().split("?")[0];
    if (_DOC_EXTS.has(pathExt)) return "file";
    return "webpage";
}

function getUrlUiConfig(urlType) {
    const configs = {
        gdrive:   { buttonLabel:"Downloading…", initialLabel:"Connecting to Google Drive…",
                    progressLabels:["Connecting to Google Drive…","Authenticating share link…","Downloading file…","Detecting file type…","Extracting content…","Chunking + enriching…","Generating embeddings…"] },
        onedrive: { buttonLabel:"Downloading…", initialLabel:"Resolving OneDrive link…",
                    progressLabels:["Resolving OneDrive link…","Following redirect…","Downloading file…","Detecting file type…","Extracting content…","Chunking + enriching…","Generating embeddings…"] },
        file:     { buttonLabel:"Downloading…", initialLabel:"Downloading file…",
                    progressLabels:["Downloading file…","Verifying file type…","Extracting content…","Chunking + enriching…","Generating embeddings…","Storing vectors…","Almost done…"] },
    };
    return configs[urlType] || { buttonLabel:"Scraping…", initialLabel:"Launching browser…",
        progressLabels:["Launching browser…","Rendering JavaScript…","Scrolling page…","Expanding hidden content…","Extracting text…","Chunking + enriching…","Generating embeddings…"] };
}

async function scrapeWebsite() {
    const url = scrapeUrl.value.trim();
    if (!url) { showScrapeStatus("❌ Please enter a URL.", "error"); return; }
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
        showScrapeStatus("❌ URL must start with http:// or https://", "error"); return;
    }
    const urlType = classifyUrl(url);
    if (urlType === "gdrive_folder") {
        showScrapeStatus("❌ Google Drive folder links are not supported. Please share a single file.", "error"); return;
    }
    const uiCfg = getUrlUiConfig(urlType);
    scrapeBtn.disabled = true;
    scrapeBtn.classList.add("loading");
    scrapeBtnText.textContent = uiCfg.buttonLabel;
    showScrapeProgress(0, uiCfg.initialLabel);
    hideScrapeStatus();

    try {
        const res  = await fetch(`${API}/admin/load-url`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ url })
        });
        const data = await res.json();

        if (data.status === "accepted" && data.job_id) {
            // Background job started — poll for completion with animated labels
            const labels = uiCfg.progressLabels;
            let labelIdx = 0;
            const labelTimer = setInterval(() => {
                labelIdx = Math.min(labelIdx + 1, labels.length - 1);
                const pct = 5 + (labelIdx / (labels.length - 1)) * 75;
                setScrapeProgress(pct, labels[labelIdx]);
            }, 4000);

            await _pollJob(data.job_id, {
                onProgress: (pct, label) => setScrapeProgress(pct, label),
                onDone: (msg) => {
                    clearInterval(labelTimer);
                    setScrapeProgress(100, "Done!");
                    setTimeout(() => hideScrapeProgress(), 800);
                    showScrapeStatus(`✅ ${msg}`, "success");
                    scrapeUrl.value = "";
                    loadKnowledgeBase();
                },
                onError: (msg) => {
                    clearInterval(labelTimer);
                    hideScrapeProgress();
                    showScrapeStatus(`❌ ${msg}`, "error");
                },
            });
        } else if (data.status === "success") {
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
        hideScrapeProgress();
        showScrapeStatus(`❌ Network error: ${err.message}`, "error");
    } finally {
        scrapeBtn.disabled = false;
        scrapeBtn.classList.remove("loading");
        scrapeBtnText.textContent = "Scrape & Ingest";
    }
}

function showScrapeProgress(pct, label)  { scrapeProgressWrap.style.display = "flex"; setScrapeProgress(pct, label); }
function setScrapeProgress(pct, label)   { scrapeProgressBar.style.width = pct + "%"; scrapeProgressLbl.textContent = label || "Processing…"; }
function hideScrapeProgress()            { scrapeProgressBar.style.width = "0%"; scrapeProgressWrap.style.display = "none"; }
function showScrapeStatus(msg, type)     { scrapeStatus.textContent = msg; scrapeStatus.className = "upload-status " + type; scrapeStatus.style.display = "block"; }
function hideScrapeStatus()              { scrapeStatus.style.display = "none"; scrapeStatus.textContent = ""; scrapeStatus.className = "upload-status"; }


// ════════════════════════════════════════════════════════════════════════════
//  SECTION NAVIGATION
// ════════════════════════════════════════════════════════════════════════════

const SECTIONS = ["kb", "chats", "visitors", "bookings"];
const PAGE_TITLES = {
    kb:       ["Knowledge Base Manager",    "Upload documents and URLs to expand what the chatbot knows"],
    chats:    ["Chat Logs",                 "All conversations recorded from users"],
    visitors: ["Visitors",                  "IP, geo, browser and device data for every visitor"],
    bookings: ["Bookings",                  "Test-drive and service slot bookings"],
};

function showSection(name) {
    SECTIONS.forEach(s => {
        const el = document.getElementById("section-" + s);
        if (el) el.style.display = "none";
    });
    const target = document.getElementById("section-" + name);
    if (target) target.style.display = "block";

    const titles = PAGE_TITLES[name] || ["Admin Panel", ""];
    const titleEl    = document.getElementById("pageTitle");
    const subtitleEl = document.getElementById("pageSubtitle");
    if (titleEl)    titleEl.textContent    = titles[0];
    if (subtitleEl) subtitleEl.textContent = titles[1];

    document.querySelectorAll(".nav-link").forEach(a => a.classList.remove("active"));
    const activeLink = document.querySelector(`.nav-link[href="#${name}"]`);
    if (activeLink) activeLink.classList.add("active");

    if (name === "chats")    loadChats();
    if (name === "visitors") loadVisitors();
    if (name === "bookings") loadBookings();
}

// ════════════════════════════════════════════════════════════════════════════
//  DASHBOARD STATS
// ════════════════════════════════════════════════════════════════════════════

async function loadDashboardStats() {
    try {
        const res  = await fetch(`${API}/admin/api/stats`, { credentials: "include" });
        const data = await res.json();
        if (data.status !== "success") return;
        const s  = data.stats;
        const el = (id) => document.getElementById(id);
        if (el("statChats"))    el("statChats").textContent    = s.total_chats    ?? "—";
        if (el("statVisitors")) el("statVisitors").textContent = s.total_visitors ?? "—";
    } catch (_) {}
}


// ════════════════════════════════════════════════════════════════════════════
//  CHAT LOGS
// ════════════════════════════════════════════════════════════════════════════

const chatsLoading     = document.getElementById("chatsLoading");
const chatsEmpty       = document.getElementById("chatsEmpty");
const chatsTableWrap   = document.getElementById("chatsTableWrap");
const chatsTableBody   = document.getElementById("chatsTableBody");
const refreshChatsBtn  = document.getElementById("refreshChatsBtn");
const chatsPagination  = document.getElementById("chatsPagination");
const prevChatsPageBtn = document.getElementById("prevChatsPageBtn");
const nextChatsPageBtn = document.getElementById("nextChatsPageBtn");
const chatsPageInfo    = document.getElementById("chatsPageInfo");
let chatsCurrentPage   = 1;
let chatsTotalPages    = 1;

if (refreshChatsBtn)  refreshChatsBtn.addEventListener("click",  () => loadChats(chatsCurrentPage));
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
        const res   = await fetch(`${API}/admin/api/chat-logs?page=${page}`, { credentials: "include" });
        const data  = await res.json();
        const logs  = data.logs || [];
        const limit = Number(data.limit || 10);
        const total = Number.isFinite(data.total) ? data.total : logs.length;
        chatsCurrentPage = page;
        chatsTotalPages  = Math.max(Math.ceil(total / limit), 1);
        chatsLoading.style.display = "none";

        if (total === 0) { chatsEmpty.style.display = "flex"; return; }

        chatsTableBody.innerHTML = "";
        logs.forEach(log => {
            const tr = document.createElement("tr");
            const typeColor = { rag:"#6366f1", faq:"#22c55e", smalltalk:"#f59e0b" }[log.response_type] || "#94a3b8";
            let visitorLabel;
            if (log.user_name && log.user_name.trim()) {
                visitorLabel = `<span class="visitor-name-badge">${escHtml(log.user_name.trim())}</span>`;
            } else if (log.user_email && log.user_email.trim()) {
                visitorLabel = `<span class="visitor-email-badge">${escHtml(log.user_email.trim())}</span>`;
            } else if (log.visitor_id) {
                const vName = log.visitor_name || "";
                visitorLabel = vName
                    ? `<span class="visitor-name-badge">${escHtml(vName.trim())}</span>`
                    : `<span class="visitor-uuid-badge" title="${escHtml(log.visitor_id)}">${escHtml(log.visitor_id.slice(0,8))}…</span>`;
            } else {
                visitorLabel = `<span style="opacity:.4">—</span>`;
            }
            tr.innerHTML = `
                <td><span class="date-text">${formatDate(log.created_at)}</span></td>
                <td>${visitorLabel}</td>
                <td class="td-truncate" title="${escHtml(log.query||"")}">${escHtml((log.query||"").slice(0,80))}${(log.query||"").length>80?"…":""}</td>
                <td class="td-truncate" title="${escHtml(log.answer||"")}">${escHtml((log.answer||"").slice(0,100))}${(log.answer||"").length>100?"…":""}</td>
                <td><span class="type-badge" style="background:${typeColor}22;color:${typeColor};border-color:${typeColor}44;">${escHtml(log.response_type||"—")}</span></td>`;
            chatsTableBody.appendChild(tr);
        });

        chatsTableWrap.style.display = "block";
        if (chatsPageInfo)    chatsPageInfo.textContent  = `Page ${chatsCurrentPage} of ${chatsTotalPages}`;
        if (prevChatsPageBtn) prevChatsPageBtn.disabled  = chatsCurrentPage <= 1;
        if (nextChatsPageBtn) nextChatsPageBtn.disabled  = chatsCurrentPage >= chatsTotalPages;
        if (chatsPagination)  chatsPagination.style.display = "flex";
    } catch (err) {
        chatsLoading.style.display = "none";
        chatsEmpty.style.display   = "flex";
    } finally {
        if (refreshChatsBtn) refreshChatsBtn.classList.remove("spinning");
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  VISITORS  (10 per page, newest first)
// ════════════════════════════════════════════════════════════════════════════

const visitorsLoading     = document.getElementById("visitorsLoading");
const visitorsEmpty       = document.getElementById("visitorsEmpty");
const visitorsTableWrap   = document.getElementById("visitorsTableWrap");
const visitorsTableBody   = document.getElementById("visitorsTableBody");
const refreshVisitorsBtn  = document.getElementById("refreshVisitorsBtn");
const visitorsPagination  = document.getElementById("visitorsPagination");
const prevVisitorsPageBtn = document.getElementById("prevVisitorsPageBtn");
const nextVisitorsPageBtn = document.getElementById("nextVisitorsPageBtn");
const visitorsPageInfo    = document.getElementById("visitorsPageInfo");

const VISITORS_PER_PAGE   = 10;
let _allVisitors           = [];   // full sorted list
let visitorsCurrentPage    = 1;
let visitorsTotalPages     = 1;

if (refreshVisitorsBtn)  refreshVisitorsBtn.addEventListener("click",  () => loadVisitors());
if (prevVisitorsPageBtn) prevVisitorsPageBtn.addEventListener("click", () => renderVisitorsPage(visitorsCurrentPage - 1));
if (nextVisitorsPageBtn) nextVisitorsPageBtn.addEventListener("click", () => renderVisitorsPage(visitorsCurrentPage + 1));

async function loadVisitors() {
    if (!visitorsLoading) return;
    visitorsLoading.style.display   = "flex";
    visitorsEmpty.style.display     = "none";
    visitorsTableWrap.style.display = "none";
    if (visitorsPagination)  visitorsPagination.style.display  = "none";
    if (refreshVisitorsBtn)  refreshVisitorsBtn.classList.add("spinning");

    try {
        const res  = await fetch(`${API}/admin/api/visitors?limit=1000`, { credentials: "include" });
        const data = await res.json();
        let visitors = data.visitors || [];

        // Sort descending by last_visit (newest first)
        visitors.sort((a, b) => {
            const ta = new Date(String(a.last_visit || a.first_visit || "").replace(" ","T")).getTime() || 0;
            const tb = new Date(String(b.last_visit || b.first_visit || "").replace(" ","T")).getTime() || 0;
            return tb - ta;
        });

        _allVisitors       = visitors;
        visitorsTotalPages = Math.max(Math.ceil(_allVisitors.length / VISITORS_PER_PAGE), 1);
        visitorsCurrentPage = 1;

        visitorsLoading.style.display = "none";

        if (_allVisitors.length === 0) {
            visitorsEmpty.style.display = "flex";
            return;
        }
        renderVisitorsPage(1);
    } catch (err) {
        visitorsLoading.style.display = "none";
        visitorsEmpty.style.display   = "flex";
    } finally {
        if (refreshVisitorsBtn) refreshVisitorsBtn.classList.remove("spinning");
    }
}

function renderVisitorsPage(page) {
    page = Math.max(1, Math.min(page, visitorsTotalPages));
    visitorsCurrentPage = page;

    const start    = (page - 1) * VISITORS_PER_PAGE;
    const pageData = _allVisitors.slice(start, start + VISITORS_PER_PAGE);

    visitorsTableBody.innerHTML = "";
    pageData.forEach(v => {
        const tr       = document.createElement("tr");
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

    if (visitorsPageInfo)    visitorsPageInfo.textContent  = `Page ${visitorsCurrentPage} of ${visitorsTotalPages}`;
    if (prevVisitorsPageBtn) prevVisitorsPageBtn.disabled  = visitorsCurrentPage <= 1;
    if (nextVisitorsPageBtn) nextVisitorsPageBtn.disabled  = visitorsCurrentPage >= visitorsTotalPages;
    if (visitorsPagination)  visitorsPagination.style.display = _allVisitors.length > VISITORS_PER_PAGE ? "flex" : "none";
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
        const res      = await fetch(`${API}/admin/api/bookings`, { credentials: "include" });
        const data     = await res.json();
        const bookings = data.bookings || [];
        bookingsLoading.style.display = "none";
        if (bookings.length === 0) { bookingsEmpty.style.display = "flex"; return; }

        bookingsTableBody.innerHTML = "";
        bookings.forEach(b => {
            const tr = document.createElement("tr");
            const statusColor = { confirmed:"#22c55e", pending:"#f59e0b", cancelled:"#ef4444" }[b.status?.toLowerCase()] || "#94a3b8";
            tr.innerHTML = `
                <td><span style="font-family:monospace;font-size:11px;opacity:.7">${escHtml((b.user_id||"—").slice(0,12))}…</span></td>
                <td><strong>${escHtml(b.vehicle_model||"—")}</strong></td>
                <td>${escHtml(b.booking_date||"—")}</td>
                <td>${escHtml(b.time_slot||"—")}</td>
                <td><span class="type-badge" style="background:${statusColor}22;color:${statusColor};border-color:${statusColor}44;">${escHtml(b.status||"—")}</span></td>
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
//  INIT
// ════════════════════════════════════════════════════════════════════════════

window.addEventListener("load", () => {
    loadDashboardStats();
    loadKnowledgeBase();
    startAdminKbPolling();
    showSection("kb");
});
