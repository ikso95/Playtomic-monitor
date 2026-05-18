#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from playtomic_core import (
    DEFAULT_CONFIG_PATH,
    MonitorError,
    build_club_runs,
    build_next_state_payload,
    format_combined_summary,
    format_run_summary,
    http_get_json,
    http_get_text,
    load_config,
    resolve_state_path,
    save_state_payload,
)


def notify_console(message: str) -> None:
    print(message)


def notify_callmebot(notification_config: dict[str, Any], message: str) -> None:
    phone = notification_config.get("phone", "")
    api_key = notification_config.get("api_key", "")
    if not phone or phone.startswith("+48YOUR"):
        raise MonitorError("CallMeBot phone is not configured.")
    if not api_key or api_key == "YOUR_CALLMEBOT_API_KEY":
        raise MonitorError("CallMeBot API key is not configured.")

    query = urllib.parse.urlencode({"phone": phone, "text": message, "apikey": api_key})
    url = f"https://api.callmebot.com/whatsapp.php?{query}"
    http_get_text(url)


def notify_telegram(notification_config: dict[str, Any], message: str) -> None:
    bot_token = notification_config.get("bot_token", "")
    chat_id = str(notification_config.get("chat_id", ""))
    if not bot_token or bot_token == "123456:ABC":
        raise MonitorError("Telegram bot token is not configured.")
    if not chat_id or chat_id == "123456789":
        raise MonitorError("Telegram chat_id is not configured.")

    query = urllib.parse.urlencode({"chat_id": chat_id, "text": message})
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage?{query}"
    http_get_json(url)


def send_notifications(config: dict[str, Any], message: str) -> None:
    notifications = config.get("notifications", {})
    providers = notifications.get("providers", ["console"])

    for provider in providers:
        if provider == "console":
            notify_console(message)
        elif provider == "callmebot_whatsapp":
            notify_callmebot(notifications.get("callmebot_whatsapp", {}), message)
        elif provider == "telegram":
            notify_telegram(notifications.get("telegram", {}), message)
        else:
            raise MonitorError(f"Unsupported notification provider: {provider}")


def should_notify_when_no_new_slots(config: dict[str, Any]) -> bool:
    notifications = config.get("notifications", {})
    return bool(notifications.get("notify_when_no_new_slots", False))


def run_monitor(config_path: Path, dry_run: bool, test_notification: str | None) -> int:
    config = load_config(config_path)
    notify_when_no_new_slots = should_notify_when_no_new_slots(config)

    if test_notification:
        send_notifications(config, test_notification)
        return 0

    config, previous_state, club_runs = build_club_runs(config_path)

    summary = format_combined_summary(
        [
            format_run_summary(
                club=club_run.club,
                matches=list(club_run.matches),
                new_slots=list(club_run.new_slots),
                dry_run=dry_run,
            )
            for club_run in club_runs
        ]
    )
    print(summary)

    if dry_run:
        return 0

    notification_sections = [
        format_run_summary(
            club=club_run.club,
            matches=list(club_run.matches),
            new_slots=list(club_run.new_slots),
            dry_run=False,
        )
        for club_run in club_runs
        if club_run.notifications_allowed_now
        and (club_run.new_slots or notify_when_no_new_slots)
    ]
    if notification_sections:
        send_notifications(config, format_combined_summary(notification_sections))

    next_state = build_next_state_payload(previous_state=previous_state, club_runs=club_runs)
    save_state_payload(resolve_state_path(config, config_path), next_state, previous_state=previous_state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Playtomic availability for matching slots.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to TOML config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print current matching slots and skip notifications/state updates.",
    )
    parser.add_argument(
        "--test-notification",
        help="Send a test notification and exit.",
    )
    args = parser.parse_args()

    try:
        config_path = Path(args.config).expanduser().resolve()
        return run_monitor(
            config_path=config_path,
            dry_run=args.dry_run,
            test_notification=args.test_notification,
        )
    except MonitorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
