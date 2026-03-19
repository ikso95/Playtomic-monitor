#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


WEEKDAY_MAP = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


class MonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowRule:
    weekdays: frozenset[int]
    start: time
    end: time


@dataclass(frozen=True)
class Resource:
    resource_id: str
    name: str
    features: tuple[str, ...]
    sport: str


@dataclass(frozen=True)
class ClubInfo:
    name: str
    tenant_id: str
    timezone: str
    slug: str
    sport_id: str
    resources: tuple[Resource, ...]
    club_url: str


@dataclass(frozen=True)
class Slot:
    slot_id: str
    resource_id: str
    resource_name: str
    features: tuple[str, ...]
    start_local: datetime
    end_local: datetime
    duration_minutes: int
    price: str | None
    club_day_url: str

    @property
    def signature(self) -> str:
        return "|".join(
            [
                self.resource_id,
                self.start_local.isoformat(),
                str(self.duration_minutes),
            ]
        )


def http_get_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PlaytomicMonitor/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        raise MonitorError(f"Request failed for {url}: {exc}") from exc


def http_get_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PlaytomicMonitor/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise MonitorError(f"Request failed for {url}: {exc}") from exc


def parse_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":")
        return time(hour=int(hour_text), minute=int(minute_text))
    except Exception as exc:
        raise MonitorError(f"Invalid time value: {value}") from exc


def load_config(path: Path) -> dict[str, Any]:
    try:
        return parse_toml_subset(path.read_text())
    except FileNotFoundError as exc:
        raise MonitorError(f"Config file not found: {path}") from exc


def strip_inline_comment(line: str) -> str:
    in_string = False
    escaped = False
    output: list[str] = []

    for char in line:
        if char == "\\" and in_string:
            escaped = not escaped
            output.append(char)
            continue
        if char == '"' and not escaped:
            in_string = not in_string
        if char == "#" and not in_string:
            break
        output.append(char)
        escaped = False

    return "".join(output).strip()


def split_toml_path(value: str) -> list[str]:
    return [part.strip() for part in value.split(".") if part.strip()]


def parse_toml_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if raw.startswith('"') or raw.startswith("["):
        return ast.literal_eval(raw)
    try:
        return int(raw)
    except ValueError:
        return raw


