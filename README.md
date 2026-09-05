# Codex Reset Lark Notifier

Monitor Codex reset watch information and send update notifications to a Lark custom bot.

## Background

The original need is simple:

- Watch reset information from `codex-resets.com`.
- Avoid relying on Telegram as the daily notification surface.
- Send meaningful reset watch updates to a Lark group bot.

## Architecture decision record

### Decision 1: Poll the public source directly

Chosen design:

```text
codex-resets source
  -> scheduled poller
  -> normalized snapshot
  -> state diff
  -> Lark webhook
```

Why:

- The signal we care about is reset watch status and latest reset announcement.
- A Telegram bridge would require Telegram session handling, channel access, and a long-running user client.
- Direct polling keeps the system smaller and easier to operate.

### Decision 2: Use GitHub Actions

Chosen runtime:

```text
GitHub Actions schedule
  -> Python script
  -> Lark notification
  -> commit updated state.json
```

Why:

- This is a low-frequency personal automation task.
- No always-on VPS is required.
- GitHub Actions Secrets are good enough for webhook credentials.
- The workflow can be manually triggered with `workflow_dispatch`.

### Decision 3: Commit `state.json` to git

Chosen state store:

```text
data/state.json
```

Why:

- State is tiny.
- Git history provides a simple audit trail.
- No database, Redis, or external KV service is required.

### Decision 4: Keep `.env` local only

Production configuration lives in GitHub Actions Secrets.

Local development may use `.env`, but `.env` is ignored by git.

### Decision 5: Separate state fingerprint from notification key

The notifier stores two identities:

```text
fingerprint
notification_key
```

`fingerprint` represents the broader normalized snapshot and can change when API metadata or stats change.

`notification_key` represents the user-visible event that should trigger a Lark message.

Why:

- The API can revise aggregate stats such as `reset_count` without changing the latest reset announcement.
- `reset_count` is useful state, but it is not shown in the Lark message.
- Using a separate notification key prevents duplicate messages when only hidden stats change.

Fields included in `notification_key`:

- active watch status and details
- latest reset time and type
- latest announcement id, text, and URL
- source URL

Fields excluded from `notification_key`:

- `fetched_at`
- `raw_shape`
- `reset_count`
- other bookkeeping fields

## Repository layout

```text
.
├── .github/workflows/monitor.yml
├── data/state.json
├── src
│   ├── codex_resets.py
│   ├── lark.py
│   ├── main.py
│   └── state.py
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Configuration

Create these GitHub repository secrets:

```text
LARK_WEBHOOK_URL
LARK_WEBHOOK_SECRET
```

Optional variables:

```text
CODEX_RESETS_API_URL
SOURCE_URL
STATE_PATH
NOTIFY_ON_FIRST_RUN
```

Defaults:

```text
CODEX_RESETS_API_URL=https://codex-resets.com/api/v1/status
SOURCE_URL=
STATE_PATH=data/state.json
NOTIFY_ON_FIRST_RUN=false
```

`CODEX_RESETS_API_URL` points to the public status API by default. `SOURCE_URL` is only needed as a fallback override, for example if you intentionally want to parse the public HTML page.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python src/main.py --dry-run
```

## GitHub Actions setup

1. Open repository settings.
2. Go to `Secrets and variables` -> `Actions`.
3. Add `LARK_WEBHOOK_URL`.
4. Add `LARK_WEBHOOK_SECRET` if the Lark bot enables signature verification.
5. Optional: add repository variable `CODEX_RESETS_API_URL` with `https://codex-resets.com/api/v1/status`.
6. Optional: add repository variable `NOTIFY_ON_FIRST_RUN` with `true` if you want the first run to send a baseline message.
7. Trigger `Codex Reset Monitor` manually once from the Actions tab.

The workflow runs every 5 minutes.

## Notification behavior

The script builds a normalized snapshot containing fields such as:

- reset watch chance
- reset watch deadline or summary
- latest reset time
- latest reset type
- latest announcement text
- source URL

A notification is sent only when `notification_key` changes.

The broader `fingerprint` can still change when non-notification state changes, such as `reset_count`. In that case, the state file may be updated, but no duplicate Lark notification is sent.

On the first run, the script writes a baseline state without notification by default. Set `NOTIFY_ON_FIRST_RUN=true` to send the initial snapshot.

## Lark signature

Lark custom bot signature is calculated with:

```text
base64(HMAC_SHA256(timestamp + "\n" + secret, empty_message))
```

The payload is sent as a text message to the custom bot webhook.

## Development notes

This repository is intentionally small. It can later be expanded into a more general signal notifier:

```text
source adapters -> event detectors -> notification routers
```

Potential future adapters:

- Codex reset watch
- GitHub releases
- AI product updates
- SEC filing alerts
- personal market signals
