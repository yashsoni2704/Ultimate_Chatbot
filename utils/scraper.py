"""
Web scraper — extracts ALL visible text from a single URL using
Playwright (headless Chromium) + BeautifulSoup for deep cleaning.

Strategy
--------
1.  Launch headless Chromium with a realistic user-agent
2.  Navigate and wait for networkidle (full JS render)
3.  Auto-scroll top-to-bottom to trigger lazy-loaded content
4.  Expand hidden content (details/summary, display:none sections)
5.  Extract text from main frame + all iframes
6.  Handle Shadow DOM via JS injection
7.  Deep-clean HTML with BeautifulSoup
8.  Build section-based LangChain Documents (one per heading block)
9.  Line-level deduplication (hashes) to remove repeated nav/footer text
10. Validate minimum content — raise if page appears empty/blocked

Returns: list of LangChain Document objects
"""

import hashlib
import re
from datetime import datetime
from urllib.parse import urlparse

from langchain_core.documents import Document

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Noise tags stripped before text extraction ────────────────────────────
_STRIP_TAGS = {
    "script", "style", "noscript", "svg", "canvas",
    "nav", "footer", "header", "aside", "form",
    "button", "input", "select", "textarea",
    "iframe",   # iframes handled separately
    "figure",   # usually images with captions already in alt
}

# ── Heading tags used to split content into sections ─────────────────────
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# ── JS to force all hidden elements visible ───────────────────────────────
_JS_EXPAND_HIDDEN = """
() => {
    // Open all <details> elements
    document.querySelectorAll('details').forEach(el => el.open = true);

    // Force display:none and visibility:hidden elements visible
    document.querySelectorAll('*').forEach(el => {
        const style = window.getComputedStyle(el);
        if (style.display === 'none') {
            el.style.setProperty('display', 'block', 'important');
        }
        if (style.visibility === 'hidden') {
            el.style.setProperty('visibility', 'visible', 'important');
        }
    });
}
"""

# ── JS to extract Shadow DOM text ─────────────────────────────────────────
_JS_SHADOW_TEXT = """
() => {
    const results = [];
    function extractShadow(root) {
        root.querySelectorAll('*').forEach(el => {
            if (el.shadowRoot) {
                const text = el.shadowRoot.textContent || '';
                if (text.trim().length > 20) results.push(text.trim());
                extractShadow(el.shadowRoot);
            }
        });
    }
    extractShadow(document);
    return results.join('\\n');
}
"""


# ════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ════════════════════════════════════════════════════════════════════════════

def _line_hash(text: str) -> str:
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


def _deduplicate_lines(text: str) -> str:
    """Remove exact-duplicate lines (handles repeated nav/footer text)."""
    seen = set()
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        h = _line_hash(stripped)
        if h not in seen:
            seen.add(h)
            out.append(line)
    return "\n".join(out)


