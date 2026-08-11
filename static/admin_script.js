// ============================================================
//  DocMind Admin Panel — JavaScript
// ============================================================

const API = "";  // same origin

// ── DOM refs ──────────────────────────────────────────────────────────────
const dropZone    = document.getElementById("dropZone");
const fileInput   = document.getElementById("fileInput");
const browseBtn   = document.getElementById("browseBtn");
const uploadBtn   = document.getElementById("uploadBtn");
const uploadBtnText = document.getElementById("uploadBtnText");
const refreshBtn  = document.getElementById("refreshBtn");
const statTotal   = document.getElementById("statTotal");
const statChunks  = document.getElementById("statChunks");
const deleteModal    = document.getElementById("deleteModal");
const deleteFileName = document.getElementById("deleteFileName");
const modalCancel    = document.getElementById("modalCancel");
const modalConfirm   = document.getElementById("modalConfirm");

let pendingDelete = null;

// ── Multi-file queue state ────────────────────────────────────────────────
// selectedFiles : File[] currently staged in the drop zone
// _queuedJobs   : { jobId, filename, status, message }[] — live job list
let selectedFiles = [];
let _queuedJobs   = [];
let _queuePollTimer = null;

// ── All ingested docs (unified table) ────────────────────────────────────
let _allDocs  = [];
let _allUrls  = [];
let _allItems = [];
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
//  UPLOAD MENU TOGGLE
// ════════════════════════════════════════════════════════════════════════════

function toggleUploadMenu() {
    const menu    = document.getElementById("kbUploadMenu");
    const chevron = document.getElementById("kbNewChevron");
    const isOpen  = menu.style.display !== "none";
    menu.style.display    = isOpen ? "none" : "block";
    chevron.style.transform = isOpen ? "" : "rotate(180deg)";
}

function openUploadForm(type) {
    // Close the dropdown menu
    document.getElementById("kbUploadMenu").style.display = "none";
    document.getElementById("kbNewChevron").style.transform = "";

    const panel  = document.getElementById("kbUploadPanel");
    const docFrm = document.getElementById("kbFormDoc");
    const urlFrm = document.getElementById("kbFormUrl");

    panel.style.display  = "block";
    docFrm.style.display = type === "doc" ? "flex" : "none";
    urlFrm.style.display = type === "url" ? "flex" : "none";

    // Scroll panel into view smoothly
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeUploadForm() {
    const panel  = document.getElementById("kbUploadPanel");
    panel.style.display = "none";
    document.getElementById("kbFormDoc").style.display = "none";
    document.getElementById("kbFormUrl").style.display = "none";
}

// Close dropdown when clicking outside
document.addEventListener("click", (e) => {
    const dropdown = document.getElementById("kbUploadDropdown");
    if (dropdown && !dropdown.contains(e.target)) {
        const menu    = document.getElementById("kbUploadMenu");
        const chevron = document.getElementById("kbNewChevron");
        if (menu)    menu.style.display      = "none";
        if (chevron) chevron.style.transform = "";
    }
});

// Kept for backward-compat (old HTML may still reference it)
function switchKbTab() {}


// ════════════════════════════════════════════════════════════════════════════
//  KNOWLEDGE BASE — unified load, search & render
// ════════════════════════════════════════════════════════════════════════════

async function loadKnowledgeBase() {
    const kbLoading  = document.getElementById("kbLoading");
    const kbEmpty    = document.getElementById("kbEmpty");
    const kbNoRes    = document.getElementById("kbNoResults");
    const kbTableWrap= document.getElementById("kbTableWrap");
    const refreshBtn = document.getElementById("refreshBtn");

    if (kbLoading)   kbLoading.style.display   = "flex";
    if (kbEmpty)     kbEmpty.style.display      = "none";
    if (kbNoRes)     kbNoRes.style.display      = "none";
    if (kbTableWrap) kbTableWrap.style.display  = "none";
    if (refreshBtn)  refreshBtn.classList.add("spinning");

    try {
        const res  = await fetch(`${API}/admin/documents`, { credentials: "include" });
        const data = await res.json();
        const docs = data.documents || [];
        _adminKbLastCount = docs.length;

        _allDocs  = docs.filter(d => { const n = d.filename||d.name||""; return !n.startsWith("http://") && !n.startsWith("https://"); });
        _allUrls  = docs.filter(d => { const n = d.filename||d.name||""; return  n.startsWith("http://") || n.startsWith("https://"); });
        _allItems = [...docs];

        updateSidebarStats(docs);
        filterUnifiedTable();  // apply any existing search query
    } catch (err) {
        _allItems = [];
        filterUnifiedTable();
    } finally {
        if (kbLoading) kbLoading.style.display = "none";
        if (refreshBtn) refreshBtn.classList.remove("spinning");
    }
}

function updateSidebarStats(docs) {
    const totalChunks = docs.reduce((sum, d) => sum + (d.chunks || 0), 0);
    if (statTotal)  statTotal.textContent  = docs.length;
    if (statChunks) statChunks.textContent = totalChunks > 999 ? (totalChunks/1000).toFixed(1)+"k" : totalChunks;

    const countEl = document.getElementById("kbTotalCount");
    if (countEl) countEl.textContent = docs.length + " item" + (docs.length !== 1 ? "s" : "") + " in knowledge base";
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
                _allDocs  = docs.filter(d => { const n = d.filename||d.name||""; return !n.startsWith("http"); });
                _allUrls  = docs.filter(d => { const n = d.filename||d.name||""; return  n.startsWith("http"); });
                _allItems = [...docs];
                filterUnifiedTable();
                updateSidebarStats(docs);
            }
        } catch (_) {}
    }, 10000);
}


