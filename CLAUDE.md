# Synthhive

Multi-tenant Twitch bot platform built with Django + TwitchIO 3.x.

## Architecture

Two Docker containers share the same codebase and PostgreSQL database:

- **server** — Daphne ASGI app serving Django admin, API, and OAuth setup pages on port 7177.
- **bot** — Runs `manage.py runbot`, which starts one `BotClient` (TwitchIO) per active bot record. Each bot gets its own AiohttpAdapter port (base 4343, incrementing).

```
┌─────────────────────────────────────────────┐
│  docker-compose                             │
│                                             │
│  server (Daphne :7177)   bot (runbot)       │
│    ├─ Django Admin         ├─ BotClient ×N  │
│    ├─ Ninja API            │   ├─ Router    │
│    └─ OAuth setup          │   ├─ Skills    │
│                            │   └─ EventSub  │
│                                             │
│  db (Postgres :5432)     redis (:6379)      │
└─────────────────────────────────────────────┘
```

## Data Model

- **Bot** — A Twitch bot identity (e.g., Elsydeon, WorldFriendshipBot). Holds encrypted OAuth tokens.
- **Channel** — A channel where a bot is active. FK to Bot. Also stores the channel owner's OAuth tokens for moderation.
- **Command** — A chat command (e.g., `!lurk`) defined per channel. The `type` field determines how the response is chosen (text, lottery, random_list, counter). The `config` JSONField stores type-specific settings. Response text supports variables. `created_by` tracks who created it (Twitch username from `!addcom`, or channel owner name from imports). `cooldown_seconds` (global) and `user_cooldown_seconds` (per-user) control cooldown timing; `config["cooldown_response"]` is the template shown when on cooldown.
- **Skill** — A Python-coded command toggled per channel. Used for complex built-in behaviors that need real Python logic (future: quotes, followage, API integrations). Logic lives in `bot/skills/` as handler classes, the model controls enable/disable and stores JSON config.
- **Counter** — A named counter per channel (e.g., death count, scare count). Dedicated model with `IntegerField` for atomic `F()` updates. Readable in command responses via `$(count.get name)`.
- **SkillStat** — Per-user stats for a skill in a channel. Stores arbitrary stats as JSON (e.g., `{"deaths": 14, "survivals": 22}`). Keyed by `(channel, skill_name, twitch_id)`. Used by lizardroulette for death tracking. Reusable for any skill needing per-user data.
- **Alias** — A type-agnostic command alias per channel. Resolved early in the message pipeline to rewrite triggers before routing (e.g., `!ct` → `!count death`). Works for all command types and skills.

## Command Types

Commands use a two-tier architecture: **command types** for config-driven behaviors, and **skill handlers** for complex Python-coded behaviors.

### Type-Based Commands

The `type` field on the Command model determines how the response is chosen and what side effects happen. All types share the same response processing pipeline (variables, `/me` handling, use_count).

| Type | Example | Response Source | Side Effect |
|---|---|---|---|
| `text` | `!lurk` | `command.response` template | None |
| `lottery` | `!getyeflask` | Roll `config["odds"]` → pick `config["success"]` or `config["failure"]` | None |
| `random_list` | `!conch` | Random pick from `config["responses"]`, optional `config["prefix"]` | None |
| `counter` | `!deaths` | `command.response` template (uses `$(count.get name)`) | Auto-increment named counter |

### Config Schemas

**lottery:**
```json
{"odds": 2, "success": "$(user) wins!", "failure": "Better luck next time!", "cooldown_response": "$(user), you have $(remaining) seconds left."}
```
`odds` is a percentage (1-100). Success/failure templates support variables.

**random_list:**
```json
{"prefix": "🐚 ", "responses": ["Yes.", "No.", "Maybe."]}
```
`prefix` is optional, prepended to the chosen response. Responses support variables.

**counter:**
```json
{"counter_name": "death"}
```
`counter_name` defaults to the command name if omitted. The counter is auto-incremented before variable processing so `$(count.get name)` returns the updated value.

### Cooldowns

Cooldowns are model fields on Command, applied in the common pipeline before type-specific dispatch. Both types can be set on the same command.

| Field | Scope | Description |
|---|---|---|
| `cooldown_seconds` | Global | Shared timer — once anyone triggers the command, nobody can use it for N seconds |
| `user_cooldown_seconds` | Per-user | Each chatter has their own timer |

