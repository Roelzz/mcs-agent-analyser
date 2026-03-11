# Agent Analyser — Improvement Clusters

Full audit and improvement plan across all areas: analysis depth, UX, architecture, CLI, new features, and testing.

---

## Cluster 1: Analysis Depth

**Goal:** Make reports actionable — surface problems the user would miss by reading raw config.

### 1.1 Quick Wins Section
- New renderer function `render_quick_wins(profile: BotProfile) -> str`
- Placed right after bot profile summary, before AI config
- Scans profile and flags:
  - Disabled topics (why are they still there?)
  - Topics with no trigger queries (unreachable unless called by another topic)
  - Topics with descriptions < 10 chars or matching display_name (poor documentation)
  - Missing system topics: OnError, OnUnknownIntent, OnEscalate
  - Unused global variables (declared but not referenced in any topic)
  - Knowledge sources not referenced by any topic's search actions
- Output: numbered list of findings with severity (warning/info)

### 1.2 Topic Graph Annotations
- Extend `render_topic_graph()` in renderer.py
- Compute graph properties from `topic_connections`:
  - **Orphaned topics**: no inbound edges (except system entry points)
  - **Circular dependencies**: detect cycles (A→B→C→A)
  - **Dead ends**: topics with no outbound edges and no end-conversation action
- Annotate Mermaid nodes with warning icons
- Add legend section below graph explaining annotations

### 1.3 Trigger Query Overlap Detection
- New function in parser.py: `detect_trigger_overlaps(components: list[ComponentSummary]) -> list[dict]`
- Compare trigger queries across topics using normalized lowercase matching
- Flag pairs with >50% token overlap
- Render as warning table in reports: "Topic A and Topic B both train on similar queries"

### 1.4 Orchestrator Health Checks
- New rules in solution_checker.py under "Orchestrator" category (ORCH001-ORCH005):
  - ORCH001: All child agents have connection references
  - ORCH002: Catch-all/fallback handler exists
  - ORCH003: No single agent handles >70% of routed topics
  - ORCH004: Agent descriptions are distinct (no copy-paste)
  - ORCH005: External agent count vs topic count ratio is reasonable
- Render in solution tools check tab

### 1.5 Connection Reference Validation
- New function in parser.py: `validate_connections(profile: BotProfile) -> list[dict]`
- Cross-reference component `connection_reference` against `connector_definitions`
- Flag: missing connectors, duplicate references, orphaned connectors
- Include in Quick Wins output

### 1.6 Knowledge Source Coverage Matrix
- New renderer function: `render_knowledge_coverage(profile: BotProfile) -> str`
- Build matrix: knowledge source × topics that reference it via search actions
- Flag sources with zero topic references
- Flag topics that use search but have no knowledge source configured
- Render as markdown table after knowledge inventory section

---

## Cluster 2: UX Polish

**Goal:** Reduce friction, improve feedback, prevent confusion.

### 2.1 Upload Progress Feedback
- Add progress state vars to State class: `upload_stage: str`
- Yield progress updates during `handle_upload()`:
  - "Detecting file format..."
  - "Parsing bot configuration..."
  - "Generating report..."
  - "Done"
- Show as inline status text or spinner in upload area

### 2.2 Empty State Onboarding
- First-time user sees guidance card on dashboard:
  - "Upload a .zip export from Copilot Studio"
  - "Or connect to Dataverse for live analysis"
  - Link to sample bot export for testing
- Only shown when no analyses have been performed

### 2.3 Solution Tools Error Handling
- Per-tab error state instead of scattered messages
- Failed tab shows error inline with "Retry" button
- Successful tabs don't flash/reload when sibling fails

### 2.4 Report State Preservation
- Cache last report in state so navigating away and back preserves it
- Lint results persist independently of report tab
- "Back to list" warns if unsaved work exists

### 2.5 Download Confirmation
- Toast notification after download: "Report saved as {filename}"
- Copy-to-clipboard button as alternative to file download

---

## Cluster 3: Architecture / Code Quality

**Goal:** Reduce complexity, fix security issue, improve maintainability.

### 3.1 Security Fix: Safe ZIP Extraction
- Replace `zf.extractall(extract_dir)` in web/state.py with `safe_extractall()` from renamer.py
- Extract `safe_extractall` to a shared utils module