// ════════════════════════════════════════════════════════════════════════════
//  UNIFIED TABLE
// ════════════════════════════════════════════════════════════════════════════

function filterUnifiedTable() {
    const input   = document.getElementById("kbSearchInput");
    const clearEl = document.getElementById("kbSearchClear");
    const q       = (input ? input.value : "").toLowerCase().trim();

    if (clearEl) clearEl.style.display = q ? "flex" : "none";

    // Show all items when the box is empty or has just 1 character
    const filtered = (!q || q.length >= 1)
        ? (q ? _allItems.filter(d => (d.filename||d.name||"").toLowerCase().includes(q)) : _allItems)
        : _allItems;

    renderUnifiedTable(filtered);
}

function clearKbSearch() {
    const input = document.getElementById("kbSearchInput");
    if (input) input.value = "";
    filterUnifiedTable();
}

function renderUnifiedTable(items) {
    const kbEmpty     = document.getElementById("kbEmpty");
    const kbNoRes     = document.getElementById("kbNoResults");
    const kbTableWrap = document.getElementById("kbTableWrap");
    const tbody       = document.getElementById("kbTableBody");
    const countEl     = document.getElementById("kbItemCount");
    const input       = document.getElementById("kbSearchInput");
    const q           = (input ? input.value : "").trim();

    if (countEl) countEl.textContent = _allItems.length + " item" + (_allItems.length !== 1 ? "s" : "");

    if (_allItems.length === 0) {
        if (kbEmpty)     kbEmpty.style.display     = "flex";
        if (kbNoRes)     kbNoRes.style.display      = "none";
        if (kbTableWrap) kbTableWrap.style.display  = "none";
        return;
    }

    if (items.length === 0) {
        if (kbEmpty)     kbEmpty.style.display     = "none";
        if (kbNoRes)     kbNoRes.style.display      = "flex";
        if (kbTableWrap) kbTableWrap.style.display  = "none";
        return;
    }

    if (kbEmpty)     kbEmpty.style.display     = "none";
    if (kbNoRes)     kbNoRes.style.display      = "none";
    if (kbTableWrap) kbTableWrap.style.display  = "block";

    tbody.innerHTML = "";
    items.forEach(doc => {
        const name    = doc.filename || doc.name || "Unknown";
        const isUrl   = name.startsWith("http://") || name.startsWith("https://");
        const ft      = getFileType(name);
        const tr      = document.createElement("tr");

        let displayName = name;
        let nameCell;
        if (isUrl) {
            let short = name;
            try { const u = new URL(name); short = u.hostname + (u.pathname !== "/" ? u.pathname : ""); } catch(_) {}
            nameCell = `<div class="td-filename"><div class="td-file-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div><a class="td-file-name td-url-link" href="${escHtml(name)}" target="_blank" rel="noopener" title="${escHtml(name)}">${escHtml(short)}</a></div>`;
        } else {
            nameCell = `<div class="td-filename"><div class="td-file-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div><span class="td-file-name" title="${escHtml(name)}">${escHtml(name)}</span></div>`;
        }

        tr.innerHTML = `
            <td>${nameCell}</td>
            <td><span class="type-badge" style="background:${ft.bg};color:${ft.color};border-color:${ft.color}44;">${ft.label}</span></td>
            <td><span class="chunks-badge">${doc.chunks || "&#8212;"}</span></td>
            <td><span class="date-text">${formatDate(doc.ingested_at || doc.date || "&#8212;")}</span></td>
            <td><button class="delete-btn" data-filename="${escHtml(name)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>Remove</button></td>`;
        tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".delete-btn").forEach(btn => {
        btn.addEventListener("click", () => openDeleteModal(btn.dataset.filename));
    });
}

// ── Stubs kept so older code paths don't throw ────────────────────────────
function renderDocsTable() {}
function renderUrlsTable() {}
function filterDocsTable()  { filterUnifiedTable(); }
function filterUrlsTable()  { filterUnifiedTable(); }
function clearDocsSearch()  { clearKbSearch(); }
function clearUrlsSearch()  { clearKbSearch(); }


// ════════════════════════════════════════════════════════════════════════════
//  DRAG & DROP — multi-file
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
    if (e.dataTransfer.files.length > 0) handleFilesSelected(Array.from(e.dataTransfer.files));
});
browseBtn.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
dropZone.addEventListener("click",  () => fileInput.click());
fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) handleFilesSelected(Array.from(e.target.files));
});


