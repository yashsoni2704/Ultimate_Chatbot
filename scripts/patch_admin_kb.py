"""
Replaces the entire #section-kb block in admin.html with the new unified layout.
"""
import os

HTML_FILE = os.path.join(os.path.dirname(__file__), "..", "templates", "admin.html")

NEW_SECTION = '''            <div id="section-kb">

                <!-- ── Top bar ── -->
                <div class="kb-topbar">
                    <span id="kbTotalCount" class="kb-total-count"></span>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <div class="kb-upload-dropdown" id="kbUploadDropdown">
                            <button class="kb-new-btn" id="kbNewBtn" onclick="toggleUploadMenu()">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                                New Upload
                                <svg class="kb-new-chevron" id="kbNewChevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                            </button>
                            <div class="kb-upload-menu" id="kbUploadMenu" style="display:none;">
                                <button class="kb-upload-option" onclick="openUploadForm(\'doc\')">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                                    <span><strong>Document</strong><span class="kb-option-hint">PDF, DOCX, XLSX&#8230;</span></span>
                                </button>
                                <button class="kb-upload-option" onclick="openUploadForm(\'url\')">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                                    <span><strong>URL / Website</strong><span class="kb-option-hint">Web page, Drive, OneDrive</span></span>
                                </button>
                            </div>
                        </div>
                        <button class="refresh-btn" id="refreshBtn" title="Refresh" onclick="loadKnowledgeBase()">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                            Refresh
                        </button>
                    </div>
                </div>

                <!-- ── Collapsible upload forms ── -->
                <div id="kbUploadPanel" style="display:none;margin-bottom:20px;">

                    <!-- Document upload -->
                    <section class="upload-card" id="kbFormDoc" style="display:none;">
                        <div class="upload-card-header">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                            <h3>Upload Document</h3>
                            <button class="kb-form-close" onclick="closeUploadForm()" title="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                        </div>
                        <div id="dropZone" class="drop-zone">
                            <div class="drop-zone-inner">
                                <div class="drop-icon-wrap" id="dropIconWrap"><svg class="drop-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg></div>
                                <p class="drop-title">Drag &amp; drop your file here</p>
                                <p class="drop-sub">PDF, DOCX, XLSX, PPTX, CSV, TXT, RTF</p>
                                <input type="file" id="fileInput" accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.csv,.txt,.rtf" style="display:none;">
                                <button class="browse-btn" id="browseBtn">Browse File</button>
                            </div>
                        </div>
                        <div id="filePreview" class="file-preview" style="display:none;">
                            <div class="file-preview-icon" id="fileTypeIcon"></div>
                            <div class="file-preview-body">
                                <p class="file-preview-name" id="previewName">&#8212;</p>
                                <div class="file-preview-meta"><span class="file-type-badge" id="fileTypeBadge">&#8212;</span><span class="file-preview-size" id="previewSize">&#8212;</span></div>
                            </div>
                            <button class="remove-btn" id="removeFileBtn" title="Remove"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                        </div>
                        <button class="upload-btn" id="uploadBtn" disabled>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                            <span id="uploadBtnText">Select a file to upload</span>
                        </button>
                        <div id="progressWrap" class="progress-wrap" style="display:none;"><div class="progress-bar-track"><div class="progress-bar-fill" id="progressBar"></div></div><span class="progress-label" id="progressLabel">Processing&#8230;</span></div>
                        <div id="uploadStatus" class="upload-status" style="display:none;"></div>
                    </section>

                    <!-- URL scrape -->
                    <section class="upload-card" id="kbFormUrl" style="display:none;">
                        <div class="upload-card-header">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                            <h3>Scrape Website / URL</h3>
                            <button class="kb-form-close" onclick="closeUploadForm()" title="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                        </div>
                        <div class="url-input-wrap">
                            <div class="url-input-row">
                                <div class="url-input-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg></div>
                                <input type="url" id="scrapeUrl" class="url-input" placeholder="https://example.com/page" autocomplete="off"/>
                            </div>
                            <p class="url-hint">Paste any public URL &#8212; web page, Google Drive file, or OneDrive link.</p>
                        </div>
                        <button class="upload-btn" id="scrapeBtn">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                            <span id="scrapeBtnText">Scrape &amp; Ingest</span>
                        </button>
                        <div id="scrapeProgressWrap" class="progress-wrap" style="display:none;"><div class="progress-bar-track"><div class="progress-bar-fill" id="scrapeProgressBar"></div></div><span class="progress-label" id="scrapeProgressLabel">Scraping page&#8230;</span></div>
                        <div id="scrapeStatus" class="upload-status" style="display:none;"></div>
                    </section>

                </div><!-- /kbUploadPanel -->

                <!-- ── Unified KB table ── -->
                <section class="kb-section">
                    <div class="kb-section-header">
                        <h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>All Knowledge</h3>
                        <span id="kbItemCount" class="panel-count">0 items</span>
                    </div>
                    <div class="kb-search-wrap" style="margin:16px 24px 4px;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        <input type="text" id="kbSearchInput" class="kb-search-input" placeholder="Search documents and URLs&#8230;" autocomplete="off" oninput="filterUnifiedTable()">
                        <button class="kb-search-clear" id="kbSearchClear" onclick="clearKbSearch()" style="display:none;" title="Clear">&#10005;</button>
                    </div>
                    <div id="kbLoading" class="kb-loading"><div class="kb-spinner"></div><span>Loading&#8230;</span></div>
                    <div id="kbEmpty" class="kb-empty" style="display:none;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 13h6m-3-3v6m-9 1V7a2 2 0 0 1 2-2h6l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                        <p>Nothing here yet</p><p class="kb-empty-sub">Click &#8220;New Upload&#8221; to add documents or URLs</p>
                    </div>
                    <div id="kbNoResults" class="kb-empty" style="display:none;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        <p>No matching items</p>
                    </div>
                    <div id="kbTableWrap" class="kb-table-wrap" style="display:none;padding-top:12px;">
                        <table class="kb-table">
                            <thead><tr><th>Name / URL</th><th>Type</th><th>Chunks</th><th>Ingested</th><th>Action</th></tr></thead>
                            <tbody id="kbTableBody"></tbody>
                        </table>
                    </div>
                </section>

            </div><!-- /section-kb -->'''

with open(HTML_FILE, "r", encoding="utf-8") as f:
    html = f.read()

START_MARKER = '            <div id="section-kb">'
END_MARKER   = '            </div><!-- /section-kb -->'

start = html.find(START_MARKER)
end   = html.find(END_MARKER) + len(END_MARKER)

if start == -1 or end == -1:
    print("ERROR: markers not found")
else:
    html = html[:start] + NEW_SECTION + html[end:]
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK: section-kb replaced")