`config["cooldown_response"]` is the template shown when on cooldown. Supports `$(remaining)` for remaining seconds as a raw number, plus all standard variables like `$(user)`. Omit `cooldown_response` to silently ignore attempts during cooldown. Cooldowns are in-memory and reset on bot restart.

### Skill Handlers

Skills are Python handler classes in `bot/skills/` for complex built-in behaviors that need real Python logic. Each skill is a `SkillHandler` subclass registered in `SKILL_REGISTRY`. The router checks commands first, then falls back to skill handlers.

Handler signature: `handle(self, payload, args, skill, bot)` — the `bot` parameter gives handlers access to the TwitchIO client for API calls (e.g., `bot.fetch_users()`).

| Skill | Handler | Description |
|---|---|---|
| `followage` | `FollowCheckHandler` | Checks if the chatter follows the channel and shows how long they've been following. Uses `twitch_request()` to call Twitch Helix API (`/channels/followers`) with automatic token refresh on 401. Requires `moderator:read:followers` scope on the channel owner token. |
| `lizardroulette` | `LizardRouletteHandler` | Roll odds — lose and get timed out via Twitch Helix `POST /moderation/bans`. Tracks per-user death count via `SkillStat` model; `$(deaths)` in failure message becomes ordinal (1st, 2nd, 14th). **Bullet mechanic**: `LizardBullets` component silently rolls 1/651 every 30s per channel to load a 6-chamber gun — when loaded, next 6 uses are guaranteed losses. Config: `odds` (1-100), `success`/`failure`/`failure_first`/`timeout_failed` messages, `timeout_duration`, `timeout_delay` (default 5s), `cooldown`. Per-user cooldown scoped per-channel. |
| `quote` | `QuoteHandler` | Quote CRUD via Synthfunc API. Subcommands: `!quote`, `!quote 42`, `!quote search <text>`, `!quote user <name>`, `!quote add "text" ~ @user`, `!quote latest`, `!quote stats <name>`. `!quote add` auto-records the current game from Twitch Helix. |
| `wallet` | `WalletHandler` | Check currency balance via Synthfunc wallets. `!wallet` for self, `!wallet @name` for others. Resolves target via `bot.fetch_users()`. |
| `dungeon` | `DungeonHandler` | Multiplayer dungeon minigame with currency wagering via Synthfunc `POST /transact`. Entry phase (120s default) → level selection by player count → survival rolls → payout to winners. In-memory game state (`_games` dict keyed by broadcaster_id). Global cooldown between runs. Spoonee-only (aliased as `!heist`). |
| `cute` | `CuteHandler` | Compliment someone. If target matches `config["bot_name"]` (default "elsydeon"), responds with `config["bot_response"]`. Otherwise uses `config["response"]` template with `$(target)` replacement. Avalonstar-only (Elsydeon channel). |
| `punt` | `PuntHandler` | 1-second self-timeout for disrespecting lalafells. Issues `POST /moderation/bans` with `duration: 1` via `twitch_request()`. Mods and broadcasters are immune (get a "too kawaii" message). Config: `immune`, `success`, `failure` message templates. Avalonstar-only. |
| `markov` | `MarkovHandler` | Generate fake chat messages from a 2nd-order Markov chain built from Synthfunc chat history. `!markov` generates a sentence (builds chain on cache miss), `!markov rebuild` (mod/broadcaster only) forces a rebuild. Chain cached in Redis (`markov:{slug}`, 6h TTL). |
| `ads` | `AdsHandler` | Ad rotation control. `!ads` shows status, `!ads on`/`off` enables/disables (mod/broadcaster only). Calls Synthfunc REST API. Success messages come from `AdAnnounce` component via Redis events. |
| `campaign` | `CampaignHandler` | Show active campaign info (subs, resubs, milestones unlocked). Avalonstar-only. |
| `timer` | `TimerHandler` | Show subathon timer status (remaining time, running/paused). Avalonstar-only. |
| `milestones` | `MilestonesHandler` | Show milestone progress with `[+]`/`[-]` icons. Avalonstar-only. |
| `gifts` | `GiftsHandler` | Show top 5 gift sub contributors from Synthfunc leaderboard. Avalonstar-only. |
| `nextgoal` | `NextGoalHandler` | Show the next milestone to unlock. Avalonstar-only. |
| `progress` | `ProgressHandler` | Show overall campaign progress percentage, subs, resubs, bits. Avalonstar-only. |
| `starttimer` | `StartTimerHandler` | Start the subathon timer (mod/broadcaster only). Calls Synthfunc `POST /campaigns/timer/start`. Avalonstar-only. |
| `pausetimer` | `PauseTimerHandler` | Pause the subathon timer (mod/broadcaster only). Calls Synthfunc `POST /campaigns/timer/pause`. Avalonstar-only. |

