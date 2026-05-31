#!/usr/bin/env python3
"""Snapshot the live Firefox triage dashboard into a static GH-Pages site.

One-shot script: run with a dashboard at http://127.0.0.1:8765, produces
docs/*.html files that can be served as a static site. All mutating
interactions are disabled; pending-feedback add/remove is rewired to a
client-side localStorage shim so visitors can play with it without a
backend.

Safety: aborts if any pending JSON or copied investigation file mentions
sec-* keywords, to prevent accidentally publishing a security bug.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

DASHBOARD = "http://127.0.0.1:8765"
TRIAGE_DIR = Path.home() / "firefox-triage"
INVESTIGATIONS_SRC = Path.home() / "firefox-bug-investigation"
REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
INV_DIR = REPO / "investigations"

# These four tabs cover the entire UI surface today.
TABS = ["triaged", "needs-info", "close", "watching"]
DEFAULT_TAB = "triaged"  # index.html will be a copy of this tab's landing

SEC_KEYWORDS = {
    "sec-critical", "sec-high", "sec-moderate", "sec-low",
    "sec-vector", "sec-other", "sec-audit",
}


def fetch(path: str) -> str:
    with urllib.request.urlopen(f"{DASHBOARD}{path}", timeout=10) as r:
        return r.read().decode("utf-8")


def fetch_bytes(path: str) -> bytes:
    with urllib.request.urlopen(f"{DASHBOARD}{path}", timeout=10) as r:
        return r.read()


def sec_keyword_check() -> None:
    """Abort if any pending draft or copied investigation mentions sec-*."""
    hits: list[tuple[str, list[str]]] = []
    for p in (TRIAGE_DIR / "pending").glob("bug-*.json"):
        d = json.loads(p.read_text())
        kws = set((d.get("keywords_add") or []) + (
            d.get("bug_context", {}).get("keywords") or []))
        bad = sorted(kws & SEC_KEYWORDS)
        if bad:
            hits.append((p.name, bad))
    for p in INV_DIR.glob("*.md"):
        body = p.read_text()
        bad = sorted(k for k in SEC_KEYWORDS if k in body)
        if bad:
            hits.append((p.name, bad))
    if hits:
        print("ABORT: sec-* keywords found:", file=sys.stderr)
        for name, bad in hits:
            print(f"  {name}: {bad}", file=sys.stderr)
        sys.exit(1)
    print(f"  sec-* check: clean ({len(list((TRIAGE_DIR / 'pending').glob('bug-*.json')))} drafts, {len(list(INV_DIR.glob('*.md')))} investigations)")


def bug_ids_per_tab() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for tab in TABS:
        html = fetch(f"/?tab={tab}")
        ids = sorted({int(m) for m in re.findall(
            rf"\?tab={re.escape(tab)}&bug=(\d+)", html)})
        out[tab] = ids
    return out


def url_to_filename(tab: str, bug: int | None) -> str:
    if bug is None:
        return f"{tab}.html"
    return f"{tab}-bug-{bug}.html"


# ─── HTML transformations ─────────────────────────────────────────────


_NOINDEX = '<meta name="robots" content="noindex,nofollow">\n  '
_DEMO_BANNER = (
    '<div class="demo-banner" role="note">'
    'Static demo &middot; interactions simulated &middot; '
    'bug data from public Bugzilla A/V bugs'
    '</div>'
)
_FEEDBACK_SHIM = """
<script>
// Static-demo shims: localStorage-backed feedback + fetch+swap navigation.
// Together they preserve the htmx feel (no full-page repaint when switching
// tabs / focused cards) while running entirely client-side.
(function () {
  const KEY = (bugId) => 'triage-demo:feedback:' + bugId;

  function read(bugId) {
    try { return JSON.parse(localStorage.getItem(KEY(bugId)) || '[]'); }
    catch (_) { return []; }
  }
  function write(bugId, list) {
    localStorage.setItem(KEY(bugId), JSON.stringify(list));
  }

  function ensureHost(bugId) {
    let host = document.querySelector('[data-feedback-list="' + bugId + '"]');
    if (host) return host;
    // No server-rendered list — create one ourselves, inserted right before
    // the composer form for this bug.
    const form = document.querySelector('form[data-feedback-form="' + bugId + '"]');
    if (!form) return null;
    const section = document.createElement('section');
    section.className = 'pending-feedback';
    section.innerHTML =
      '<h4 class="pending-feedback-head">Pending feedback</h4>' +
      '<ul class="pending-feedback-list" data-feedback-list="' + bugId + '"></ul>';
    form.parentNode.insertBefore(section, form);
    return section.querySelector('[data-feedback-list]');
  }

  function render(bugId) {
    const list = read(bugId);
    const host = ensureHost(bugId);
    if (!host) return;
    if (!list.length) {
      // Hide the whole section when empty so the empty state stays clean.
      const section = host.closest('.pending-feedback');
      if (section) section.style.display = 'none';
      host.innerHTML = '';
      return;
    }
    const section = host.closest('.pending-feedback');
    if (section) section.style.display = '';
    host.innerHTML = list.map((fb, i) =>
      '<li class="pending-feedback-item">' +
        '<span class="pending-feedback-text"></span>' +
        '<button type="button" class="pending-feedback-remove" ' +
          'aria-label="Remove" title="Remove" ' +
          'data-feedback-remove="' + bugId + '" data-index="' + i + '">' +
          '\\u2715' +
        '</button>' +
      '</li>'
    ).join('');
    const items = host.querySelectorAll('.pending-feedback-text');
    list.forEach((fb, i) => items[i].textContent = fb.text);
  }

  document.addEventListener('submit', (e) => {
    const form = e.target.closest('form[data-feedback-form]');
    if (!form) return;
    e.preventDefault();
    const bugId = form.getAttribute('data-feedback-form');
    const ta = form.querySelector('textarea');
    const text = (ta && ta.value || '').trim();
    if (!text) return;
    const list = read(bugId);
    list.push({ text, ts: new Date().toISOString() });
    write(bugId, list);
    if (ta) ta.value = '';
    render(bugId);
  });

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-feedback-remove]');
    if (!btn) return;
    e.preventDefault();
    const bugId = btn.getAttribute('data-feedback-remove');
    const idx = parseInt(btn.getAttribute('data-index'), 10);
    const list = read(bugId);
    list.splice(idx, 1);
    write(bugId, list);
    render(bugId);
  });

  function initFeedback() {
    document.querySelectorAll('form[data-feedback-form]').forEach((form) => {
      render(form.getAttribute('data-feedback-form'));
    });
  }
  initFeedback();

  // ─── fetch+swap navigation shim ───────────────────────────────────
  // Intercept clicks on .tab / .rail-item / .queue-dropdown-jump / .deck-prev
  // / .deck-next and swap only #tab-content, mirroring what the live htmx
  // app does. Hotkeys (arrow keys, j/k, /, a) keep working because their
  // handler just calls .click() on these same elements.
  const NAV_PATTERN = /^[a-z\\-]+(?:-bug-\\d+)?\\.html$/;

  function parseFilename(name) {
    const m = (name || '').match(/^([a-z\\-]+)(?:-bug-(\\d+))?\\.html$/);
    if (!m) return null;
    const tab = m[1] === 'index' ? 'triaged' : m[1];
    return { tab, bug: m[2] || null };
  }

  function syncActiveStates(parsed) {
    document.querySelectorAll('.tab').forEach((t) => {
      const p = parseFilename(t.getAttribute('href') || '');
      const isActive = !!(p && p.tab === parsed.tab);
      t.classList.toggle('tab--active', isActive);
      t.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    if (parsed.bug) {
      document.querySelectorAll('.rail-item').forEach((el) => {
        el.classList.toggle('is-active', el.dataset.bugId === parsed.bug);
      });
    }
  }

  async function navigate(href, push, swapSel) {
    const parsed = parseFilename(href);
    if (!parsed) return false;
    const sel = swapSel || '#tab-content';
    try {
      const resp = await fetch(href);
      if (!resp.ok) return false;
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const newNode = doc.querySelector(sel);
      const curNode = document.querySelector(sel);
      if (!newNode || !curNode) return false;
      curNode.innerHTML = newNode.innerHTML;

      if (push !== false) history.pushState({}, '', href);
      syncActiveStates(parsed);
      initFeedback();
      // Let any existing afterSwap/afterSettle handlers in base.html run
      // (autosizeAll, etc).
      document.dispatchEvent(new CustomEvent('htmx:afterSwap'));
      document.dispatchEvent(new CustomEvent('htmx:afterSettle'));
      return true;
    } catch (_) {
      return false;
    }
  }

  document.addEventListener('click', (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || (e.button && e.button !== 0)) return;
    const el = e.target.closest('a[href], [data-nav-target]');
    if (!el) return;
    const target = el.getAttribute('data-nav-target') || el.getAttribute('href');
    if (!target || !NAV_PATTERN.test(target)) return;
    const swapSel = el.getAttribute('data-nav-swap');
    e.preventDefault();
    navigate(target, true, swapSel);
  });

  window.addEventListener('popstate', () => {
    const name = (window.location.pathname.split('/').pop() || 'index.html');
    navigate(name, false);
  });
})();
</script>
"""

_DEMO_CSS = """
<style>
.demo-banner {
  background: #fff7d6;
  color: #5b4a00;
  border-bottom: 1px solid #e8d27a;
  padding: 6px 14px;
  font: 13px/1.5 -apple-system, system-ui, sans-serif;
  text-align: center;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
"""


def disable_button(match: re.Match[str]) -> str:
    """Convert a mutation button into a disabled placeholder."""
    tag = match.group(0)
    # Strip hx-* attributes
    tag = re.sub(r'\s+hx-[a-z\-]+="[^"]*"', "", tag)
    # Add disabled + tooltip
    if "disabled" not in tag:
        tag = tag.replace("<button", '<button disabled title="demo — actions disabled"', 1)
    return tag


def rewrite_tab_links(html: str, current_tab: str) -> str:
    """Rewrite tab/queue/rail href + hx-get from `?tab=...` to static files.

    href becomes `X.html` or `X-bug-Y.html`; hx-get is converted to
    `data-nav-target="..."` so buttons that only had hx-get (deck-prev,
    deck-next) keep a navigable destination for the JS nav shim.
    """
    # href="?tab=X&bug=Y" → href="X-bug-Y.html"   (must come before tab-only)
    html = re.sub(
        r'href="\?tab=([a-z\-]+)&(?:amp;)?bug=(\d+)"',
        lambda m: f'href="{url_to_filename(m.group(1), int(m.group(2)))}"',
        html,
    )
    # href="?tab=X" → href="X.html"
    html = re.sub(
        r'href="\?tab=([a-z\-]+)"',
        lambda m: f'href="{url_to_filename(m.group(1), None)}"',
        html,
    )
    # hx-get="?tab=X&bug=Y" → data-nav-target="X-bug-Y.html"
    html = re.sub(
        r'hx-get="\?tab=([a-z\-]+)&(?:amp;)?bug=(\d+)"',
        lambda m: f'data-nav-target="{url_to_filename(m.group(1), int(m.group(2)))}"',
        html,
    )
    # hx-get="?tab=X" → data-nav-target="X.html"
    html = re.sub(
        r'hx-get="\?tab=([a-z\-]+)"',
        lambda m: f'data-nav-target="{url_to_filename(m.group(1), None)}"',
        html,
    )
    # Preserve the swap target so deck-prev/next can swap #deck-area only
    # (keeping the rail mounted) while tab clicks swap the full #tab-content.
    html = re.sub(
        r'hx-target="(#[a-zA-Z0-9\-_]+)"',
        lambda m: f'data-nav-swap="{m.group(1)}"',
        html,
    )
    # Strip the remaining htmx co-attributes.
    html = re.sub(r'\s+hx-(swap|push-url|vals|select)="[^"]*"', "", html)
    html = re.sub(r'\s+hx-on::?[a-zA-Z\-]+="[^"]*"', "", html)
    return html


def rewrite_bug_links(html: str) -> str:
    """No-op now — folded into rewrite_tab_links to share the regex set."""
    return html


def rewrite_investigation_links(html: str) -> str:
    """Point investigation links at the locally-rendered HTML pages."""
    return re.sub(
        r'href="https://github\.com/alastor0325/firefox-bug-investigation/blob/main/bug-(\d+)-investigation\.md"',
        r'href="investigations/bug-\1.html"',
        html,
    )


# ─── Minimal markdown renderer for investigation pages ────────────────


def _inline_md(text: str) -> str:
    text = html_mod.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    return text


def _parse_frontmatter(md: str) -> tuple[dict[str, str], str]:
    lines = md.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, md
    fm: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if line.startswith("  - ") or line.startswith("  -"):
            fm.setdefault("_listitems", "")
            fm["_listitems"] += line.strip()[2:].strip() + "\n"
        elif ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
        i += 1
    return fm, "\n".join(lines[i + 1:])


def _render_body(body: str) -> str:
    out: list[str] = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            cls = f' class="lang-{html_mod.escape(lang)}"' if lang else ""
            out.append(
                f"<pre><code{cls}>" + html_mod.escape("\n".join(code)) + "</code></pre>"
            )
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline_md(m.group(2))}</h{level}>")
            i += 1
            continue
        if re.match(r"^\s*[-*]\s+", line):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                stripped = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append("<li>" + _inline_md(stripped) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                stripped = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                items.append("<li>" + _inline_md(stripped) + "</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        paras = [line]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].startswith(("#", "```", "- ", "* "))
            and not re.match(r"^\s*\d+\.\s+", lines[i])
        ):
            paras.append(lines[i])
            i += 1
        out.append("<p>" + _inline_md(" ".join(paras)) + "</p>")
    return "\n".join(out)


_INV_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex,nofollow">
  <title>{title}</title>
  <link rel="stylesheet" href="../static/style.css">
  <style>
    body {{ background: #fafafa; color: #1a1a1a; font-family: -apple-system, system-ui, sans-serif; line-height: 1.55; }}
    .inv-shell {{ max-width: 880px; margin: 0 auto; padding: 24px 32px 60px; }}
    .inv-back {{ display: inline-block; margin: 8px 0 16px; color: #555; text-decoration: none; font-size: 13px; }}
    .inv-back:hover {{ color: #111; }}
    .inv-fm {{ background: #fff; border: 1px solid #e6e6e6; border-radius: 8px; padding: 14px 18px; margin: 8px 0 24px; font-size: 13px; }}
    .inv-fm dt {{ font-weight: 600; color: #555; }}
    .inv-fm dd {{ margin: 0 0 8px; }}
    .inv-body h1 {{ font-size: 22px; margin: 18px 0 12px; }}
    .inv-body h2 {{ font-size: 18px; margin: 22px 0 10px; }}
    .inv-body h3 {{ font-size: 15px; margin: 18px 0 8px; }}
    .inv-body code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 90%; }}
    .inv-body pre {{ background: #1f2330; color: #f0f0f0; padding: 12px; border-radius: 6px; overflow-x: auto; }}
    .inv-body pre code {{ background: none; color: inherit; padding: 0; }}
    .inv-body a {{ color: #1a5cb8; }}
    .inv-body ul, .inv-body ol {{ padding-left: 22px; }}
    .demo-banner {{ background: #fff7d6; color: #5b4a00; border-bottom: 1px solid #e8d27a; padding: 6px 14px; font: 13px/1.5 -apple-system, system-ui, sans-serif; text-align: center; }}
  </style>
</head>
<body>
  <div class="demo-banner">Static demo &middot; investigation rendered from markdown</div>
  <div class="inv-shell">
    <a class="inv-back" href="../{back_href}">&larr; back to dashboard</a>
    {frontmatter_html}
    <div class="inv-body">{body_html}</div>
  </div>
</body>
</html>
"""


_FM_FIELDS = (
    "bug_id", "investigated_at", "status", "depth", "root_cause",
    "regression_range", "related_bugs", "complexity", "notes",
)


def _format_frontmatter(fm: dict[str, str]) -> str:
    if not fm:
        return ""
    rows: list[str] = []
    for key in _FM_FIELDS:
        if key in fm and fm[key]:
            rows.append(
                f"<dt>{html_mod.escape(key)}</dt>"
                f"<dd>{_inline_md(fm[key])}</dd>"
            )
    listitems = fm.get("_listitems")
    if listitems:
        items = [li for li in listitems.strip().split("\n") if li]
        rows.append("<dt>affected_files</dt><dd><ul>" + "".join(
            f"<li>{_inline_md(li)}</li>" for li in items) + "</ul></dd>")
    if not rows:
        return ""
    return f'<dl class="inv-fm">{"".join(rows)}</dl>'


def render_investigations(triaged_ids: list[int]) -> None:
    """Render each available investigation MD into docs/investigations/bug-N.html."""
    dest = DOCS / "investigations"
    dest.mkdir(parents=True, exist_ok=True)
    for bug_id in triaged_ids:
        src = INV_DIR / f"bug-{bug_id}-investigation.md"
        if not src.exists():
            continue
        md = src.read_text()
        fm, body = _parse_frontmatter(md)
        page = _INV_PAGE_TEMPLATE.format(
            title=f"Bug {bug_id} investigation",
            back_href=f"triaged-bug-{bug_id}.html",
            frontmatter_html=_format_frontmatter(fm),
            body_html=_render_body(body),
        )
        (dest / f"bug-{bug_id}.html").write_text(page)
        print(f"  inv: bug-{bug_id}.html")


def rewrite_brand_title(html: str) -> str:
    """Strip the brand-title link (real repo is private)."""
    return re.sub(
        r'<h1 class="brand-title"><a [^>]+>Triage</a></h1>',
        '<h1 class="brand-title">Triage</h1>',
        html,
    )


def strip_sse(html: str) -> str:
    """Remove the EventSource block — no server to push events from."""
    # The SSE init block lives inside an IIFE. Replace just the EventSource
    # construction with a no-op return so the rest of the script is harmless.
    return re.sub(
        r'const es = new EventSource\([^)]+\);',
        '/* SSE disabled in static demo */ return;',
        html,
    )


def rewire_feedback(html: str) -> str:
    """Convert the pending-feedback form and remove buttons to the JS shim."""
    # 1. The composer form: hx-post="/draft/N/refine" → data-feedback-form="N"
    html = re.sub(
        r'<form([^>]*?)hx-post="/draft/(\d+)/refine"([^>]*?)>',
        lambda m: f'<form{m.group(1)}data-feedback-form="{m.group(2)}"{m.group(3)}>',
        html,
    )
    # 2. The remove buttons: hx-post="/draft/N/refine/remove" → data-feedback-remove
    # In the live render the remove is per-row inside a list rendered server-side.
    # Static snapshots have empty lists (no feedback at snapshot time), so the
    # JS shim populates everything client-side on render(bugId).
    # Mark the host <ul> and the empty-state element for the shim to find.
    html = re.sub(
        r'<ul class="pending-feedback-list">',
        '<ul class="pending-feedback-list" data-feedback-list="__BUG__">',
        html,
    )
    # We'll fix __BUG__ in pass_two_per_bug() since the placeholder needs the
    # actual bug id from the surrounding card.
    # 3. Strip any remaining hx-* on feedback rows (shouldn't be any, but defensive)
    html = re.sub(r'\s+hx-(post|target|swap|vals)="/draft/\d+/refine[^"]*"', "", html)
    return html


def disable_mutation_buttons(html: str) -> str:
    """Disable Apply / Reassign / queue-remove buttons (no backend)."""
    # Apply / Apply & close / Reassign — these all hx-post to /draft/N/apply
    html = re.sub(
        r'<button[^>]*hx-post="/draft/\d+/apply"[^>]*>[^<]*</button>',
        disable_button,
        html,
    )
    # Queue remove (only present if queue non-empty)
    html = re.sub(
        r'<button[^>]*hx-post="/queue/remove"[^>]*>[^<]*</button>',
        disable_button,
        html,
    )
    # Strip the hx-post attribute from the process-queue summary if any
    html = re.sub(r'\s+hx-post="/[^"]+"', "", html)
    return html


def fix_static_paths(html: str) -> str:
    """Convert /static/foo to static/foo so it works under GH Pages subpaths."""
    html = re.sub(r'(src|href)="/static/', r'\1="static/', html)
    html = re.sub(r'(src|href)="/favicon\.svg', r'\1="favicon.svg', html)
    return html


def inject_head_and_banner(html: str) -> str:
    """Add noindex meta, demo CSS, demo banner, and feedback shim."""
    # noindex + demo CSS go into <head>
    html = html.replace("<head>", "<head>\n  " + _NOINDEX + _DEMO_CSS, 1)
    # Banner right after <body>
    html = re.sub(
        r'(<body[^>]*>)',
        r'\1\n' + _DEMO_BANNER,
        html,
        count=1,
    )
    # Feedback shim before </body>
    html = html.replace("</body>", _FEEDBACK_SHIM + "\n</body>", 1)
    return html


def per_bug_fixups(html: str, bug_id: int | None) -> str:
    """Substitute the __BUG__ placeholder with the focused-card's bug id."""
    if bug_id is None:
        # On a tab landing page that focuses on bug X automatically, we still
        # need to set the placeholder. The dashboard's focused card has the
        # bug id in a data attribute on the article. Pull from the rendered
        # html instead of guessing.
        m = re.search(r'<article[^>]*data-bug-id="(\d+)"', html)
        if m:
            bug_id = int(m.group(1))
    if bug_id is None:
        # Watching tab has no card.
        html = html.replace('data-feedback-list="__BUG__"', "")
    else:
        html = html.replace("__BUG__", str(bug_id))
    return html


def transform(html: str, current_tab: str, bug_id: int | None) -> str:
    html = rewrite_brand_title(html)
    html = rewrite_tab_links(html, current_tab)
    html = rewrite_bug_links(html)
    html = rewrite_investigation_links(html)
    html = strip_sse(html)
    html = rewire_feedback(html)
    html = disable_mutation_buttons(html)
    html = fix_static_paths(html)
    html = inject_head_and_banner(html)
    html = per_bug_fixups(html, bug_id)
    return html


# ─── Static asset mirroring ───────────────────────────────────────────


def mirror_static() -> None:
    """Download every /static/* file referenced by any snapshotted page."""
    # The dashboard's known static surface — keep this list tight; we only
    # need what's actually loaded.
    paths = [
        "/static/style.css",
        "/static/favicon.svg",
        "/favicon.svg",
        "/static/htmx.min.js",
    ]
    (DOCS / "static").mkdir(parents=True, exist_ok=True)
    for p in paths:
        try:
            body = fetch_bytes(p)
        except Exception as e:
            print(f"  skip {p}: {e}")
            continue
        # /favicon.svg → docs/favicon.svg, /static/* → docs/static/*
        out = DOCS / p.lstrip("/")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
        print(f"  static: {p} ({len(body)} bytes)")


# ─── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("Snapshotting Firefox triage dashboard")
    print(f"  dashboard:     {DASHBOARD}")
    print(f"  output:        {DOCS}")
    print(f"  investigations: {INV_DIR}")

    # Wipe & recreate docs/ — one-shot script.
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)

    sec_keyword_check()
    mirror_static()

    per_tab = bug_ids_per_tab()
    for tab, ids in per_tab.items():
        print(f"  {tab}: {len(ids)} bug(s)")

    # Render investigation MDs for analyzed-tab bugs to HTML pages so the
    # "Open full investigation →" link works locally and on GH Pages
    # without needing a separate repo to land first.
    render_investigations(per_tab.get("triaged", []))

    pages_written = 0

    # 1. Tab landing pages (each defaults to its first bug, server-chosen).
    for tab in TABS:
        html = fetch(f"/?tab={tab}")
        out = DOCS / url_to_filename(tab, None)
        out.write_text(transform(html, tab, None))
        pages_written += 1

    # 2. Per-bug focused permalinks.
    for tab, ids in per_tab.items():
        for bug in ids:
            html = fetch(f"/?tab={tab}&bug={bug}")
            out = DOCS / url_to_filename(tab, bug)
            out.write_text(transform(html, tab, bug))
            pages_written += 1

    # 3. index.html = a copy of the default tab's landing page.
    default = DOCS / url_to_filename(DEFAULT_TAB, None)
    if default.exists():
        shutil.copyfile(default, DOCS / "index.html")
        pages_written += 1

    print(f"  wrote {pages_written} HTML page(s) to {DOCS}")
    print("done.")


if __name__ == "__main__":
    main()
