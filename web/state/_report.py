import reflex as rx
from loguru import logger

from web.mermaid import split_markdown_mermaid


class ReportMixin(rx.State, mixin=True):
    """Report vars and handlers."""

    # Report vars
    report_markdown: str = ""
    report_title: str = ""
    report_source: str = ""  # "upload" | "import" | ""
    report_custom_findings: list[dict] = []

    @rx.var
    def has_report(self) -> bool:
        return bool(self.report_markdown)

    @rx.var
    def has_custom_findings(self) -> bool:
        return len(self.report_custom_findings) > 0

    @rx.var
    def report_segments(self) -> list[dict[str, str]]:
        if not self.report_markdown:
            return []
        segments = split_markdown_mermaid(self.report_markdown)
        return [{"type": t, "content": c} for t, c in segments]

    def _evaluate_custom_rules(self, profile: object) -> None:
        """Evaluate custom rules against a BotProfile and store findings."""
        from custom_rules import evaluate_rules
        from models import CustomRule

        rule_dicts = self.get_custom_rules()  # type: ignore[attr-defined]
        if not rule_dicts:
            self.report_custom_findings = []
            return
        try:
            parsed = [CustomRule(**r) for r in rule_dicts]
            results = evaluate_rules(parsed, profile)
            self.report_custom_findings = results
            logger.debug("Custom rules evaluated: {} findings from {} rules", len(results), len(parsed))
        except Exception as e:
            logger.warning("Custom rule evaluation failed: {}", e)
            self.report_custom_findings = []

    # --- Report handlers ---

    @rx.event
    def download_report(self):
        filename = f"{self.report_title}.md" if self.report_title else "report.md"
        yield rx.download(data=self.report_markdown, filename=filename)
        yield rx.toast(f"Report saved as {filename}", duration=3000)

    @rx.event
    def download_report_html(self):
        from web.mermaid import build_standalone_html

        title = self.report_title or "report"
        html = build_standalone_html(self.report_markdown, title)
        filename = f"{title}.html"
        yield rx.download(data=html, filename=filename)
        yield rx.toast(f"Report saved as {filename}", duration=3000)

    @rx.event
    def download_report_pdf(self):
        yield rx.call_script("window.print()")
        yield rx.toast("Print dialog opened", duration=3000)

    @rx.event
    def copy_report_to_clipboard(self):
        yield rx.set_clipboard(self.report_markdown)
        yield rx.toast("Report copied to clipboard", duration=3000)
