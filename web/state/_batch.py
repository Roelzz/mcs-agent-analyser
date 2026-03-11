import json
import tempfile
from pathlib import Path

import reflex as rx
from loguru import logger

from batch_analytics import aggregate_timelines, render_batch_report
from timeline import build_timeline
from transcript import parse_transcript_json

BATCH_UPLOAD_ID = "batch_upload"


class BatchMixin(rx.State, mixin=True):
    """Batch analytics state mixin."""

    batch_is_processing: bool = False
    batch_error: str = ""
    batch_report_md: str = ""
    batch_count: int = 0

    @rx.var
    def batch_segments(self) -> list[dict[str, str]]:
        if not self.batch_report_md:
            return []
        from web.mermaid import split_markdown_mermaid

        segments = split_markdown_mermaid(self.batch_report_md)
        return [{"type": t, "content": c} for t, c in segments]

    @rx.event
    async def handle_batch_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.batch_error = "No files selected."
            return

        self.batch_is_processing = True
        self.batch_error = ""
        self.batch_report_md = ""
        self.batch_count = 0
        yield

        try:
            timelines = []
            metadata_list = []

            for upload_file in files:
                if not upload_file.filename.endswith(".json"):
                    continue

                data = await upload_file.read()
                self.batch_count = len(timelines) + 1
                yield

                with tempfile.TemporaryDirectory() as tmpdir:
                    json_path = Path(tmpdir) / upload_file.filename
                    json_path.write_bytes(data)

                    try:
                        activities, metadata = parse_transcript_json(json_path)
                        timeline = build_timeline(activities, {})
                        timelines.append(timeline)
                        metadata_list.append(metadata)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"Skipping {upload_file.filename}: {e}")

            if not timelines:
                self.batch_error = "No valid transcript files found."
                return

            self.batch_count = len(timelines)
            yield

            summary = aggregate_timelines(timelines, metadata_list)
            self.batch_report_md = render_batch_report(summary)

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            self.batch_error = f"Processing failed: {e}"
        finally:
            self.batch_is_processing = False
            yield

    @rx.event
    def clear_batch(self):
        self.batch_is_processing = False
        self.batch_error = ""
        self.batch_report_md = ""
        self.batch_count = 0
