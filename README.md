# Copilot Studio Bot Analyser

Parses Microsoft Copilot Studio bot exports (`botContent.yml` + `dialog.json`) and conversation transcripts, generating Markdown reports with Mermaid diagrams.

## Quick Start

```bash
uv sync
uv run python main.py path/to/botContent --all
```

This scans all subfolders containing `botContent.yml` + `dialog.json` and writes a `report.md` into each. If a `Transcripts/` subfolder exists, every `.json` transcript in it gets a matching `.md` report automatically.

Single folder:

```bash
uv run python main.py path/to/botContent_folder
uv run python main.py path/to/botContent_folder -o custom_report.md
```

## What It Extracts

**From `botContent.yml`:**
- Bot metadata (name, ID, channels, recognizer, orchestrator detection)
- AI configuration (GPT component model, instructions, knowledge sources, capabilities)
- All components with kind, state, triggers, dialog types
- Topic connection graph (which topics call which via `BeginDialog`)

**From `dialog.json`:**
- Full conversation timeline (user messages, bot responses, plan steps, knowledge searches, errors)
- Execution phases with duration and status
- Mermaid sequence diagram of the conversation flow
- Mermaid Gantt chart of execution timing

**From transcript `.json` files:**
- Session metadata (outcome, outcome reason, turn count, implied success, duration)
- Variable assignments and dialog redirects
- Same conversation timeline rendering (sequence diagram, Gantt chart, event log)

## Report Structure

Each generated `report.md` contains:

1. **AI Configuration** - GPT model, knowledge sources, web browsing, code interpreter, system instructions (collapsible)
2. **Bot Profile** - Schema name, bot ID, channels, recognizer, AI settings
3. **Components** - Summary counts (active/inactive by kind) + detail tables per kind
4. **Topic Connection Graph** - Mermaid flowchart of topic-to-topic calls with conditions
5. **Conversation Trace** - Sequence diagram, Gantt chart, phase breakdown, event log, errors

Transcript reports contain:

1. **Title** — derived from the JSON filename
2. **Session Summary** — start/end time, session type, outcome, turn count, implied success
3. **Conversation Trace** — same sequence diagram, Gantt chart, phase breakdown, event log as bot reports

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Project Structure

```
main.py          CLI entry point (Typer)
models.py        Pydantic models (BotProfile, ConversationTimeline, GptInfo, TopicConnection)
parser.py        YAML + JSON parsing, GPT extraction, topic connection extraction
renderer.py      Markdown + Mermaid rendering
timeline.py      Dialog activity → timeline event conversion
transcript.py    Transcript JSON parsing and normalization
tests/
  test_main.py   50 tests covering all modules
samples/
  report.md              Sample bot export report
  transcript_report.md   Sample transcript report
```
