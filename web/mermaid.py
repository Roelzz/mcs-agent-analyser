import html
import re

import reflex as rx


def split_markdown_mermaid(md: str) -> list[tuple[str, str]]:
    """Split markdown into alternating (type, content) segments.

    Returns list of ("markdown", text) and ("mermaid", diagram_code) tuples.
    """
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
    segments: list[tuple[str, str]] = []
    last_end = 0

    for match in pattern.finditer(md):
        before = md[last_end : match.start()]
        if before.strip():
            segments.append(("markdown", before.strip()))
        segments.append(("mermaid", match.group(1).strip()))
        last_end = match.end()

    after = md[last_end:]
    if after.strip():
        segments.append(("markdown", after.strip()))

    return segments


def mermaid_script() -> rx.Component:
    """Load mermaid.js CDN and auto-render diagrams via MutationObserver.

    Supports dynamic light/dark theme switching and injects readability CSS.
    """
    return rx.fragment(
        rx.script(src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"),
        rx.script(
            """
            (function() {
                // Inject readability CSS
                (function injectCSS() {
                    var style = document.createElement('style');
                    style.textContent = [
                        '.rx-Markdown { line-height: 1.75; font-size: 15px; }',
                        '.rx-Markdown table { border-collapse: collapse; width: 100%; min-width: 600px; font-size: 13.5px; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }',
                        '.rx-Markdown th, .rx-Markdown td { border: 1px solid var(--gray-a5); padding: 8px 14px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; max-width: 400px; vertical-align: top; }',
                        '.rx-Markdown th { background: var(--gray-a3); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }',
                        '.rx-Markdown tr:nth-child(even) td { background: var(--gray-a2); }',
                        '.rx-Markdown pre:not(.mermaid) { background: var(--gray-a3); border: 1px solid var(--gray-a5); border-radius: 8px; padding: 16px; overflow-x: auto; font-size: 13px; font-family: \\'JetBrains Mono\\', monospace; }',
                        '.rx-Markdown code:not(pre code) { background: var(--gray-a3); border-radius: 4px; padding: 2px 6px; font-size: 0.875em; font-family: \\'JetBrains Mono\\', monospace; }',
                        'pre.mermaid { background: var(--gray-a2); border: 1px solid var(--gray-a4); border-radius: 10px; padding: 24px; margin: 16px 0; }',
                        '.rx-Markdown h2 { margin-top: 2.5em; margin-bottom: 0.75em; }',
                        '.rx-Markdown h3 { margin-top: 2em; margin-bottom: 0.75em; padding-bottom: 0.4em; border-bottom: 1px solid var(--gray-a4); }',
                        '.rx-Markdown h4 { margin-top: 1.5em; margin-bottom: 0.5em; }',
                        '.rx-Markdown blockquote { border-left: 3px solid var(--amber-8); padding: 8px 16px; margin: 12px 0; background: var(--amber-a2); border-radius: 0 6px 6px 0; }',
                        '.rx-Markdown ul, .rx-Markdown ol { padding-left: 1.5em; margin: 8px 0; }',
                        '.rx-Markdown li { margin-bottom: 4px; }',
                        '.rx-Markdown hr { border: none; border-top: 1px solid var(--gray-a4); margin: 2em 0; }',
                        '@media print { #report-content { position: absolute; top: 0; left: 0; width: 100%; z-index: 99999; background: white; } #report-content button, #report-content hr, #report-content [role="separator"] { display: none !important; } nav, header, [class*="navbar"], [class*="NavBar"] { display: none !important; } @page { margin: 1.5cm; } }',
                    ].join('\\n');
                    document.head.appendChild(style);
                })();

                function getMermaidTheme() {
                    var cl = document.documentElement.className;
                    return cl.indexOf('dark') !== -1 ? 'dark' : 'default';
                }

                function initMermaidObserver() {
                    if (typeof mermaid === 'undefined') {
                        setTimeout(initMermaidObserver, 100);
                        return;
                    }
                    mermaid.initialize({ startOnLoad: false, theme: getMermaidTheme() });

                    var isRendering = false;

                    function fixIdleBars() {
                        var isDark = document.documentElement.className.indexOf('dark') !== -1;
                        document.querySelectorAll('pre.mermaid svg rect.task.done.crit, pre.mermaid svg rect.task.crit.done').forEach(function(r) {
                            r.style.setProperty('fill', isDark ? '#2a2a2a' : '#e5e5e5', 'important');
                            r.style.setProperty('stroke', isDark ? '#555555' : '#a3a3a3', 'important');
                        });
                        document.querySelectorAll('pre.mermaid svg text.taskText.done.crit, pre.mermaid svg text.taskText.crit.done').forEach(function(t) {
                            t.style.setProperty('fill', isDark ? '#cccccc' : '#525252', 'important');
                        });
                    }

                    function storeAndRender() {
                        if (isRendering) return;
                        var els = Array.from(document.querySelectorAll('pre.mermaid:not([data-processed])'));
                        els.forEach(function(el) {
                            if (!el.getAttribute('data-mermaid-source')) {
                                el.setAttribute('data-mermaid-source', el.textContent);
                            }
                        });
                        if (els.length > 0) {
                            isRendering = true;
                            mermaid.run({ nodes: els }).then(function() {
                                fixIdleBars();
                                isRendering = false;
                            }).catch(function(err) {
                                console.error('Mermaid render error:', err);
                                isRendering = false;
                            });
                        }
                    }

                    function rerenderAll() {
                        mermaid.initialize({ startOnLoad: false, theme: getMermaidTheme() });
                        document.querySelectorAll('pre.mermaid').forEach(function(el) {
                            var src = el.getAttribute('data-mermaid-source');
                            if (src) { el.removeAttribute('data-processed'); el.innerHTML = src; }
                        });
                        storeAndRender();
                    }

                    storeAndRender();

                    // Watch for new mermaid nodes (Reflex SPA navigation)
                    var domObserver = new MutationObserver(function(mutations) {
                        var hasNew = false;
                        for (var i = 0; i < mutations.length; i++) {
                            if (mutations[i].addedNodes.length > 0) { hasNew = true; break; }
                        }
                        if (hasNew) { storeAndRender(); }
                    });
                    domObserver.observe(document.body, { childList: true, subtree: true });

                    // Watch for color mode changes on <html> element
                    new MutationObserver(function(muts) {
                        muts.forEach(function(m) {
                            if (m.attributeName === 'class') { rerenderAll(); }
                        });
                    }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
                }

                initMermaidObserver();
            })();
            """
        ),
    )


def build_standalone_html(markdown: str, title: str) -> str:
    """Build a self-contained HTML file from report markdown.

    Uses CDN-loaded marked.js and mermaid.js to render markdown and diagrams.
    """
    # Escape for JS template literal: backslashes first, then backticks, then ${}
    escaped = markdown.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/marked@15/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.75; font-size: 15px; max-width: 960px; margin: 0 auto; padding: 32px 24px; color: #1a1a1a; background: #fff; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
  th, td {{ border: 1px solid #d4d4d4; padding: 8px 14px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  pre:not(.mermaid) {{ background: #f5f5f5; border: 1px solid #d4d4d4; border-radius: 8px; padding: 16px; overflow-x: auto; font-size: 13px; }}
  code:not(pre code) {{ background: #f5f5f5; border-radius: 4px; padding: 2px 6px; font-size: 0.875em; }}
  pre.mermaid {{ background: #fafafa; border: 1px solid #e5e5e5; border-radius: 10px; padding: 24px; margin: 16px 0; }}
  h2 {{ margin-top: 2.5em; margin-bottom: 0.75em; }}
  h3 {{ margin-top: 2em; margin-bottom: 0.75em; padding-bottom: 0.4em; border-bottom: 1px solid #e5e5e5; }}
  h4 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
  blockquote {{ border-left: 3px solid #f59e0b; padding: 8px 16px; margin: 12px 0; background: #fffbeb; border-radius: 0 6px 6px 0; }}
  ul, ol {{ padding-left: 1.5em; margin: 8px 0; }}
  li {{ margin-bottom: 4px; }}
  hr {{ border: none; border-top: 1px solid #e5e5e5; margin: 2em 0; }}
  @media print {{ body {{ max-width: 100%; padding: 0; }} }}
</style>
</head>
<body>
<div id="content"></div>
<script>
(function() {{
  const md = `{escaped}`;

  // Custom renderer: mermaid code blocks -> <pre class="mermaid">
  const renderer = new marked.Renderer();
  const origCode = renderer.code.bind(renderer);
  renderer.code = function(token) {{
    if (token.lang === 'mermaid') {{
      return '<pre class="mermaid">' + token.text + '</pre>';
    }}
    return origCode(token);
  }};

  document.getElementById('content').innerHTML = marked.parse(md, {{ renderer: renderer }});
  mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
  mermaid.run();
}})();
</script>
</body>
</html>"""


def render_segment(segment: dict) -> rx.Component:
    """Render a single report segment (markdown or mermaid)."""
    return rx.cond(
        segment["type"] == "mermaid",
        rx.box(
            rx.el.pre(segment["content"], class_name="mermaid"),
            width="100%",
            min_height="200px",
            overflow_x="auto",
        ),
        rx.markdown(segment["content"]),
    )


def md_to_segments(md: str) -> list[dict]:
    """Split markdown into text/mermaid segments as dicts for dynamic view."""
    if not md:
        return []
    segments: list[dict] = []
    remaining = md
    fence_open = "```mermaid"
    fence_close = "```"
    while remaining:
        start = remaining.find(fence_open)
        if start == -1:
            segments.append({"type": "text", "content": remaining})
            break
        if start > 0:
            segments.append({"type": "text", "content": remaining[:start]})
        rest = remaining[start + len(fence_open) :]
        end = rest.find(fence_close)
        if end == -1:
            segments.append({"type": "text", "content": fence_open + rest})
            break
        mermaid_src = rest[:end].strip()
        segments.append({"type": "mermaid", "content": mermaid_src})
        remaining = rest[end + len(fence_close) :]
    return segments


def render_segment_styled(segment: dict) -> rx.Component:
    """Render a segment with green-themed styling for the dynamic view."""
    return rx.cond(
        segment["type"] == "mermaid",
        rx.box(
            rx.el.pre(segment["content"], class_name="mermaid"),
            width="100%",
            overflow_x="auto",
            padding="22px",
            background="var(--green-a2)",
            border="1px solid var(--green-a4)",
            border_radius="14px",
            margin_y="4px",
        ),
        rx.box(
            rx.markdown(
                segment["content"],
                component_map={
                    "h1": lambda text: rx.heading(text, size="6", margin_bottom="10px", color="var(--gray-12)"),
                    "h2": lambda text: rx.heading(
                        text, size="4", margin_top="18px", margin_bottom="8px", color="var(--gray-12)"
                    ),
                    "h3": lambda text: rx.heading(
                        text, size="3", margin_top="14px", margin_bottom="6px", color="var(--gray-11)"
                    ),
                    "p": lambda text: rx.text(text, font_size="13px", color="var(--gray-11)", line_height="1.65"),
                    "code": lambda text: rx.code(text, font_size="12px", background="var(--green-a3)"),
                },
            ),
            width="100%",
            overflow_x="auto",
            padding="2px 2px 6px",
        ),
    )