// ════════════════════════════════════════════════════════════════════════════
//  FILE SELECTION — multi-file staging list
// ════════════════════════════════════════════════════════════════════════════

const ALLOWED_EXTS = ["pdf","docx","doc","xlsx","xls","pptx","ppt","csv","txt","rtf"];

function handleFilesSelected(files) {
    const valid   = [];
    const invalid = [];

    files.forEach(f => {
        const ext = f.name.split(".").pop().toLowerCase();
        if (ALLOWED_EXTS.includes(ext)) valid.push(f);
        else invalid.push(f.name);
    });

    if (invalid.length) {
        // Non-blocking — warn but still accept valid files
        console.warn("Unsupported files skipped:", invalid.join(", "));
    }

    // Merge with existing staged files (deduplicate by name)
    const existingNames = new Set(selectedFiles.map(f => f.name));
    valid.forEach(f => { if (!existingNames.has(f.name)) selectedFiles.push(f); });

    renderStagedFiles();
}

function renderStagedFiles() {
    const listEl  = document.getElementById("selectedFilesList");
    const qPanel  = document.getElementById("uploadQueuePanel");

    if (!selectedFiles.length) {
        if (listEl) listEl.style.display = "none";
        uploadBtn.disabled = true;
        uploadBtnText.textContent = "Select files to upload";
        return;
    }

    if (listEl) {
        listEl.style.display = "block";
        listEl.innerHTML = selectedFiles.map((f, i) => {
            const ft  = getFileType(f.name);
            const ext = f.name.split(".").pop().toLowerCase();
            return `
            <div class="staged-file-row" data-idx="${i}">
                <div class="staged-file-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div>
                <div class="staged-file-info">
                    <span class="staged-file-name" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
                    <span class="staged-file-size">${formatBytes(f.size)}</span>
                </div>
                <button class="staged-remove-btn" onclick="removeStagedFile(${i})" title="Remove">✕</button>
            </div>`;
        }).join("");
    }

    uploadBtn.disabled = false;
    uploadBtnText.textContent = selectedFiles.length === 1
        ? `Upload 1 file`
        : `Upload ${selectedFiles.length} files`;
}

function removeStagedFile(idx) {
    selectedFiles.splice(idx, 1);
    renderStagedFiles();
}

function clearStagedFiles() {
    selectedFiles = [];
    fileInput.value = "";
    renderStagedFiles();
}


// ════════════════════════════════════════════════════════════════════════════
//  UPLOAD — submit all staged files, show queue panel
// ════════════════════════════════════════════════════════════════════════════

uploadBtn.addEventListener("click", uploadFiles);