def parse_toml_subset(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current: dict[str, Any] = root

    for raw_line in text.splitlines():
        line = strip_inline_comment(raw_line)
        if not line:
            continue

        if line.startswith("[[") and line.endswith("]]"):
            path = split_toml_path(line[2:-2].strip())
            target = root
            for key in path[:-1]:
                target = target.setdefault(key, {})
            table_list = target.setdefault(path[-1], [])
            if not isinstance(table_list, list):
                raise MonitorError(f"Invalid TOML structure for {line}")
            new_item: dict[str, Any] = {}
            table_list.append(new_item)
            current = new_item
            continue

        if line.startswith("[") and line.endswith("]"):
            path = split_toml_path(line[1:-1].strip())
            current = root
            for key in path:
                current = current.setdefault(key, {})
                if not isinstance(current, dict):
                    raise MonitorError(f"Invalid TOML structure for {line}")
            continue

        if "=" not in line:
            raise MonitorError(f"Invalid config line: {line}")

        key, raw_value = line.split("=", 1)
        current[key.strip()] = parse_toml_value(raw_value.strip())

    return root


def normalize_windows(raw_windows: list[dict[str, Any]]) -> list[WindowRule]:
    windows: list[WindowRule] = []
    for raw in raw_windows:
        days = raw.get("days", [])
        weekdays = frozenset(WEEKDAY_MAP[day.lower()] for day in days)
        windows.append(
            WindowRule(
                weekdays=weekdays,
                start=parse_time(raw["start"]),
                end=parse_time(raw["end"]),
            )
        )
    if not windows:
        raise MonitorError("Config must include at least one [[watch_windows]] entry.")
    return windows


def extract_next_data_payload(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">\s*(.*?)\s*</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise MonitorError("Could not find __NEXT_DATA__ on the Playtomic club page.")
    return json.loads(match.group(1))


def fetch_club_info(club_url: str, sport_id: str) -> ClubInfo:
    html = http_get_text(club_url)
    payload = extract_next_data_payload(html)
    tenant = payload["props"]["pageProps"]["tenant"]
    resources = tuple(
        Resource(
            resource_id=resource["resourceId"],
            name=resource["name"],
            features=tuple(resource.get("features", [])),
            sport=resource["sport"],
        )
        for resource in tenant["resources"]
    )
    return ClubInfo(
        name=tenant["tenant_name"],
        tenant_id=tenant["tenant_id"],
        timezone=tenant["address"]["timezone"],
        slug=tenant["slug"],
        sport_id=sport_id,
        resources=resources,
        club_url=club_url.rstrip("/"),
    )


def utc_slot_to_local(slot_date: str, start_time: str, timezone_name: str, duration_minutes: int) -> tuple[datetime, datetime]:
    utc_start = datetime.fromisoformat(f"{slot_date}T{start_time}+00:00")
    local_start = utc_start.astimezone(ZoneInfo(timezone_name))
    local_end = local_start + timedelta(minutes=duration_minutes)
    return local_start, local_end


def fetch_day_slots(club: ClubInfo, requested_date: date) -> list[Slot]:
    params = urllib.parse.urlencode(
        {
            "tenant_id": club.tenant_id,
            "date": requested_date.isoformat(),
            "sport_id": club.sport_id,
        }
    )
    url = f"https://playtomic.com/api/clubs/availability?{params}"
    payload = http_get_json(url)

    resources_by_id = {resource.resource_id: resource for resource in club.resources}
    slots: list[Slot] = []

    for item in payload:
        resource_id = item["resource_id"]
        resource = resources_by_id.get(resource_id)
        if resource is None:
            continue
        for raw_slot in item.get("slots", []):
            duration_minutes = int(raw_slot["duration"])
            start_local, end_local = utc_slot_to_local(
                slot_date=item["start_date"],
                start_time=raw_slot["start_time"],
                timezone_name=club.timezone,
                duration_minutes=duration_minutes,
            )
            slot_id = re.sub(
                r"[^a-z0-9-]",
                "-",
                f"{resource_id}-{start_local.isoformat()}-{duration_minutes}".lower(),
            )
            slots.append(
                Slot(
                    slot_id=slot_id,
                    resource_id=resource_id,
                    resource_name=resource.name,
                    features=resource.features,
                    start_local=start_local,
                    end_local=end_local,
                    duration_minutes=duration_minutes,
                    price=raw_slot.get("price"),
                    club_day_url=f"{club.club_url}?date={requested_date.isoformat()}",
                )
            )

    return slots


def slot_matches_filters(
    slot: Slot,
    filters: dict[str, Any],
    windows: list[WindowRule],
    minimum_notice_minutes: int,
    now_local: datetime,
) -> bool:
    required_features = {feature.lower() for feature in filters.get("required_features", [])}
    slot_features = {feature.lower() for feature in slot.features}
    if not required_features.issubset(slot_features):
        return False

    include_resource_names = set(filters.get("include_resource_names", []))
    if include_resource_names and slot.resource_name not in include_resource_names:
        return False

    exclude_resource_names = set(filters.get("exclude_resource_names", []))
    if slot.resource_name in exclude_resource_names:
        return False

    excluded_name_substrings = [item.lower() for item in filters.get("excluded_name_substrings", [])]
    if any(item in slot.resource_name.lower() for item in excluded_name_substrings):
        return False

    allowed_durations = {int(value) for value in filters.get("allowed_durations", [])}
    if allowed_durations and slot.duration_minutes not in allowed_durations:
        return False

    if slot.start_local < now_local + timedelta(minutes=minimum_notice_minutes):
        return False

    for window in windows:
        if slot.start_local.weekday() not in window.weekdays:
            continue
        window_start = datetime.combine(slot.start_local.date(), window.start, tzinfo=slot.start_local.tzinfo)
        window_end = datetime.combine(slot.start_local.date(), window.end, tzinfo=slot.start_local.tzinfo)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        if slot.start_local >= window_start and slot.end_local <= window_end:
            return True
    return False


def collect_matching_slots(
    club: ClubInfo,
    config: dict[str, Any],
) -> list[Slot]:
    watch_config = config["watch"]
    windows = normalize_windows(config.get("watch_windows", []))
    filters = config.get("filters", {})

    now_local = datetime.now(ZoneInfo(club.timezone))
    look_ahead_days = int(watch_config.get("look_ahead_days", 7))
    minimum_notice_minutes = int(watch_config.get("minimum_notice_minutes", 0))

    candidate_dates: list[date] = []
    for offset in range(look_ahead_days):
        candidate_date = (now_local + timedelta(days=offset)).date()
        weekday = candidate_date.weekday()
        if any(weekday in window.weekdays for window in windows):
            candidate_dates.append(candidate_date)

    matching_slots: list[Slot] = []
    for candidate_date in candidate_dates:
        for slot in fetch_day_slots(club, candidate_date):
            if slot_matches_filters(
                slot=slot,
                filters=filters,
                windows=windows,
                minimum_notice_minutes=minimum_notice_minutes,
                now_local=now_local,
            ):
                matching_slots.append(slot)

    matching_slots.sort(key=lambda slot: (slot.start_local, slot.resource_name, slot.duration_minutes))
    return matching_slots


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"known_slots": []}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise MonitorError(f"State file is not valid JSON: {path}") from exc


def build_state_payload(slots: list[Slot]) -> dict[str, Any]:
    return {
        "known_slots": sorted({slot.signature for slot in slots}),
    }


def save_state(path: Path, slots: list[Slot], previous_state: dict[str, Any] | None = None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_state_payload(slots)
    previous_known_slots = sorted(set((previous_state or {}).get("known_slots", [])))
    if previous_known_slots == payload["known_slots"]:
        return False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return True


def format_slots(slots: list[Slot], club: ClubInfo) -> str:
    if not slots:
        return f"No matching {club.name} slots right now."

    lines = [f"New {club.name} slots found:"]
    last_date: date | None = None

    for slot in slots:
        slot_date = slot.start_local.date()
        if slot_date != last_date:
            lines.append("")
            lines.append(slot.start_local.strftime("%A %Y-%m-%d"))
            last_date = slot_date
        price_text = slot.price or "price unavailable"
        lines.append(
            "  "
            + f"{slot.start_local.strftime('%H:%M')}-{slot.end_local.strftime('%H:%M')} | "
            + f"{slot.resource_name} | {slot.duration_minutes} min | {price_text}"
        )
        lines.append("  " + slot.club_day_url)

    return "\n".join(lines)


def format_run_summary(club: ClubInfo, matches: list[Slot], new_slots: list[Slot], dry_run: bool) -> str:
    if dry_run:
        return format_slots(matches, club)
    if new_slots:
        return format_slots(new_slots, club)
    if matches:
        return f"No new matching {club.name} slots since the last run."
    return f"No matching {club.name} slots right now."


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
    club_section = config.get("club", {})
    club_url = club_section["url"]
    sport_id = club_section.get("sport_id", "PADEL")

    if test_notification:
        send_notifications(config, test_notification)
        return 0

    club = fetch_club_info(club_url=club_url, sport_id=sport_id)
    matches = collect_matching_slots(club=club, config=config)

    state_path = Path(config["watch"].get("state_path", "state/availability_state.json"))
    if not state_path.is_absolute():
        state_path = (config_path.parent / state_path).resolve()

    previous_state = load_state(state_path)
    known_slots = set(previous_state.get("known_slots", []))
    new_slots = [slot for slot in matches if slot.signature not in known_slots]

    summary = format_run_summary(club=club, matches=matches, new_slots=new_slots, dry_run=dry_run)
    print(summary)

    if dry_run:
        return 0

    if new_slots or should_notify_when_no_new_slots(config):
        send_notifications(config, summary)

    save_state(state_path, matches, previous_state=previous_state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Playtomic availability for matching slots.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent / "config.toml"),
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
