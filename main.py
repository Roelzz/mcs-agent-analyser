import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from loguru import logger

from parser import parse_dialog_json, parse_yaml
from renderer import render_report, render_transcript_report
from timeline import build_timeline
from transcript import parse_transcript_json

load_dotenv()

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="{time:DD-MM-YYYY at HH:mm:ss} | {level: <8} | {message}",
)

app = typer.Typer(help="Copilot Studio Bot Analyser — generates Markdown reports from bot exports.")


def _process_folder(folder: Path, output: Path | None = None) -> Path:
    """Process a single bot export folder and generate a report."""
    yaml_path = folder / "botContent.yml"
    json_path = folder / "dialog.json"

    if not yaml_path.exists():
        logger.error(f"botContent.yml not found in {folder}")
        raise typer.Exit(1)
    if not json_path.exists():
        logger.error(f"dialog.json not found in {folder}")
        raise typer.Exit(1)

    logger.info(f"Parsing {folder.name}...")

    profile, schema_lookup = parse_yaml(yaml_path)
    logger.info(f"Bot: {profile.display_name} ({len(profile.components)} components)")

    activities = parse_dialog_json(json_path)
    logger.info(f"Dialog: {len(activities)} activities")

    timeline = build_timeline(activities, schema_lookup)
    logger.info(
        f"Timeline: {len(timeline.events)} events, {len(timeline.phases)} phases, {len(timeline.errors)} errors"
    )

    report = render_report(profile, timeline)

    if output is None:
        output = folder / "report.md"

    output.write_text(report, encoding="utf-8")
    logger.info(f"Report written to {output}")
    return output


def _process_transcript(json_path: Path) -> Path:
    """Process a single transcript JSON and generate a report."""
    logger.info(f"Parsing transcript {json_path.name}...")
    activities, metadata = parse_transcript_json(json_path)
    timeline = build_timeline(activities, {})
    logger.info(
        f"Timeline: {len(timeline.events)} events, {len(timeline.phases)} phases, {len(timeline.errors)} errors"
    )
    title = json_path.stem
    report = render_transcript_report(title, timeline, metadata)
    output = json_path.with_suffix(".md")
    output.write_text(report, encoding="utf-8")
    logger.info(f"Transcript report written to {output}")
    return output


@app.command()
def analyse(
    path: Path = typer.Argument(..., help="Path to a bot export folder (or parent folder with --all)"),
    all_folders: bool = typer.Option(False, "--all", "-a", help="Process all subfolders containing bot exports"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Custom output path for the report"),
) -> None:
    """Analyse Copilot Studio bot exports and generate Markdown reports."""
    path = path.resolve()

    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        raise typer.Exit(1)

    if all_folders:
        # Process all subfolders
        folders = sorted([d for d in path.iterdir() if d.is_dir() and (d / "botContent.yml").exists()])
        if not folders:
            logger.error(f"No bot export folders found in {path}")
            raise typer.Exit(1)

        logger.info(f"Found {len(folders)} bot export folders")
        for folder in folders:
            try:
                _process_folder(folder)
            except Exception as e:
                logger.error(f"Failed to process {folder.name}: {e}")

        # Process Transcripts folder if present
        transcripts_dir = path / "Transcripts"
        if transcripts_dir.is_dir():
            transcript_files = sorted(transcripts_dir.glob("*.json"))
            if transcript_files:
                logger.info(f"Found {len(transcript_files)} transcript files")
                for tf in transcript_files:
                    try:
                        _process_transcript(tf)
                    except Exception as e:
                        logger.error(f"Failed to process transcript {tf.name}: {e}")

        logger.info("All done.")
    else:
        # Single folder
        if not path.is_dir():
            logger.error(f"Not a directory: {path}")
            raise typer.Exit(1)
        _process_folder(path, output)


if __name__ == "__main__":
    app()
