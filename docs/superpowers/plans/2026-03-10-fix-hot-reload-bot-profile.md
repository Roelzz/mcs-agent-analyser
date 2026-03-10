# Fix Hot-Reload Destroying bot_profile_json

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `data/` file writes from triggering Reflex hot-reload, which causes `_clear_bot_profile()` to fire and wipe the bot profile between analyse-bot and analyse-transcript.

**Architecture:** Reflex's dev-mode file watcher (uvicorn) watches all top-level directories including `data/`. When `_increment_counter()` writes `stats.json`, it triggers a hot-reload → frontend recompile → client reconnect → state reset → `_clear_bot_profile()`. The fix: tell Reflex to exclude `data/` from its watcher via `REFLEX_HOT_RELOAD_EXCLUDE_PATHS`.

**Tech Stack:** Reflex, Python, environment variables

---

## Root Cause (from diagnostic logs)

```
18:54:38 _save_bot_profile: wrote 12687 bytes → file exists=True
18:54:38 _increment_counter → writes stats.json → triggers uvicorn file watcher
18:54:49 Compiling: 28/28 (hot-reload)
18:54:57 _clear_bot_profile: removing ..., existed=True  ← KILLS THE FILE
18:55:05 dv_analyse_transcript: in-memory len=0, file exists=False
```

The `_clear_bot_profile` call sites (lines 311, 423, 523, 1008) are all intentional — the bug is that hot-reload causes an unintended state reset that triggers one of them.

---

### Task 1: Exclude `data/` from Reflex hot-reload

**Files:**
- Modify: `.env` (add env var)
- Modify: `.env.example` (add env var)

- [ ] **Step 1: Add `REFLEX_HOT_RELOAD_EXCLUDE_PATHS` to `.env.example`**

After the existing `BACKEND_PORT` line, add:

```
# Exclude data dir from hot-reload watcher (prevents bot_profile wipe)
REFLEX_HOT_RELOAD_EXCLUDE_PATHS=data
```

- [ ] **Step 2: Add the same to `.env`**

Same line:
```
REFLEX_HOT_RELOAD_EXCLUDE_PATHS=data
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "fix: exclude data/ from Reflex hot-reload watcher"
```

Note: `.env` is gitignored, only `.env.example` gets committed.

---

### Task 2: Remove diagnostic logging

**Files:**
- Modify: `web/state.py`

The diagnostic logging served its purpose. Remove it to keep logs clean.

- [ ] **Step 1: Remove diagnostic log from `_save_bot_profile()`**

Remove the `logger.info("_save_bot_profile: wrote {} bytes...")` line added after `tmp.replace(_BOT_PROFILE_FILE)`.

- [ ] **Step 2: Remove diagnostic logs from `_load_bot_profile()`**

Revert to original: return `_BOT_PROFILE_FILE.read_text()` directly (remove the `text` variable and both logger lines). Restore the fallback `return ""` without the `logger.warning("_load_bot_profile: file not found...")` line.

- [ ] **Step 3: Remove diagnostic log from `_clear_bot_profile()`**

Remove the `logger.info("_clear_bot_profile: removing...")` line.

- [ ] **Step 4: Remove diagnostic log from `dv_analyse_bot()`**

Remove the `logger.info("dv_analyse_bot: post-save check...")` line.

- [ ] **Step 5: Remove diagnostic logs from `dv_analyse_transcript()` and `dv_fetch_and_analyse_by_id()`**

Remove both `logger.info("dv_analyse_transcript: in-memory...")` and `logger.info("dv_fetch_and_analyse_by_id: in-memory...")` lines.

- [ ] **Step 6: Lint check**

Run: `uv run ruff check web/state.py`
Expected: All checks passed!

- [ ] **Step 7: Commit**

```bash
git add web/state.py
git commit -m "chore: remove bot_profile diagnostic logging"
```

---

### Task 3: End-to-end verification

- [ ] **Step 1: Restart Reflex**

```bash
uv run reflex run
```

Verify in terminal: no hot-reload triggers when navigating the app normally.

- [ ] **Step 2: Test the full flow**

1. Connect to Dataverse (device code auth)
2. Enter bot ID → click Analyse Bot
3. Confirm: report shows bot profile with components
4. Check terminal: `_save_bot_profile` logged, NO "Compiling" messages after
5. Click a transcript from the list
6. Confirm: report includes bot profile data (not transcript-only)
7. Check terminal: `bot_profile_json present: True`

- [ ] **Step 3: Verify stats still persist**

1. Note the cat counter value
2. Stop and restart Reflex
3. Confirm counter value survived restart (stats.json still works, just doesn't trigger reload)