### 3.2 Split Oversized Files
- `web/components.py` (1,826 lines) → split into `components/upload.py`, `components/report.py`, `components/solution_tools.py`, `components/common.py`
- `renderer.py` (1,730 lines) → split into `renderer/bot.py`, `renderer/timeline.py`, `renderer/credits.py`, `renderer/graphs.py`
- `web/state.py` (1,438 lines) → extract into Reflex substates: `AuthState`, `UploadState`, `DataverseState`, `SolutionToolsState`
- `solution_checker.py` (1,096 lines) → extract rules into `checker_rules/` with registry pattern

### 3.3 Break Up Long Functions
- `parser.py::_parse_bot_dict()` (309 lines) → split into `_extract_config()`, `_parse_components()`, `_extract_gpt_info()`, `_build_connections()`, `_enrich_components()`
- `timeline.py::build_timeline()` (400+ lines) → split into phase-specific builders

### 3.4 Extract Shared Utils
- YAML sanitization → `utils.py::sanitize_yaml()`
- JSON parsing with fallback → `utils.py::safe_json_load()`
- Compiled regex patterns → `utils.py::PATTERNS`

### 3.5 State Class Decomposition
- Split God Object `State` into Reflex substates with clear boundaries
- Each substate owns its own vars and handlers
- Communication via events, not shared mutable state

---

## Cluster 4: CLI Feature Parity

**Goal:** Enable automation and CI/CD integration.

### 4.1 Lint Command
- `uv run python main.py lint <path> --api-key <key>`
- Reuses existing `linter.py` logic
- Outputs lint results to stdout or file

### 4.2 Solution Tools Commands
- `uv run python main.py check <solution.zip>`
- `uv run python main.py validate <solution.zip>`
- `uv run python main.py deps <solution.zip>`
- `uv run python main.py rename <solution.zip> --new-name <name>`

### 4.3 Dataverse Support
- `uv run python main.py analyze --dataverse-url <url> --bot-id <guid>`
- Device code auth flow in terminal
- Outputs same markdown report as web UI

### 4.4 Output Format Options
- `--format markdown` (default)
- `--format json` — exports BotProfile + analysis results as JSON
- `--format html` — wraps markdown in simple HTML with Mermaid rendering

---

## Cluster 5: New Features

**Goal:** High-value capabilities that differentiate the tool.

### 5.1 Bot Comparison / Diff
- Upload two bot exports → side-by-side diff report
- Compare: topic count, component changes, instruction drift, new/removed connections
- Render as markdown diff with additions/removals highlighted

### 5.2 Batch Transcript Analytics
- Aggregate insights across multiple conversations:
  - Average response time, success rate, top failure modes
  - Most/least used topics, escalation rate
  - Time-series trends (if timestamps available)
- Dashboard view in web UI

### 5.3 Instruction Versioning
- Store instruction snapshots per analysis
- Diff consecutive versions to detect drift
- Alert if instructions changed significantly between runs

### 5.4 Custom Rule Engine
- YAML-based rule definitions users can upload
- Format: `rule_id`, `severity`, `condition` (Python expression), `message`
- Loaded at startup, applied alongside built-in rules
- Enables enterprise-specific checks without code changes

---

## Cluster 6: Test Coverage

**Goal:** Safety net for refactoring and new features.

### 6.1 Renderer Output Validation
- Test Mermaid diagram syntax is valid (parse to AST or regex validation)
- Test markdown table column counts match headers
- Test rendering with large component counts (500+)

### 6.2 CLI Integration Tests
- Test `--all` flag with mixed valid/invalid folders
- Test transcript processing pipeline
- Test custom output paths

### 6.3 Parser Edge Cases
- Malformed YAML (missing required fields)
- Circular topic connections
- Components with 1000+ trigger queries
- Empty/null fields that should have defaults

### 6.4 Web Flow E2E Tests
- Upload → Parse → Render → Download pipeline
- Dataverse connection flow (mock auth)
- Solution tools multi-tab workflow

### 6.5 Validator/Checker Output Format
- Ensure result dicts have required keys: `rule_id`, `severity`, `detail`
- Test all severity levels produce valid output

---

## Priority Order

| Order | Cluster | Rationale |
|-------|---------|-----------|
| 1 | Analysis Depth | Core user value — makes the tool actually useful |
| 2 | Architecture | Foundation for everything else + security fix |
| 3 | UX Polish | Better experience for existing features |
| 4 | Test Coverage | Safety net before adding more features |
| 5 | CLI Parity | Enables automation use cases |
| 6 | New Features | Big bets once foundation is solid |
