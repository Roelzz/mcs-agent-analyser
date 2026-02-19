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
    """Load mermaid.js CDN and auto-render diagrams via MutationObserver."""
    return rx.fragment(
        rx.script(src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"),
        rx.script(
            """
            (function() {
                function initMermaidObserver() {
                    if (typeof mermaid === 'undefined') {
                        setTimeout(initMermaidObserver, 100);
                        return;
                    }
                    mermaid.initialize({ startOnLoad: false, theme: 'neutral' });

                    function renderUnprocessed() {
                        var els = document.querySelectorAll('pre.mermaid:not([data-processed])');
                        if (els.length > 0) {
                            mermaid.run({ nodes: els });
                        }
                    }

                    renderUnprocessed();

                    var observer = new MutationObserver(function(mutations) {
                        var dominated = false;
                        for (var i = 0; i < mutations.length; i++) {
                            if (mutations[i].addedNodes.length > 0) {
                                dominated = true;
                                break;
                            }
                        }
                        if (dominated) { renderUnprocessed(); }
                    });
                    observer.observe(document.body, { childList: true, subtree: true });
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
