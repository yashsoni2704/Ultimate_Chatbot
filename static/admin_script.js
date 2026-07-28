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
        const ext      = filename.split(".").pop().toLowerCase();

        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>
                <div class="td-filename">
                    <div class="td-file-icon"
                         style="background:${ft.bg};color:${ft.color};border:1px solid ${ft.color}44;">
                        ${ft.icon}
                    </div>
                    <span class="td-file-name" title="${escHtml(filename)}">${escHtml(filename)}</span>
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
