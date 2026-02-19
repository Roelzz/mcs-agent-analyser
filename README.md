# Agent Analyser

Parses Microsoft Copilot Studio bot exports (`botContent.yml` + `dialog.json`) and conversation transcripts, generating Markdown reports with Mermaid diagrams. Includes a web UI for upload-and-analyse workflows.

## Quick Start

### Web UI

```bash
cp .env.example .env    # edit credentials
uv sync
uv run reflex run
```

Open http://localhost:2009, sign in, upload a `.zip` bot export or individual files.

### CLI

```bash
uv sync
uv run python main.py path/to/botContent --all
```

Scans all subfolders containing `botContent.yml` + `dialog.json` and writes a `report.md` into each. If a `Transcripts/` subfolder exists, every `.json` transcript gets a matching `.md` report.

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

Each generated report contains:

1. **AI Configuration** - GPT model, knowledge sources, web browsing, code interpreter, system instructions (collapsible)
2. **Bot Profile** - Schema name, bot ID, channels, recognizer, AI settings
3. **Components** - Summary counts (active/inactive by kind) + detail tables per kind
4. **Topic Connection Graph** - Mermaid flowchart of topic-to-topic calls with conditions
5. **Conversation Trace** - Sequence diagram, Gantt chart, phase breakdown, event log, errors

Transcript reports contain:

1. **Title** — derived from the JSON filename
2. **Session Summary** — start/end time, session type, outcome, turn count, implied success
3. **Conversation Trace** — sequence diagram, Gantt chart, phase breakdown, event log

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `USERS` | _(none)_ | Web UI credentials, comma-separated `user:pass` pairs |

## Development

```bash
uv sync
uv run pytest              # 77 tests
uv run ruff check .
uv run ruff format .
uv run reflex run          # dev server on :2009
```

## Project Structure

```
main.py            CLI entry point (Typer)
models.py          Pydantic models (BotProfile, ConversationTimeline, GptInfo, TopicConnection)
parser.py          YAML + JSON parsing, GPT extraction, topic connection extraction
renderer.py        Markdown + Mermaid rendering
timeline.py        Dialog activity → timeline event conversion
transcript.py      Transcript JSON parsing and normalization
rxconfig.py        Reflex app config
web/
  web.py           Page definitions and Reflex app setup
  state.py         Reflex state (auth, file upload, report generation)
  components.py    UI components (navbar, upload form, report viewer)
  mermaid.py       Mermaid diagram rendering (CDN loader, MutationObserver, segment splitter)
tests/
  test_main.py     Core module tests
  test_web.py      Web frontend tests (auth, mermaid splitting)
samples/
  report.md              Sample bot export report
  transcript_report.md   Sample transcript report
```
