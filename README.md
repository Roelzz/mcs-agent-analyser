# Agent Analyser

![Repo Views](https://komarev.com/ghpvc/?username=Roelzz&label=Repo%20Views&color=0e75b6&style=flat)

Parses Microsoft Copilot Studio bot exports and live Dataverse environments, generating Markdown reports with Mermaid diagrams. Includes a web UI for upload-and-analyse workflows.

## Why Agent Analyser

- **Full visibility into bot architecture** — see every topic, skill, entity, knowledge source, and how they connect, in one report
- **Catch misconfigurations before they hit production** — AI-powered instruction lint audits your bot's guardrails, topic structure, and component health
- **Your data stays yours** — runs locally or self-hosted in your own tenant. No data is sent externally (except to OpenAI if you opt into the Lint feature)
- **Works with exports and live Dataverse** — upload a `.zip` export, or connect directly to your environment and auto-analyse on login

## What You Can Do

| Feature | Description |
| --- | --- |
| **Upload bot export** | Drop a `.zip`, or `botContent.yml` + `dialog.json` — get a full architecture report |
| **Connect to Dataverse** | Device-code auth to your environment, auto-analyses your bot the moment you connect |
| **Conversation transcripts** | Upload or fetch transcripts from Dataverse — sequence diagrams, Gantt charts, event logs |
| **Instruction Lint** | AI audit of bot instructions, guardrails, and topic architecture (requires OpenAI API key) |
| **Single conversation lookup** | Fetch and analyse a specific conversation by ID directly from Dataverse |
| **Analysis counter** | Tracks how many analyses you've run, with cat-themed gamification milestones |
| **Dark / Light mode** | Respects your OS preference, green accent theme throughout |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager

### macOS / Linux (Terminal)

```bash
git clone https://github.com/Roelzz/Agent_analyser.git
cd Agent_analyser
cp .env.example .env       # edit credentials in .env
uv sync
uv run reflex run
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Roelzz/Agent_analyser.git
cd Agent_analyser
Copy-Item .env.example .env   # edit credentials in .env
uv sync
uv run reflex run
```

### Windows (CMD)

```cmd
git clone https://github.com/Roelzz/Agent_analyser.git
cd Agent_analyser
copy .env.example .env        REM edit credentials in .env
uv sync
uv run reflex run
```

Open http://localhost:3000, sign in, upload a `.zip` bot export or connect to Dataverse.

> **Privacy note:** Deploy this locally or self-host in your own Azure tenant. Bot exports and Dataverse data never leave your machine. The only external call is to OpenAI if you use the Instruction Lint feature.

### CLI

```bash
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

**From Dataverse (live connection):**
- Bot config and all components fetched via Web API
- Auto-triggers full bot analysis after device-code authentication
- Conversation transcripts with browse, search, and single-ID lookup
- Schema lookup preserved across transcript analyses for accurate topic resolution

**From transcript `.json` files:**
- Session metadata (outcome, outcome reason, turn count, implied success, duration)
- Variable assignments and dialog redirects
- Same conversation timeline rendering (sequence diagram, Gantt chart, event log)

**Instruction Lint (AI-powered):**
- Audit of bot instructions, guardrails, topic architecture, and component health
- Requires an OpenAI API key — set `OPENAI_API_KEY` in `.env`

## Report Structure

Each generated report contains:

1. **AI Configuration** - GPT model, knowledge sources, web browsing, code interpreter, system instructions (collapsible)
2. **Bot Profile** - Schema name, bot ID, channels, recognizer, AI settings
3. **Components** - Smart categorization (User/Orchestrator/System/Automation Topics, Knowledge, Skills, Entities, Variables, Settings) with tailored columns per category
4. **Topic Connection Graph** - Mermaid flowchart of topic-to-topic calls with conditions
5. **Conversation Trace** - Sequence diagram, Gantt chart, phase breakdown, event log, errors

Transcript reports contain:

1. **Title** — derived from the JSON filename
2. **Session Summary** — start/end time, session type, outcome, turn count, implied success
3. **Conversation Trace** — sequence diagram, Gantt chart, phase breakdown, event log

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `REFLEX_ENV` | `dev` | `dev` = separate ports, `prod` = single-port mode |
| `FRONTEND_PORT` | `3000` | Frontend port (dev mode only) |
| `BACKEND_PORT` | `8000` | Backend port (dev mode only) |
| `PORT` | `2009` | Single port for prod mode (`--single-port`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `USERS` | _(none)_ | Web UI credentials, comma-separated `user:pass` pairs |
| `OPENAI_API_KEY` | _(none)_ | OpenAI API key for Instruction Lint feature (optional) |

## Deployment

> **Recommendation:** Self-host this in your own tenant or run it locally. Bot configuration data and conversation transcripts are sensitive — keep them under your control.

Single-port mode — one exposed port serves everything.

### Nixpacks (Coolify / Railway)

Configure these env vars in your platform:

```bash
REFLEX_ENV=prod
PORT=2009
USERS=admin:secret
OPENAI_API_KEY=sk-...        # optional, enables Instruction Lint
```

The `Procfile` runs `reflex run --env prod --single-port`. Set `REFLEX_ENV=prod` so `rxconfig.py` uses the single `PORT` for both frontend and backend.

### Docker

```bash
docker build -t agent-analyser .
docker run -p 2009:2009 --env-file .env agent-analyser
```

Make sure `.env` contains at least `REFLEX_ENV=prod` and `PORT=2009`.

## Development

```bash
cp .env.example .env          # edit credentials
uv sync
uv run pytest              # 83 tests
uv run ruff check .
uv run ruff format .
uv run reflex run          # dev server — frontend :3000, backend :8000
```

## Project Structure

```
main.py              CLI entry point (Typer)
models.py            Pydantic models (BotProfile, ConversationTimeline, GptInfo, TopicConnection)
parser.py            YAML + JSON parsing, GPT extraction, topic connection extraction
renderer.py          Markdown + Mermaid rendering
timeline.py          Dialog activity → timeline event conversion
transcript.py        Transcript JSON parsing and normalization
dataverse_client.py  Dataverse Web API client (bot config, components, transcripts)
rxconfig.py          Reflex app config
linter.py            Instruction lint logic (OpenAI API, model resolution, audit prompt)
web/
  web.py             Page definitions and Reflex app setup
  state.py           Reflex state (auth, file upload, Dataverse connection, report generation)
  components.py      UI components (navbar, upload form, report viewer, import form)
  mermaid.py         Mermaid diagram rendering (CDN loader, MutationObserver, segment splitter)
tests/
  test_main.py       Core module tests
  test_web.py        Web frontend tests (auth, mermaid splitting)
  test_linter.py     Instruction linter tests
samples/
  report.md                Sample bot export report
  transcript_report.md     Sample transcript report
docs/                      Additional documentation
```