async function uploadFiles() {
    if (!selectedFiles.length) return;

    const filesToUpload = [...selectedFiles];
    clearStagedFiles();

    uploadBtn.disabled = true;
    uploadBtn.classList.add("loading");
    uploadBtnText.textContent = "Uploading…";

    const formData = new FormData();
    filesToUpload.forEach(f => formData.append("files", f));

    try {
        const res  = await fetch(`${API}/admin/load-documents`, {
            method: "POST",
            credentials: "include",
            body: formData,
        });
        const data = await res.json();

        // Show the queue panel regardless of partial/full acceptance
        showQueuePanel();

        if (data.accepted && data.accepted.length > 0) {
            // Add each accepted job to our local queue state
            data.accepted.forEach(item => {
                _queuedJobs.push({
                    jobId:    item.job_id,
                    filename: item.filename,
                    status:   "queued",
                    message:  "Waiting in queue…",
                });
            });
        }

        if (data.rejected && data.rejected.length > 0) {
            // Add rejected items as instant-error rows
            data.rejected.forEach(item => {
                _queuedJobs.push({
                    jobId:    null,
                    filename: item.filename,
                    status:   "error",
                    message:  item.reason || "Rejected",
                });
            });
        }

        renderQueuePanel();
        startQueuePolling();

    } catch (err) {
        showQueuePanel();
        filesToUpload.forEach(f => {
            _queuedJobs.push({
                jobId: null, filename: f.name,
                status: "error", message: `Network error: ${err.message}`,
            });
        });
        renderQueuePanel();
    } finally {
        uploadBtn.classList.remove("loading");
        uploadBtn.disabled = true;
        uploadBtnText.textContent = "Select files to upload";
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  QUEUE PANEL — render + polling
// ════════════════════════════════════════════════════════════════════════════

function showQueuePanel() {
    const panel = document.getElementById("uploadQueuePanel");
    if (panel) panel.style.display = "block";
}

function renderQueuePanel() {
    const listEl   = document.getElementById("uqJobList");
    const summaryEl= document.getElementById("uqSummary");
    const clearBtn = document.getElementById("uqClearBtn");
    if (!listEl) return;

    const total     = _queuedJobs.length;
    const done      = _queuedJobs.filter(j => j.status === "done").length;
    const errors    = _queuedJobs.filter(j => j.status === "error").length;
    const active    = _queuedJobs.filter(j => j.status === "processing").length;
    const queued    = _queuedJobs.filter(j => j.status === "queued").length;

    if (summaryEl) {
        const parts = [];
        if (done)    parts.push(`${done} done`);
        if (errors)  parts.push(`${errors} failed`);
        if (active)  parts.push(`${active} processing`);
        if (queued)  parts.push(`${queued} queued`);
        summaryEl.textContent = parts.join(" · ");
    }

    // Show "Clear done" only if there is something to clear
    if (clearBtn) clearBtn.style.display = (done + errors > 0) ? "inline-flex" : "none";

    listEl.innerHTML = _queuedJobs.map((job, i) => {
        const ft = getFileType(job.filename);
        let statusClass = "uq-status-queued";
        let statusIcon  = "⏳";
        let statusLabel = "Queued";

        if (job.status === "processing") { statusClass = "uq-status-processing"; statusIcon = ""; statusLabel = "Processing"; }
        if (job.status === "done")       { statusClass = "uq-status-done";       statusIcon = "✅"; statusLabel = "Done"; }
        if (job.status === "error")      { statusClass = "uq-status-error";      statusIcon = "❌"; statusLabel = "Failed"; }

        const spinnerHtml = job.status === "processing"
            ? `<span class="uq-spinner"></span>`
            : `<span class="uq-status-icon">${statusIcon}</span>`;

        // Progress bar — animates while processing
        const progressHtml = (job.status === "queued" || job.status === "processing")
            ? `<div class="uq-progress-track"><div class="uq-progress-fill ${job.status === "processing" ? "uq-progress-anim" : ""}"></div></div>`
            : "";

        const msgHtml = job.message
            ? `<span class="uq-job-msg ${statusClass}-text">${escHtml(job.message)}</span>`
            : "";

        return `
        <div class="uq-job-row ${statusClass}" data-idx="${i}">
            <div class="uq-job-icon" style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">${ft.icon}</div>
            <div class="uq-job-body">
                <div class="uq-job-top">
                    <span class="uq-job-name" title="${escHtml(job.filename)}">${escHtml(job.filename)}</span>
                    <span class="uq-job-status-wrap">${spinnerHtml}<span class="uq-job-status-label ${statusClass}-text">${statusLabel}</span></span>
                </div>
                ${progressHtml}
                ${msgHtml}
            </div>
        </div>`;
    }).join("");
}

function startQueuePolling() {
    if (_queuePollTimer) return;   // already polling

    _queuePollTimer = setInterval(async () => {
        const activeJobs = _queuedJobs.filter(j => j.jobId && (j.status === "queued" || j.status === "processing"));

        if (!activeJobs.length) {
            clearInterval(_queuePollTimer);
            _queuePollTimer = null;
            loadKnowledgeBase();   // refresh the KB table when all jobs finish
            return;
        }

        let anyChange = false;
        await Promise.all(activeJobs.map(async job => {
            try {
                const res  = await fetch(`${API}/admin/job/${job.jobId}`, { credentials: "include" });
                const data = await res.json();

                if (data.status !== job.status) anyChange = true;

                job.status  = data.status;
                job.message = data.message || job.message;

                if (data.status === "done") {
                    loadKnowledgeBase();   // update KB table as each file completes
                }
            } catch (_) {}
        }));

        if (anyChange) renderQueuePanel();
    }, 2000);
}

function clearCompletedJobs() {
    _queuedJobs = _queuedJobs.filter(j => j.status === "queued" || j.status === "processing");
    renderQueuePanel();
    if (!_queuedJobs.length) {
        const panel = document.getElementById("uploadQueuePanel");
        if (panel) panel.style.display = "none";
    }
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
    modalConfirm.disabled = true;

    // Show feedback in the queue panel or as a temporary toast
    _showGlobalToast(`⏳ Removing '${filename}'…`, "info");

    try {
        const res  = await fetch(`${API}/admin/delete-document`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ filename }),
        });
        const data = await res.json();
        if (data.status === "success") {
            _showGlobalToast(` ${data.message}`, "success");
            loadKnowledgeBase();
        } else if (res.status === 409) {
            _showGlobalToast(` ${data.message}`, "error");
        } else {
            _showGlobalToast(`❌ ${data.message}`, "error");
        }
    } catch (err) {
        _showGlobalToast(`❌ Network error: ${err.message}`, "error");
    } finally {
        modalConfirm.disabled = false;
    }
});

if (refreshBtn) refreshBtn.addEventListener("click", loadKnowledgeBase);


// ════════════════════════════════════════════════════════════════════════════
//  GLOBAL TOAST — lightweight status notification bar
// ════════════════════════════════════════════════════════════════════════════

let _toastTimer = null;

function _showGlobalToast(msg, type = "info") {
    let toast = document.getElementById("globalToast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "globalToast";
        toast.className = "global-toast";
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className   = `global-toast global-toast--${type} global-toast--visible`;
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
        toast.classList.remove("global-toast--visible");
    }, type === "error" ? 6000 : 4000);
}


