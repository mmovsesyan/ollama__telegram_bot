# Smart & Friendly Bot — Design Spec

**Date:** 2026-06-14  
**Project:** Ollama Telegram Bot  
**Topic:** Make the bot maximally smart and user-friendly  
**Approach:** LLM-based intent router with strict JSON validation + rule-based tool executors + contextual memory + proactive suggestions + AI weekly planning  

---

## 1. Goal and Scope

### 1.1 Goal
Make the bot understand free-form Russian messages, remember conversation context and user facts, and proactively suggest useful actions.

### 1.2 In Scope
- Smart routing of free-form text to the right tool (reminder, task, memory, note, search, weather, news, monitor, plan, chat).
- LLM returns a structured JSON decision; code validates and executes it.
- Contextual enrichment before each LLM call: user profile, dialogue summary, relevant memory/notes, current time.
- Compacted dialogue summary that preserves meaning.
- Proactive daily suggestions based on memory, habits, reminders, and tasks.
- AI weekly planning that generates a draft plan and creates reminders/tasks after user confirmation.
- Gradual refactoring of existing routers behind a common `BaseTool` interface.

### 1.3 Out of Scope for This Cycle
- Adding or changing Ollama models (use current `OLLAMA_MODEL`).
- Billing, payments, or multi-tenant tiers.
- Real-time webhooks beyond Telegram polling.
- Complex multi-agent orchestration.

---

## 2. High-Level Architecture

```
[Telegram Message]
        ↓
[Context Builder] — profile, summary, memory, notes, current time
        ↓
[LLM Intent Router] — JSON: intent, tool, args, confidence, clarification_needed, proactive_suggestion
        ↓
[Validator] — schema check, confidence threshold, allowed tool whitelist
        ↓
[Tool Executor] — BaseTool subclass runs business logic
        ↓
[Response Formatter] — friendly message + command_keyboard
        ↓
[User]
```

Proactive flow runs in parallel:

```
[Scheduler] → [Proactive Engine] → [LLM] → [suggestions queue] → [User with inline buttons] → [Tool Executor]
```

**Rule:** LLM decides *what* to do and extracts parameters; code performs all side effects (DB, API calls, scheduler).

---

## 3. Components

### 3.1 Context Builder

Builds a context payload for every LLM call.

| Field | Source |
|-------|--------|
| `user_profile` | `user_profiles` table: timezone, language, summary_style, last_proactive_check |
| `dialogue_summary` | `dialogue_summaries` table: compacted summary |
| `recent_messages` | SQLite session history (last 3 full exchanges) |
| `relevant_memory` | `memories` + `notes`, ranked by keyword/LLM relevance (top 5) |
| `active_state` | current FSM state, pending reminders, active monitors |
| `current_time` | ISO UTC timestamp |

#### Dialogue Summary Strategy
- Store a running summary in `dialogue_summaries`.
- After every exchange, regenerate by passing old summary + last 2 messages to LLM with a compacting prompt.
- Keep the summary under 500 characters.

### 3.2 LLM Intent Router

A single Ollama call per user message. System prompt includes the JSON schema and available tools.

#### Required JSON Output Schema

```json
{
  "intent": "create_reminder",
  "tool": "remind",
  "args": {
    "content": "позвонить брокеру",
    "trigger_at": "2026-06-15T07:30:00+00:00",
    "recurring": "weekday"
  },
  "confidence": 0.92,
  "clarification_needed": false,
  "clarification_question": null,
  "proactive_suggestion": null,
  "response_tone": "friendly"
}
```

#### Supported Intents
- `chat` — general AI conversation.
- `create_reminder` — schedule a reminder.
- `create_task` — schedule an AI-executed task.
- `add_memory` — save a fact/preference/note to memory.
- `add_note` — save a quick note.
- `search` — web search.
- `weather` — get weather.
- `news` — get news.
- `add_monitor` — add a site monitor.
- `generate_plan` — create a weekly plan.
- `clarify` — ask the user for missing details.
- `cancel` — cancel current FSM/action.
- `help` — show help.

### 3.3 Validator

- Validate JSON against the schema using `pydantic` or manual checks.
- Reject unknown `tool` or `intent` values.
- Enforce `confidence >= 0.7` for actions with side effects.
- Require `args` fields defined by the target tool.
- If validation fails, route to `clarify` or `chat` fallback.

### 3.4 Tool Executors

All tools implement a common interface:

```python
class BaseTool(ABC):
    name: str
    required_args: list[str]

    @abstractmethod
    async def execute(self, context: ToolContext) -> ToolResult: ...
```

Initial subclasses:
- `ChatTool` — fallback chat via existing `generate_chat_completion`.
- `RemindTool` — wraps `_process_remind` / `parse_reminder`.
- `TaskTool` — wraps `_process_task_from_text`.
- `MemoryTool` — auto-classify and save to memory.
- `NoteTool` — save a note.
- `SearchTool`, `WeatherTool`, `NewsTool` — wrappers over existing functions.
- `MonitorTool` — add a monitor.
- `PlanTool` — generate a weekly plan and create reminders/tasks.

Existing routers remain functional; new tools call their business logic, do not duplicate it.

### 3.5 Response Formatter