#### Dungeon Config Schema

```json
{
    "entry_duration": 120,
    "cooldown": 900,
    "min_wager": 10,
    "max_wager": 10000,
    "currency_name": "spoons",
    "levels": [
        {"name": "Cactuar Village", "min_players": 1, "survival_chance": 70, "multiplier": 1.5},
        {"name": "Tonberry Cove", "min_players": 3, "survival_chance": 60, "multiplier": 1.75},
        {"name": "Ultros", "min_players": 6, "survival_chance": 50, "multiplier": 2.0},
        {"name": "Tiamat", "min_players": 12, "survival_chance": 40, "multiplier": 2.25},
        {"name": "Bahamut", "min_players": 18, "survival_chance": 30, "multiplier": 2.5}
    ],
    "messages": { "entry_started": "...", "entry_joined": "...", "..." : "..." }
}
```

Game flow: `!dungeon 500` deducts wager → entry phase opens → others join → entry closes → level determined by player count → each player rolls survival chance → winners get `wager × multiplier` credited back, losers forfeit. Solo games have dedicated win/loss messages. Broadcast messages (entry closed, outcomes) use `broadcaster.send_message()` directly; player-specific messages (joined, insufficient funds) use `send_reply()`.

## Message Processing Pipeline

The `CommandRouter` (`bot/router.py`) is a TwitchIO Component with a single `event_message` listener. Processing order:

1. **Self-message guard** — Skip if chatter is the bot itself
2. **Prefix check** — Skip if message doesn't start with `!`
3. **Skip built-in commands** — Management commands handled by `ManagementCommands` (`addcom`, `editcom`, `delcom`, `commands`, `id`, `alias`, `unalias`, `aliases`, `count`, `counters`)
4. **Alias resolution** — Rewrite trigger via `Alias` model (e.g., `!ct` → `!count death`)
5. **Command lookup** — Query `Command` table by channel + name. If found and enabled, dispatch by type:
   - `text`: use `command.response`
   - `lottery`: roll odds → pick success or failure from config
   - `random_list`: random pick from `config["responses"]`, prepend prefix
   - `counter`: auto-increment named counter, use `command.response`
   - Common pipeline: increment use_count → build VariableContext → process variables → handle `/me` → respond
6. **Skill handler fallback** — Look up handler in `SKILL_REGISTRY`, query `Skill` model, call `handler.handle()`

## Background Components

TwitchIO Components that run background tasks alongside the message pipeline.

| Component | File | Description |
|---|---|---|
| `CurrencyAccrual` | `bot/components/accrual.py` | Ticks every 5 min while stream is live. Posts to Synthfunc `POST /wallets/accrue`. |
| `AdAnnounce` | `bot/components/ads.py` | Subscribes to Synthfunc Redis pub/sub (`events:{slug}:ads`). Announces ad warnings, running, ended, enabled, disabled events in chat. Warning intervals configurable per-channel via skill config (`warning_intervals`, default `[60, 5]`). Messages customizable via `config["messages"]`. Uses `create_partialuser()` to send messages without a chat payload. |
| `LizardBullets` | `bot/components/lizardbullets.py` | Ticks every 30s. Rolls 1/651 per channel per tick to silently load a 6-chamber gun. When loaded, next 6 `!lizardroulette` uses are guaranteed losses. Writes to `LizardRouletteHandler._bullets` dict (in-memory, resets on restart). |

## Variable System

Variables use `$(namespace.property args)` syntax in command responses. Defined in `bot/variables.py` as a registry of handler classes. Each handler owns a namespace and has `resolve()` and `describe()` methods.

| Variable | Description |
|---|---|
| `$(user)` | Display name of the chatter who triggered the command |
| `$(target)` | First argument after the command (with `@` stripped). Falls back to `$(user)` if no argument given |
| `$(channel)` | Current channel name |
| `$(uses)` | How many times this text command has been used |
| `$(count.get <name>)` | Current value of a named counter |
| `$(count.label <name>)` | Display label of a named counter |
| `$(random.range N-M)` | Random integer between N and M |
| `$(random.pick a,b,c)` | Random choice from a comma-separated list |
| `$(uptime)` | Stream uptime (e.g., `3h 42m`), or `offline` if not live. Uses `GET /helix/streams` |
| `$(game)` | Current or last game/category for the channel. Uses `GET /helix/channels` |
| `$(query)` | Full argument string after the command name |
| `$(1)`, `$(2)`, ... | Positional arguments (1-based) |

