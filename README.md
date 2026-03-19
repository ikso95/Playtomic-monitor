# Playtomic Availability Monitor

Small local monitor for Playtomic club availability.

It polls the public Playtomic availability endpoint, filters slots by your time windows and court preferences, remembers what was already seen, and sends a notification only when a new matching slot appears.

## Why this approach

- Playtomic exposes public availability data for this club without logging in.
- Official WhatsApp messaging is not the best fit for a free personal automation.
- This project keeps everything local on your Mac and uses only Python's standard library.

## What I implemented

- `playtomic_monitor.py`
  - fetches club metadata from the public club page
  - fetches availability from the public Playtomic API
  - filters to doubles courts by default
  - filters by configurable weekday/time windows
  - stores prior matches in `state/availability_state.json`
  - notifies only about newly appeared matching slots
- `install_launchd.py`
  - installs an hourly macOS `launchd` agent
- `config.toml`
  - editable local config
- `config.example.toml`
  - clean template copy

## Notification options

Supported providers:

- `console`
  - prints matches to stdout
- `callmebot_whatsapp`
  - free for personal use, but unofficial
- `telegram`
  - official Telegram Bot API, usually the cleaner fallback

You can also choose whether the monitor should send a message even when there are no new slots:

```toml
[notifications]
providers = ["callmebot_whatsapp"]
notify_when_no_new_slots = true
```

When enabled, the hourly run will also send messages like:

- `No new matching Padel Pl Wrocław slots since the last run.`
- `No matching Padel Pl Wrocław slots right now.`

## First run

```bash
cd /Users/oskarlis/AndroidStudioProjects/Playtomic
python3 playtomic_monitor.py --config config.toml --dry-run
```

`--dry-run` prints matches and does not update state or send notifications.

## Enable WhatsApp via CallMeBot

1. Open [CallMeBot WhatsApp instructions](https://www.callmebot.com/blog/free-api-whatsapp-messages/).
2. Follow the activation flow and get your API key.
3. Edit `config.toml`:

```toml
[notifications]
providers = ["callmebot_whatsapp"]

[notifications.callmebot_whatsapp]
phone = "+48YOUR_NUMBER"
api_key = "YOUR_CALLMEBOT_API_KEY"
```

4. Test:

```bash
python3 playtomic_monitor.py --config config.toml --test-notification "Playtomic test"
```

## Telegram fallback

If you want a more official free channel, create a Telegram bot with [BotFather](https://core.telegram.org/bots#6-botfather), then set:

```toml
[notifications]
providers = ["telegram"]

[notifications.telegram]
bot_token = "123456:ABC"
chat_id = "123456789"
```

## Install hourly automation on macOS

```bash
cd /Users/oskarlis/AndroidStudioProjects/Playtomic
python3 install_launchd.py --config /Users/oskarlis/AndroidStudioProjects/Playtomic/config.toml --interval 3600 --load
```

This writes:

- `~/Library/LaunchAgents/com.oskarlis.playtomic.monitor.plist`

Logs go to:

- `/Users/oskarlis/AndroidStudioProjects/Playtomic/tmp/launchd.stdout.log`
- `/Users/oskarlis/AndroidStudioProjects/Playtomic/tmp/launchd.stderr.log`

## Customizing play windows

Edit `watch_windows` in `config.toml`.

Example:

```toml
[[watch_windows]]
days = ["mon", "wed", "thu"]
start = "17:30"
end = "20:00"

[[watch_windows]]
days = ["sun"]
start = "10:00"
end = "13:00"
```

Slots must fit fully inside the configured window.

## Customizing courts

Defaults already prefer doubles courts by requiring the `double` feature and excluding names containing `single`.

You can also restrict to specific courts:

```toml
[filters]
include_resource_names = ["Kort 1", "Kort 2", "Kort 3"]
```

## Files

- `/Users/oskarlis/AndroidStudioProjects/Playtomic/playtomic_monitor.py`
- `/Users/oskarlis/AndroidStudioProjects/Playtomic/install_launchd.py`
- `/Users/oskarlis/AndroidStudioProjects/Playtomic/config.toml`
- `/Users/oskarlis/AndroidStudioProjects/Playtomic/config.example.toml`

## GitHub Actions

The repository includes a scheduled workflow in `.github/workflows/playtomic-monitor.yml`.

It runs:

- every hour at minute `17` UTC
- manually via `workflow_dispatch`

### Why minute 17

GitHub documents that scheduled workflows can be delayed during high load, especially near the start of the hour, so the workflow is intentionally not scheduled at `:00`.

### How GitHub config works

- commit `config.github.toml`
  - non-secret settings only
  - days, time windows, durations, filters
- keep WhatsApp secrets in GitHub Secrets
  - `CALLMEBOT_PHONE`
  - `CALLMEBOT_API_KEY`
- the workflow builds `config.runtime.toml` during the run

### State persistence

The workflow persists `state/availability_state.json` back into the repository.

That file is committed only when the actual slot signature set changes, so the workflow does not create useless state commits on every run.

### Setup steps

1. Create a GitHub repository for this project.
2. Push this folder to that repository.
3. In GitHub, open:
   `Settings -> Secrets and variables -> Actions`
4. Add these repository secrets:
   - `CALLMEBOT_PHONE`
   - `CALLMEBOT_API_KEY`
5. Open:
   `Settings -> Actions -> General`
6. Make sure workflows are allowed.
7. Open the workflow tab and manually run `Playtomic Monitor` once.

### Editing play windows

Update `config.github.toml`, commit, and push.

### Important GitHub scheduling note

GitHub scheduled workflows run in UTC, not your local time zone.

For example:

- `17 * * * *` means every hour at minute `17` UTC
- in winter Poland time, that is usually minute `17` of each local hour as well, but DST changes can shift local interpretation