def _clean_html(html: str) -> "BeautifulSoup":
    """Parse HTML and strip all noise tags."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    # Remove noise tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Remove common ad/cookie/banner class patterns
    noise_patterns = re.compile(
        r"cookie|banner|popup|modal|overlay|advertisement|ad-|"
        r"sidebar|breadcrumb|pagination|social|share|newsletter|"
        r"subscribe|promo|alert|notification|toast",
        re.I
    )
    for tag in soup.find_all(True):
        if not tag.attrs:
            continue
        classes = " ".join(tag.get("class", []))
        tag_id  = tag.get("id", "")
        if noise_patterns.search(classes) or noise_patterns.search(tag_id):
            tag.decompose()

    return soup


def _extract_table(table_tag) -> str:
    """Convert a <table> to pipe-separated readable text."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = []
        for cell in tr.find_all(["td", "th"]):
            text = cell.get_text(separator=" ", strip=True)
            if text:
                cells.append(text)
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _soup_to_sections(soup) -> list:
    """
    Walk the cleaned soup and build a list of (heading, body_text) tuples.
    Content before the first heading goes into a 'Page Content' section.
    Tables are converted to pipe-separated text inline.
    """
    sections = []
    current_heading = "Page Content"
    current_lines = []

    def flush():
        text = "\n".join(current_lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excessive blank lines
        if text:
            sections.append((current_heading, text))

    body = soup.find("body") or soup
    for el in body.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue
        # Only process direct meaningful elements, skip deeply nested duplicates
        if el.name in _HEADING_TAGS:
            flush()
            current_lines = []
            current_heading = el.get_text(separator=" ", strip=True) or current_heading
        elif el.name == "table":
            table_text = _extract_table(el)
            if table_text.strip():
                current_lines.append(table_text)
        elif el.name == "li":
            text = el.get_text(separator=" ", strip=True)
            if text:
                current_lines.append(f"• {text}")
        elif el.name in {"p", "blockquote", "pre", "code", "dd", "dt"}:
            text = el.get_text(separator=" ", strip=True)
            if text:
                current_lines.append(text)

    flush()
    return sections


def _get_page_metadata(page) -> dict:
    """Extract title, meta description, og tags from a Playwright page."""
    meta = {}
    try:
        meta["title"] = page.title() or ""
    except Exception:
        meta["title"] = ""

    try:
        desc = page.locator('meta[name="description"]').get_attribute("content", timeout=2000)
        meta["description"] = desc or ""
    except Exception:
        meta["description"] = ""

    try:
        og_title = page.locator('meta[property="og:title"]').get_attribute("content", timeout=2000)
        meta["og_title"] = og_title or ""
    except Exception:
        meta["og_title"] = ""

    try:
        og_desc = page.locator('meta[property="og:description"]').get_attribute("content", timeout=2000)
        meta["og_description"] = og_desc or ""
    except Exception:
        meta["og_description"] = ""

    try:
        canonical = page.locator('link[rel="canonical"]').get_attribute("href", timeout=2000)
        meta["canonical"] = canonical or ""
    except Exception:
        meta["canonical"] = ""

    return meta


def _extract_iframe_texts(page) -> list:
    """Extract visible text from all accessible iframes."""
    texts = []
    try:
        for frame in page.frames[1:]:   # skip main frame (index 0)
            try:
                html = frame.content()
                if not html or len(html) < 100:
                    continue
                soup = _clean_html(html)
                body = soup.find("body")
                if body:
                    text = body.get_text(separator="\n", strip=True)
                    if len(text.strip()) > 50:
                        texts.append(text.strip())
            except Exception:
                continue
    except Exception:
        pass
    return texts


# ════════════════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════════════════

def scrape_url(url: str) -> list:
    """
    Scrape *url* and return a list of LangChain Document objects.

    Each Document represents one section of the page
    (heading + its content block) for precise chunk retrieval.

    Raises
    ------
    ValueError   if extracted text is below SCRAPING_MIN_CHARS
                 (page is likely blocked, empty, or login-walled)
    RuntimeError on Playwright/browser errors
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    logger.info("=" * 80)
    logger.info("🌐  WEB SCRAPING STARTED")
    logger.info(f"  URL       : {url}")
    logger.info(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Timeout   : {Config.SCRAPING_TIMEOUT}s")
    logger.info("=" * 80)

    domain = urlparse(url).netloc
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )

        page = context.new_page()

        # ── 1. Navigate and wait for full render ──────────────────────────
        logger.info("  → Navigating to URL...")
        try:
            page.goto(
                url,
                wait_until="networkidle",
                timeout=Config.SCRAPING_TIMEOUT * 1000,
            )
        except PlaywrightTimeout:
            logger.warning("  ⚠️  networkidle timeout — trying domcontentloaded fallback")
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=Config.SCRAPING_TIMEOUT * 1000,
                )
                page.wait_for_timeout(5000)   # give JS 5 extra seconds to render
            except PlaywrightTimeout:
                browser.close()
                raise RuntimeError(f"Page failed to load within {Config.SCRAPING_TIMEOUT}s: {url}")

        logger.info("  ✅ Page loaded")

        # ── 2. Auto-scroll to trigger lazy-loaded content ─────────────────
        logger.info("  → Scrolling page to trigger lazy content...")
        try:
            page.evaluate("""
                async () => {
                    await new Promise(resolve => {
                        let total = 0;
                        const step = 300;
                        const delay = 80;
                        const timer = setInterval(() => {
                            window.scrollBy(0, step);
                            total += step;
                            if (total >= document.body.scrollHeight) {
                                window.scrollTo(0, 0);
                                clearInterval(timer);
                                resolve();
                            }
                        }, delay);
                    });
                }
            """)
            page.wait_for_timeout(2500)
        except Exception as e:
            logger.warning(f"  ⚠️  Scroll failed (non-fatal): {e}")

        # ── 3. Expand hidden content ──────────────────────────────────────
        logger.info("  → Expanding hidden content (details, display:none)...")
        try:
            page.evaluate(_JS_EXPAND_HIDDEN)
            page.wait_for_timeout(800)
        except Exception as e:
            logger.warning(f"  ⚠️  Hidden content expand failed (non-fatal): {e}")

        # ── 4. Get page metadata ──────────────────────────────────────────
        logger.info("  → Extracting page metadata...")
        page_meta = _get_page_metadata(page)
        logger.info(f"  Title: {page_meta.get('title', 'N/A')}")

        # ── 5. Get main page HTML ─────────────────────────────────────────
        logger.info("  → Extracting main frame HTML...")
        main_html = page.content()

        # ── 6. Extract Shadow DOM text ────────────────────────────────────
        logger.info("  → Extracting Shadow DOM content...")
        shadow_text = ""
        try:
            shadow_text = page.evaluate(_JS_SHADOW_TEXT) or ""
            if shadow_text.strip():
                logger.info(f"  Shadow DOM: {len(shadow_text)} chars extracted")
        except Exception as e:
            logger.warning(f"  ⚠️  Shadow DOM extraction failed (non-fatal): {e}")

        # ── 7. Extract iframe texts ───────────────────────────────────────
        logger.info("  → Extracting iframe content...")
        iframe_texts = _extract_iframe_texts(page)
        logger.info(f"  iFrames: {len(iframe_texts)} frame(s) with content")

        browser.close()

    # ── 8. Clean and parse main HTML ─────────────────────────────────────
    logger.info("  → Cleaning HTML and extracting sections...")
    soup = _clean_html(main_html)
    sections = _soup_to_sections(soup)
    logger.info(f"  Sections found: {len(sections)}")

    # ── 9. Build base metadata dict ───────────────────────────────────────
    base_metadata = {
        "source":      url,
        "source_type": "url",
        "domain":      domain,
        "title":       page_meta.get("title", ""),
        "description": page_meta.get("description", "") or page_meta.get("og_description", ""),
        "scraped_at":  scraped_at,
    }

    # ── 10. Build Documents from sections ────────────────────────────────
    seen_hashes = set()
    documents = []

    for heading, body_text in sections:
        # Deduplicate lines within each section
        clean_body = _deduplicate_lines(body_text)
        clean_body = clean_body.strip()
        if not clean_body or len(clean_body) < 30:
            continue

        # Skip near-duplicate sections (same content under different heading)
        content_hash = _line_hash(clean_body[:200])
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        # Cap individual section size
        if len(clean_body) > Config.SCRAPING_MAX_CHARS:
            clean_body = clean_body[:Config.SCRAPING_MAX_CHARS]
            logger.warning(f"  ⚠️  Section '{heading}' truncated to {Config.SCRAPING_MAX_CHARS} chars")

        # Format: heading on first line, then body
        page_content = f"{heading}\n\n{clean_body}" if heading != "Page Content" else clean_body

        doc_meta = {**base_metadata, "section": heading}
        if not isinstance(doc_meta, dict):
            doc_meta = {"source": url, "source_type": "url", "section": heading}
        documents.append(Document(page_content=page_content, metadata=doc_meta))

    # ── 11. Append shadow DOM and iframe content as extra documents ───────
    extra_text_parts = []
    if shadow_text.strip():
        extra_text_parts.append(_deduplicate_lines(shadow_text))
    for iframe_text in iframe_texts:
        extra_text_parts.append(_deduplicate_lines(iframe_text))

    for extra in extra_text_parts:
        extra = extra.strip()
        if len(extra) < 50:
            continue
        content_hash = _line_hash(extra[:200])
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        documents.append(Document(
            page_content=extra,
            metadata={**base_metadata, "section": "embedded_content"},
        ))

    # ── 12. Validate minimum content ─────────────────────────────────────
    total_chars = sum(len(d.page_content) for d in documents)
    logger.info(f"  Total characters extracted: {total_chars}")
    logger.info(f"  Total documents (sections): {len(documents)}")

    if total_chars < Config.SCRAPING_MIN_CHARS:
        raise ValueError(
            f"Extracted only {total_chars} characters from '{url}'. "
            f"The page may be blocked, empty, or require login. "
            f"Minimum required: {Config.SCRAPING_MIN_CHARS} characters."
        )

    logger.info("=" * 80)
    logger.info("🌐  WEB SCRAPING COMPLETE")
    logger.info(f"  Documents : {len(documents)}")
    logger.info(f"  Characters: {total_chars}")
    logger.info("=" * 80)

    return documents