### /me Action Messages

If a command's response starts with `/me `, the bot sends it as a Twitch action message (italicized). The optional `- ` separator after `/me` is also stripped (convention from Spoonee's commands).

### Security

- The bot ignores its own messages to prevent command chaining.
- `$(target)` strips leading `@` only. The self-message guard prevents injection of `!commands` or `/me` via target arguments.

### Twitch API Client (`core/twitch.py`)

Shared utility for making authenticated Twitch Helix API calls. Used by skill handlers (e.g., `FollowCheckHandler`) and variable handlers (`UptimeHandler`, `GameHandler`) that need channel owner tokens.

- `twitch_request(channel, method, url, **kwargs)` — Makes an authenticated request using the channel owner's token fetched from Synthfunc (source of truth), falling back to the locally cached token if Synthfunc is unreachable. On 401, re-fetches from Synthfunc in case the token was refreshed by Synthfunc's TwitchIO service, and retries once. Returns an `httpx.Response` on success, or `None` if both attempts fail.

Token refresh is managed by Synthfunc's TwitchIO service via `event_token_refreshed`. Synthhive does not refresh tokens directly.

## Alias System

Aliases are type-agnostic command rewrites. When someone types `!ct`, the router looks up the Alias table and rewrites it to `!count death` before routing. This works for both text commands and skills.

| Command | Permission | Description |
|---|---|---|
| `!alias <name> <target>` | Mod/Broadcaster | Create an alias (e.g., `!alias ct count death`) |
| `!unalias <name>` | Mod/Broadcaster | Remove an alias |
| `!aliases` | Everyone | List all aliases for the channel |

## Counter System

Counters are named per-channel values stored in the `Counter` model. They use Django `F()` expressions for atomic increments.

| Command | Permission | Description |
|---|---|---|
| `!count <name>` | Everyone | Show a counter's value |
| `!count <name> +` | Mod/Broadcaster | Increment a counter |
| `!count <name> -` | Mod/Broadcaster | Decrement a counter |
| `!count <name> set <N>` | Mod/Broadcaster | Set a counter to a specific value |
| `!counters` | Everyone | List all counters and their values |

Counters are also accessible in command responses via `$(count.get <name>)` and `$(count.label <name>)`. Counter values can be edited directly in Django admin.

## DeepBot Variable Mapping

For importing commands from DeepBot, these map to our system:

| DeepBot | Synthhive | Status |
|---|---|---|
| `@user@` | `$(user)` | Supported |
| `@target@` | `$(target)` | Supported |
| `@uptime@` | `$(uptime)` | ✅ Supported |
| `@game@` | `$(game)` | ✅ Supported |
| `@counter@`, `@getcounter@` | `$(count.get <name>)` | Supported (via Counter model) |
| `@customapi@` | — | Skill (not yet implemented) |
| `@readfile@` | — | Skill (not yet implemented) |
| `@if@` | — | Skill (not yet implemented) |
| `@followdate@`, `@hours@`, `@points@` | — | Skill (needs Twitch API) |

## Spoonee Import — Remaining Skipped Commands

| Skipped Command | What It Is | Status |
|---|---|---|
| `conch` | Magic Conch Shell | ✅ random_list command |
| `getyeflask` | Random chance game | ✅ lottery command |
| `parrotfact` | Parrot facts | ✅ random_list command |
| `count` | Counter management | ✅ builtin management command |
| `ct` | Counter alias → `count death` | ✅ Seeded as alias |
| `countadd` | Counter alias → `count death +` | ✅ Seeded as alias |
| `addscare` | Counter alias → `count scare +` | ✅ Seeded as alias |
| `scare` | Counter alias → `count scare` | ✅ Seeded as alias |
| `checkme` | Follow check | ✅ Skill handler (`FollowCheckHandler`) |
| `followcheck` | Follow check | ✅ Seeded as alias → `checkme` |
| `forreal` | Unknown | Ask Spoonee |

## Management Commands