- Converts `ToolResult` into a friendly Telegram message.
- Uses emojis matching the tool type.
- Always restores `command_keyboard`.
- For `clarify`, sends an inline keyboard with suggested options.

### 3.6 Proactive Engine

Runs once a day via APScheduler.

1. Load users with `last_proactive_check` older than 24 hours.
2. For each user, gather profile, memory, notes, active reminders/tasks.
3. Ask LLM for 0–3 proactive suggestions in JSON format.
4. Store suggestions in `proactive_suggestions` with `status=pending` and `expires_at`.
5. Send each pending suggestion to the user with inline buttons: **Yes / No / Don't ask again**.
6. On **Yes**: execute the corresponding tool. On **No**: dismiss. On **Don't ask again**: mark type as dismissed.

### 3.7 AI Weekly Planning

1. User says something like «план на неделю» or accepts a proactive planning suggestion.
2. `PlanTool` gathers memory, tasks, recurring reminders, and user preferences.
3. LLM generates a draft plan text + structured items (reminders/tasks).
4. Bot shows the plan and asks for confirmation with inline buttons.
5. On confirmation, each item is passed to `RemindTool` or `TaskTool`.
6. The plan is saved in `plans` with `status=active`.

---

## 4. Data Model Changes

New tables created with `CREATE TABLE IF NOT EXISTS`:

### 4.1 `dialogue_summaries`
```sql
CREATE TABLE IF NOT EXISTS dialogue_summaries (
    user_id INTEGER PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
```

### 4.2 `proactive_suggestions`
```sql
CREATE TABLE IF NOT EXISTS proactive_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    suggestion_type TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

### 4.3 `user_profiles`
```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    language TEXT NOT NULL DEFAULT 'ru',
    summary_style TEXT NOT NULL DEFAULT 'short',
    last_proactive_check TEXT
);
```

### 4.4 `plans`
```sql
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_text TEXT NOT NULL,
    items TEXT NOT NULL,  -- JSON list
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
```

Existing tables (`reminders`, `monitors`, `memories`, `notes`) are unchanged.

---

## 5. Error Handling and Fallbacks

| Failure | Behavior |
|---------|----------|
| LLM timeout / Ollama error | Fall back to existing rule-based handlers and `parse_reminder`. |
| Invalid JSON from LLM | Retry once with stricter prompt; if still invalid, ask user to rephrase. |
| Low confidence (< 0.7) | Route to `clarify`; ask user to confirm intent. |
| Tool execution exception | Catch in `BaseTool`, log error, return friendly error message + `command_keyboard`. |
| Unknown tool / intent | Treat as `chat` fallback. |

---

## 6. Testing Strategy

### 6.1 Unit Tests
- `Validator` with valid/invalid JSON, low confidence, unknown tool.
- `ContextBuilder` summary and memory ranking.
- Each `BaseTool` subclass with mocked DB and LLM.

### 6.2 Intent Regression Suite
A file with 50–100 Russian phrases covering all tools. Run via `pytest` with mocked LLM.

Examples:
- «завтра в 9 позвонить брокеру» → `create_reminder`
- «каждое утро в 8 погода в москве» → `create_task`
- «запомни, я люблю краткие ответы» → `add_memory`
- «план на неделю» → `generate_plan`
- «отчёт за сегодня» → `chat` or `report`

### 6.3 Manual QA
- Free text maps to the right tool.
- FSM does not get stuck.
- `command_keyboard` is always restored.
- Proactive suggestions arrive and buttons work.
- Weekly plan creates reminders/tasks.

---

## 7. Iteration Plan

The work is split into four independent iterations. Each iteration is a releasable milestone.

### Iteration 1 — Smart Router + Validator
- `BaseTool`, `ToolContext`, `ToolResult`.
- `LLMIntentRouter` with JSON schema.
- `Validator`.
- `ChatTool`, `RemindTool`, `TaskTool`.
- Regression tests on 30 phrases.
- **Outcome:** free-form text creates reminders/tasks/chats reliably.

### Iteration 2 — Context + Memory + Summary
- `dialogue_summaries`, `user_profiles` tables.
- `ContextBuilder`.
- `MemoryTool`, `NoteTool`, `SearchTool`, `WeatherTool`, `NewsTool`.
- Dialogue summary compaction.
- **Outcome:** bot remembers context and uses memory/notes.

### Iteration 3 — Proactive Engine
- `proactive_suggestions` table.
- Daily proactive analysis job.
- Suggestion generation + inline buttons.
- **Outcome:** bot initiates useful actions on its own.

### Iteration 4 — AI Plan Generator + Full Tool Refactor
- `plans` table.
- `PlanTool` with draft → confirm → execute flow.
- Migrate remaining routers to `BaseTool` interface.
- **Outcome:** weekly AI plans and unified tool architecture.

---

## 8. Open Questions / Decisions

1. **Confidence threshold:** default 0.7; adjustable via env var `SMART_BOT_CONFIDENCE_THRESHOLD`.
2. **Summary regeneration:** after every exchange; if LLM fails, keep previous summary.
3. **Proactive time:** 09:00 user local time once `timezone` is implemented; until then, 09:00 UTC.
4. **LLM JSON mode:** rely on prompt engineering first; if Ollama supports structured output later, switch to native JSON mode.