// ════════════════════════════════════════════════════════════════════════════
//  JOB POLLING HELPER  (used by URL scrape path)
// ════════════════════════════════════════════════════════════════════════════
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

const SECTIONS = ["kb", "chats", "visitors", "bookings", "dissat", "stt"];
const PAGE_TITLES = {
    kb:       ["Knowledge Base Manager",    "Upload documents and URLs to expand what the chatbot knows"],
    chats:    ["Chat Logs",                 "All conversations recorded from users"],
    visitors: ["Visitors",                  "IP, geo, browser and device data for every visitor"],
    bookings: ["Bookings",                  "Test-drive and service slot bookings"],
    dissat:   ["Feedback Issues",        "Users who disliked answers — manage, resolve, or view their chat history"],
    stt:      ["STT Settings",              "Switch the Speech-to-Text provider used for voice input"],
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
    if (name === "stt")      loadSttSettings();
    if (name === "dissat")   loadDissatisfied();
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
//  STT SETTINGS
// ════════════════════════════════════════════════════════════════════════════

async function loadSttSettings() {
    try {
        const res  = await fetch(`${API}/admin/stt/provider`, { credentials: "include" });
        const data = await res.json();
        if (data.status !== "success") return;
        renderSttProviders(data.all, data.provider);
        updateSttBadge(data.provider, data.label);
    } catch (_) {}
}

function updateSttBadge(provider, label) {
    const badge = document.getElementById("sttActiveBadge");
    if (badge) badge.textContent = label || provider;
}

function renderSttProviders(providers, active) {
    const grid = document.getElementById("sttProviderGrid");
    if (!grid) return;
    grid.innerHTML = "";

    providers.forEach(p => {
        const isActive = p.key === active;
        const card = document.createElement("div");
        card.style.cssText = `
            padding:14px 16px; border-radius:12px; cursor:pointer;
            border:2px solid ${isActive ? "#6366f1" : "#e2e8f0"};
            background:${isActive ? "rgba(99,102,241,0.07)" : "#f8fafc"};
            transition:all 0.2s; display:flex; flex-direction:column; gap:6px;`;
        card.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:13px;font-weight:700;color:${isActive ? "#4f46e5" : "#1e293b"};">${escHtml(p.label)}</span>
                ${isActive ? `<span style="width:8px;height:8px;border-radius:50%;background:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,0.2);flex-shrink:0;"></span>` : ""}
            </div>
            ${isActive ? `<span style="font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.5px;">Active</span>` : `<span style="font-size:10px;color:#94a3b8;">Click to activate</span>`}`;

        if (!isActive) {
            card.addEventListener("mouseenter", () => {
                card.style.borderColor = "#a5b4fc";
                card.style.background  = "#f0f4ff";
            });
            card.addEventListener("mouseleave", () => {
                card.style.borderColor = "#e2e8f0";
                card.style.background  = "#f8fafc";
            });
            card.addEventListener("click", () => switchSttProvider(p.key, p.label));
        }
        grid.appendChild(card);
    });
}

async function switchSttProvider(key, label) {
    const statusEl  = document.getElementById("sttStatus");
    const idleNote  = document.getElementById("sttIdleNote");

    if (statusEl) {
        statusEl.style.display    = "block";
        statusEl.style.background = "rgba(99,102,241,0.08)";
        statusEl.style.color      = "#4f46e5";
        statusEl.style.border     = "1px solid rgba(99,102,241,0.2)";
        statusEl.textContent      = `⏳ Switching to ${label}…`;
    }

    try {
        const res  = await fetch(`${API}/admin/stt/provider`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ provider: key }),
        });
        const data = await res.json();

        if (data.status === "success") {
            if (statusEl) {
                statusEl.style.background = "rgba(16,185,129,0.08)";
                statusEl.style.color      = "#059669";
                statusEl.style.border     = "1px solid rgba(16,185,129,0.2)";
                statusEl.textContent      = `✅ ${data.message}`;
            }
            if (idleNote) idleNote.style.display = "inline";
            updateSttBadge(data.provider, data.label);
            // Re-render cards with new active
            const res2  = await fetch(`${API}/admin/stt/provider`, { credentials: "include" });
            const data2 = await res2.json();
            if (data2.status === "success") renderSttProviders(data2.all, data2.provider);
            setTimeout(() => { if (idleNote) idleNote.style.display = "none"; }, 6000);
        } else {
            if (statusEl) {
                statusEl.style.background = "rgba(239,68,68,0.08)";
                statusEl.style.color      = "#dc2626";
                statusEl.style.border     = "1px solid rgba(239,68,68,0.2)";
                statusEl.textContent      = `❌ ${data.message}`;
            }
        }
    } catch (err) {
        if (statusEl) {
            statusEl.style.background = "rgba(239,68,68,0.08)";
            statusEl.style.color      = "#dc2626";
            statusEl.style.border     = "1px solid rgba(239,68,68,0.2)";
            statusEl.textContent      = `❌ Network error: ${err.message}`;
        }
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


// ════════════════════════════════════════════════════════════════════════════
//  DISSATISFIED USERS SECTION
// ════════════════════════════════════════════════════════════════════════════

let _dissatPage        = 1;
let _dissatStatusFilter = "";
let _dissatCurrentRecordId  = null;
let _dissatCurrentVisitorId = null;

// ── DOM refs ────────────────────────────────────────────────────────────────
const dissatLoading    = document.getElementById("dissatLoading");
const dissatEmpty      = document.getElementById("dissatEmpty");
const dissatTableWrap  = document.getElementById("dissatTableWrap");
const dissatTableBody  = document.getElementById("dissatTableBody");
const dissatPagination = document.getElementById("dissatPagination");
const dissatPageInfo   = document.getElementById("dissatPageInfo");
const prevDissatBtn    = document.getElementById("prevDissatPageBtn");
const nextDissatBtn    = document.getElementById("nextDissatPageBtn");
const refreshDissatBtn = document.getElementById("refreshDissatBtn");
const dissatNavBadge   = document.getElementById("dissatNavBadge");

if (refreshDissatBtn) refreshDissatBtn.addEventListener("click", () => loadDissatisfied(true));
if (prevDissatBtn)    prevDissatBtn.addEventListener("click",    () => { _dissatPage--; loadDissatisfied(); });
if (nextDissatBtn)    nextDissatBtn.addEventListener("click",    () => { _dissatPage++; loadDissatisfied(); });

// ── Filter dropdown ──────────────────────────────────────────────────────────
function onDissatFilterChange(select) {
    _dissatStatusFilter = select.value;
    _dissatPage = 1;
    loadDissatisfied();
}

// Keep old filterDissatTab as no-op for safety
function filterDissatTab() {}

// ── Load list ────────────────────────────────────────────────────────────────
async function loadDissatisfied(forceRefresh = false) {
    if (!dissatLoading) return;
    dissatLoading.style.display    = "flex";
    dissatEmpty.style.display      = "none";
    dissatTableWrap.style.display  = "none";
    dissatPagination.style.display = "none";

    try {
        const qs  = new URLSearchParams({
            page:     _dissatPage,
            per_page: 20,
            ..._dissatStatusFilter ? { status: _dissatStatusFilter } : {},
        });
        const res  = await fetch(`${API}/admin/api/dissatisfied-users?${qs}`, { credentials: "include" });
        const data = await res.json();

        dissatLoading.style.display = "none";

        if (data.status !== "success") {
            _showGlobalToast("❌ Failed to load dissatisfied users", "error");
            return;
        }

        // Update count badges
        const c = data.counts || {};
        _setCount("dissatCountAll",      "Total",    c.total    ?? 0);
        _setCount("dissatCountOpen",     "Open",     c.open     ?? 0);
        _setCount("dissatCountSolved",   "Solved",   c.solved   ?? 0);
        _setCount("dissatCountRejected", "Rejected", c.rejected ?? 0);

        // Update nav badge (open count)
        if (dissatNavBadge) {
            const openCount = c.open ?? 0;
            dissatNavBadge.textContent    = openCount;
            dissatNavBadge.style.display  = openCount > 0 ? "inline" : "none";
        }

        if (!data.users || data.users.length === 0) {
            dissatEmpty.style.display = "flex";
            return;
        }

        // Render rows
        dissatTableBody.innerHTML = "";
        data.users.forEach(u => dissatTableBody.appendChild(_renderDissatRow(u)));
        dissatTableWrap.style.display = "block";

        // Pagination
        if (data.pages > 1) {
            dissatPageInfo.textContent     = `Page ${data.page} of ${data.pages}`;
            prevDissatBtn.disabled         = data.page <= 1;
            nextDissatBtn.disabled         = data.page >= data.pages;
            dissatPagination.style.display = "flex";
        }

    } catch (err) {
        dissatLoading.style.display = "none";
        _showGlobalToast("❌ Network error loading dissatisfied users", "error");
    }
}

function _setCount(id, label, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = `${label}: ${val}`;
}

// ── Render a single table row ─────────────────────────────────────────────────
function _renderDissatRow(u) {
    const tr = document.createElement("tr");

    const info     = u.user_info || {};
    const nameText = info.name  ? escAdminHtml(info.name)  : "—";
    const emailTxt = info.email ? `<br><span style="font-size:11px;color:#64748b;">${escAdminHtml(info.email)}</span>` : "";

    const statusMap = {
        open:     '<span class="dissat-badge open">Open</span>',
        solved:   '<span class="dissat-badge solved">Solved</span>',
        rejected: '<span class="dissat-badge rejected">Rejected</span>',
    };
    const badge    = statusMap[u.status] || statusMap.open;
    const shortId  = (u.visitor_id || "").substring(0, 16) + "…";
    const created  = _fmtAdminDate(u.created_at);
    const updated  = _fmtAdminDate(u.updated_at);

    const isClosed = u.status === "solved" || u.status === "rejected";

    tr.innerHTML = `
        <td>
            <span class="visitor-id-link" title="${escAdminHtml(u.visitor_id)}"
                  onclick="openChatViewer('${escAdminHtml(u.visitor_id)}', '${escAdminHtml(u.id)}', '${escAdminHtml(u.status)}')">
                ${escAdminHtml(shortId)}
            </span>
        </td>
        <td>${nameText}${emailTxt}</td>
        <td><span class="dislike-chip">${u.dislike_count || 0} dislikes</span></td>
        <td>${badge}</td>
        <td style="font-size:12px;color:#64748b;">${created}</td>
        <td style="font-size:12px;color:#64748b;">${updated}</td>
        <td>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
                <button class="dissat-action-btn view"
                    onclick="openChatViewer('${escAdminHtml(u.visitor_id)}', '${escAdminHtml(u.id)}', '${escAdminHtml(u.status)}')">
                    View
                </button>
                ${!isClosed ? `
                <button class="dissat-action-btn solve"
                    onclick="updateDissatStatus('${escAdminHtml(u.id)}', 'solved', this)">
                    Solved
                </button>
                <button class="dissat-action-btn reject"
                    onclick="updateDissatStatus('${escAdminHtml(u.id)}', 'rejected', this)">
                    Rejected
                </button>` : `
                <button class="dissat-action-btn view"
                    onclick="updateDissatStatus('${escAdminHtml(u.id)}', 'open', this)">
                    Re-open
                </button>`}
            </div>
        </td>`;
    return tr;
}

// ── Update status from table row ─────────────────────────────────────────────
async function updateDissatStatus(recordId, status, btn) {
    if (btn) btn.disabled = true;
    try {
        const res  = await fetch(`${API}/admin/api/dissatisfied-users/${recordId}/status`, {
            method:      "POST",
            headers:     { "Content-Type": "application/json" },
            credentials: "include",
            body:        JSON.stringify({ status }),
        });
        const data = await res.json();
        if (data.status === "success") {
            _showGlobalToast(`Marked as ${status}`, "success");
            loadDissatisfied();
            // Also refresh viewer if it's open for this record
            if (_dissatCurrentRecordId === recordId) {
                _updateCvStatusUI(status);
            }
        } else {
            _showGlobalToast((data.message || "Update failed"), "error");
        }
    } catch (e) {
        _showGlobalToast("❌ Network error", "error");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ════════════════════════════════════════════════════════════════════════════
//  CHAT VIEWER — slide-in panel
// ════════════════════════════════════════════════════════════════════════════

const chatViewerOverlay = document.getElementById("chatViewerOverlay");
const chatViewerClose   = document.getElementById("chatViewerClose");
const cvTitle           = document.getElementById("cvTitle");
const cvMeta            = document.getElementById("cvMeta");
const cvBody            = document.getElementById("cvBody");
const cvLoading         = document.getElementById("cvLoading");
const cvSolveBtn        = document.getElementById("cvSolveBtn");
const cvRejectBtn       = document.getElementById("cvRejectBtn");
const cvReopenBtn       = document.getElementById("cvReopenBtn");
const cvStatusBadgeWrap = document.getElementById("cvStatusBadgeWrap");

if (chatViewerClose)   chatViewerClose.addEventListener("click", closeChatViewer);
if (chatViewerOverlay) chatViewerOverlay.addEventListener("click", e => {
    if (e.target === chatViewerOverlay) closeChatViewer();
});
document.addEventListener("keydown", e => {
    if (e.key === "Escape" && chatViewerOverlay?.classList.contains("visible")) closeChatViewer();
});

if (cvSolveBtn)  cvSolveBtn.addEventListener("click",  () => updateDissatStatus(_dissatCurrentRecordId, "solved",   cvSolveBtn));
if (cvRejectBtn) cvRejectBtn.addEventListener("click",  () => updateDissatStatus(_dissatCurrentRecordId, "rejected", cvRejectBtn));
if (cvReopenBtn) cvReopenBtn.addEventListener("click",  () => updateDissatStatus(_dissatCurrentRecordId, "open",     cvReopenBtn));
async function openChatViewer(visitorId, recordId, currentStatus) {
    _dissatCurrentVisitorId = visitorId;
    _dissatCurrentRecordId  = recordId;

    // Open panel
    chatViewerOverlay.classList.add("visible");
    cvBody.innerHTML = "";
    const loadingDiv = document.createElement("div");
    loadingDiv.className = "cv-loading";
    loadingDiv.id = "cvLoadingInner";
    loadingDiv.innerHTML = `<div class="kb-spinner"></div><span>Loading conversation…</span>`;
    cvBody.appendChild(loadingDiv);

    cvTitle.textContent = "Loading…";
    cvMeta.innerHTML    = "";
    _updateCvStatusUI(currentStatus);

    try {
        const res  = await fetch(`${API}/admin/api/visitor-chat-history/${encodeURIComponent(visitorId)}`, {
            credentials: "include",
        });
        const data = await res.json();

        loadingDiv.remove();

        if (data.status !== "success") {
            cvBody.innerHTML = `<div class="cv-empty"><p>Failed to load chat history.</p></div>`;
            return;
        }

        // Header
        const v   = data.visitor || {};
        const dis = data.dis_record || {};
        const info = dis.user_info || {};

        cvTitle.textContent = info.name
            ? `${info.name}'s Chat History`
            : `Visitor: ${visitorId.substring(0, 20)}…`;

        // Meta chips
        const chips = [];
        if (info.email) chips.push({ icon: "",   text: info.email });
        if (info.phone) chips.push({ icon: "",   text: info.phone });
        chips.push({ icon: "", text: `${data.total_messages} messages` });
        chips.push({ icon: "", text: `${dis.dislike_count || 0} dislikes` });
        if (v.country)  chips.push({ icon: "", text: v.country });
        if (v.browser)  chips.push({ icon: "", text: v.browser });

        cvMeta.innerHTML = chips.map(c =>
            `<span class="chat-viewer-meta-chip">${escAdminHtml((c.icon + " " + c.text).trim())}</span>`
        ).join("");

        // Render conversation turns
        if (!data.history || data.history.length === 0) {
            cvBody.innerHTML = `<div class="cv-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <p>No chat history found for this visitor.</p>
            </div>`;
            return;
        }

        data.history.forEach((turn, i) => {
            const turnEl = document.createElement("div");
            turnEl.className = "cv-turn";

            const ts = _fmtAdminDate(turn.created_at);
            const fbClass  = turn.feedback === "dislike" ? "cv-disliked"
                           : turn.feedback === "like"    ? "cv-liked" : "";
            const fbPill   = turn.feedback === "dislike"
                ? `<div class="cv-feedback-pill disliked">User marked this response as not helpful</div>`
                : turn.feedback === "like"
                ? `<div class="cv-feedback-pill liked">User marked this response as helpful</div>`
                : "";

            turnEl.innerHTML = `
                <div class="cv-turn-number">Turn ${i + 1}</div>
                <div class="cv-ts">${ts}</div>
                <div class="cv-user">${escAdminHtml(turn.query || "")}</div>
                <div class="cv-bot ${fbClass}">
                    ${_renderCvAnswer(turn.answer || "")}
                    ${fbPill}
                </div>`;
            cvBody.appendChild(turnEl);
        });

        // Scroll to first disliked message if any
        setTimeout(() => {
            const firstDisliked = cvBody.querySelector(".cv-disliked");
            if (firstDisliked) firstDisliked.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 200);

    } catch (err) {
        cvBody.innerHTML = `<div class="cv-empty"><p>Network error: ${escAdminHtml(err.message)}</p></div>`;
    }
}

function closeChatViewer() {
    chatViewerOverlay?.classList.remove("visible");
    _dissatCurrentVisitorId = null;
    _dissatCurrentRecordId  = null;
}

function _updateCvStatusUI(status) {
    if (!cvSolveBtn || !cvRejectBtn || !cvReopenBtn) return;
    const isClosed = status === "solved" || status === "rejected";
    cvSolveBtn.style.display  = isClosed ? "none" : "inline-flex";
    cvRejectBtn.style.display = isClosed ? "none" : "inline-flex";
    cvReopenBtn.style.display = isClosed ? "inline-flex" : "none";

    const statusMap = {
        open:     '<span class="dissat-badge open">Open</span>',
        solved:   '<span class="dissat-badge solved">Solved</span>',
        rejected: '<span class="dissat-badge rejected">Rejected</span>',
    };
    if (cvStatusBadgeWrap) cvStatusBadgeWrap.innerHTML = statusMap[status] || "";
}

// Render answer — simple markdown-lite for the viewer (tables + line breaks)
function _renderCvAnswer(raw) {
    if (!raw) return "";
    let html = escAdminHtml(raw);
    // Restore line breaks
    html = html.replace(/\n/g, "<br>");
    return html;
}

function escAdminHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function _fmtAdminDate(raw) {
    if (!raw) return "—";
    try {
        const d = new Date(String(raw).replace(" ", "T") + (raw.includes("Z") ? "" : "Z"));
        if (isNaN(d.getTime())) return raw;
        return d.toLocaleString(undefined, {
            month: "short", day: "numeric", year: "numeric",
            hour: "2-digit", minute: "2-digit",
        });
    } catch { return raw; }
}

// ── Auto-load open count on page load (for nav badge) ────────────────────────
(async function _initDissatBadge() {
    try {
        const res  = await fetch(`${API}/admin/api/dissatisfied-users?status=open&per_page=1`, { credentials: "include" });
        const data = await res.json();
        if (data.status === "success" && dissatNavBadge) {
            const count = data.counts?.open ?? data.total ?? 0;
            dissatNavBadge.textContent   = count;
            dissatNavBadge.style.display = count > 0 ? "inline" : "none";
        }
    } catch (_) {}
}());