| Command | Description |
|---|---|
| `manage.py runbot` | Start all active bot instances |
| `manage.py seed` | Ensure infrastructure records exist (users, bots, channels only). Runs on every deploy. Does NOT touch commands, counters, aliases, or skills. |
| `manage.py importcommands <json> --channel <name>` | Bulk import commands from JSON. Use `--dry-run` to preview. Sets `created_by` to channel owner name |
| `manage.py importmoobot <json> --channel <name>` | Import commands from a Moobot export. Use `--dry-run` to preview. Converts variables, creates counters and aliases |

### Content Management

Commands, counters, aliases, and skills are managed directly in the database — either through Django admin or via `docker exec` on Saya. The seed command intentionally does not create or modify these records to avoid overwriting changes made in production.

### Import JSON Format

```json
{
  "commands": [
    {"name": "lurk", "response": "/me - $(user) settles in for a cozy lurk.", "mod_only": false}
  ],
  "metadata": {
    "skipped_skills": ["checkme"]
  }
}
```

### Moobot Import

The `importmoobot` command reads a Moobot export file (JSON with UTF-8 BOM) and converts commands to Synthhive format.

**Variable conversion:**

| Moobot | Synthhive | Notes |
|---|---|---|
| `<username>` | `$(user)` | |
| `<args>` | `$(target)` | |
| `<counter>` | `$(count.get <name>)` | Also creates a Counter model entry with the preserved Moobot value |
| `<twitch.game>` | `$(game)` | |
| `<twitch.uptime>` | `$(uptime)` | |
| `<twitch.followed>` | — | Creates an alias to `!checkme` instead |
| `<time>` | — | Skipped (unsupported) |

**Special handling:**
- Mod-editable commands (`mod_editable: true`) use `chat_text` as the response instead of `text`
- Counter commands create both a Command and a Counter model entry
- `use_count` is preserved from the Moobot `counter` field
- Disabled commands are imported with `enabled=False`
- Existing commands are skipped (not overwritten)

## Chat Commands

| Command | Permission | Description |
|---|---|---|
| `!addcom <name> <response>` | Mod/Broadcaster | Create a new text command |
| `!editcom <name> <response>` | Mod/Broadcaster | Edit an existing command's response |
| `!delcom <name>` | Mod/Broadcaster | Delete a command |
| `!commands` | Everyone | List all enabled commands |
| `!alias <name> <target>` | Mod/Broadcaster | Create a command alias |
| `!unalias <name>` | Mod/Broadcaster | Remove a command alias |
| `!aliases` | Everyone | List all aliases |
| `!count <name> [+\|-\|set N]` | Mod/Broadcaster (mutations) | View or modify a counter |
| `!counters` | Everyone | List all counters |
| `!conch [question]` | Everyone | Magic Conch Shell (random_list command) |
| `!getyeflask` | Everyone | Random chance game (lottery command) |
| `!checkme` | Everyone | Check follow status and duration (skill) |
| `!ads` | Everyone | Show ad scheduler status (skill) |
| `!ads on` | Mod/Broadcaster | Enable ad rotation via Synthfunc |
| `!ads off` | Mod/Broadcaster | Disable ad rotation via Synthfunc |
| `!id` | Everyone | Show the bot's Twitch user ID |

## Deployment

Automated via GitHub Actions (`.github/workflows/deploy.yml`). Pushes to `main` trigger a deploy to the self-hosted runner on Saya.

- **Domain**: `bots.bardsaders.com` behind Cloudflare Zero Trust.
- **Server access**: `ssh saya`. Use `docker exec` for container interaction, not `docker compose`.
- **Startup sequence**: migrate → seed → collectstatic → Daphne.

### Static Files

WhiteNoise does not work under ASGI/Daphne (sync-only middleware). Static files are served via Django's `django.views.static.serve` through a URL route in `synthhive/urls.py`.

## Twitch IDs

| Name | Twitch User ID | Role |
|---|---|---|
| Avalonstar | 38981465 | Channel owner |
| Spoonee | 78238052 | Channel owner |
| Elsydeon | 66977097 | Bot |
| WorldFriendshipBot | 149214941 | Bot |

## Development

- **Python 3.13**, managed by `uv`.
- **Linting**: Ruff (config in `pyproject.toml`). Single-line imports, `from __future__ import annotations` required.
- **Database**: PostgreSQL 16. All models use UUID primary keys.
- **Encryption**: django-fernet-encrypted-fields for OAuth tokens.
