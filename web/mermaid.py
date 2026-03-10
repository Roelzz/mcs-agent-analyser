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
