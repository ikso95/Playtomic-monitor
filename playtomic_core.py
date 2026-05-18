from __future__ import annotations

import json
import re
import tomllib
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

WEEKDAY_NAMES = {value: key for key, value in WEEKDAY_MAP.items()}

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.shared.toml"


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


@dataclass(frozen=True)
class ClubRun:
    club: ClubInfo
    matches: tuple[Slot, ...]
    new_slots: tuple[Slot, ...]
    notifications_allowed_now: bool


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is None:
        return DEFAULT_CONFIG_PATH
    return Path(config_path).expanduser().resolve()


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
        return tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise MonitorError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise MonitorError(f"Config file is not valid TOML: {path}: {exc}") from exc


def normalize_windows(raw_windows: list[dict[str, Any]]) -> list[WindowRule]:
    windows: list[WindowRule] = []
    for raw in raw_windows:
        days = raw.get("days", [])
        try:
            weekdays = frozenset(WEEKDAY_MAP[day.lower()] for day in days)
        except KeyError as exc:
            raise MonitorError(f"Invalid weekday value: {exc.args[0]}") from exc
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


def normalize_optional_windows(raw_windows: list[dict[str, Any]]) -> list[WindowRule]:
    if not raw_windows:
        return []
    return normalize_windows(raw_windows)


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


def utc_slot_to_local(
    slot_date: str,
    start_time: str,
    timezone_name: str,
    duration_minutes: int,
) -> tuple[datetime, datetime]:
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


def is_datetime_within_window(moment: datetime, window: WindowRule) -> bool:
    if moment.weekday() not in window.weekdays:
        return False

    window_start = datetime.combine(moment.date(), window.start, tzinfo=moment.tzinfo)
    window_end = datetime.combine(moment.date(), window.end, tzinfo=moment.tzinfo)

    if window_end > window_start:
        return window_start <= moment <= window_end

    if moment >= window_start:
        return True

    previous_day = moment - timedelta(days=1)
    if previous_day.weekday() not in window.weekdays:
        return False
    previous_start = datetime.combine(previous_day.date(), window.start, tzinfo=moment.tzinfo)
    previous_end = datetime.combine(moment.date(), window.end, tzinfo=moment.tzinfo)
    return previous_start <= moment <= previous_end


def should_send_notifications_now(config: dict[str, Any], timezone_name: str) -> bool:
    notification_windows = normalize_optional_windows(config.get("notification_windows", []))
    if not notification_windows:
        return True

    now_local = datetime.now(ZoneInfo(timezone_name))
    return any(is_datetime_within_window(now_local, window) for window in notification_windows)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"known_slots": []}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise MonitorError(f"State file is not valid JSON: {path}") from exc


def save_state_payload(
    path: Path,
    payload: dict[str, Any],
    previous_state: dict[str, Any] | None = None,
) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if (previous_state or {}) == payload:
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


def format_combined_summary(sections: list[str]) -> str:
    return "\n\n".join(section for section in sections if section)


def get_club_sections(config: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_club = config.get("club")
    clubs = config.get("clubs", [])

    if legacy_club and clubs:
        raise MonitorError("Use either [club] or [[clubs]] in the config, not both.")

    if legacy_club:
        return [legacy_club]

    if clubs:
        return clubs

    raise MonitorError("Config must include [club] or at least one [[clubs]] entry.")


def resolve_state_path(config: dict[str, Any], config_path: Path) -> Path:
    state_path = Path(config["watch"].get("state_path", "state/availability_state.json"))
    if not state_path.is_absolute():
        state_path = (config_path.parent / state_path).resolve()
    return state_path


def build_club_run(
    club_section: dict[str, Any],
    config: dict[str, Any],
    known_slots: set[str],
) -> ClubRun:
    club_url = club_section["url"]
    sport_id = club_section.get("sport_id", "PADEL")
    club = fetch_club_info(club_url=club_url, sport_id=sport_id)
    matches = tuple(collect_matching_slots(club=club, config=config))
    new_slots = tuple(slot for slot in matches if slot.signature not in known_slots)
    notifications_allowed_now = should_send_notifications_now(config=config, timezone_name=club.timezone)
    return ClubRun(
        club=club,
        matches=matches,
        new_slots=new_slots,
        notifications_allowed_now=notifications_allowed_now,
    )


def build_club_runs(config_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[ClubRun]]:
    config = load_config(config_path)
    previous_state = load_state(resolve_state_path(config, config_path))
    known_slots = set(previous_state.get("known_slots", []))
    club_runs = [
        build_club_run(club_section=club_section, config=config, known_slots=known_slots)
        for club_section in get_club_sections(config)
    ]
    return config, previous_state, club_runs


def build_next_state_payload(previous_state: dict[str, Any], club_runs: list[ClubRun]) -> dict[str, Any]:
    previous_known = set(previous_state.get("known_slots", []))
    next_known: set[str] = set()

    for club_run in club_runs:
        current_signatures = {slot.signature for slot in club_run.matches}
        if club_run.notifications_allowed_now:
            next_known.update(current_signatures)
        else:
            next_known.update(previous_known.intersection(current_signatures))

    return {"known_slots": sorted(next_known)}


def slot_to_dict(slot: Slot) -> dict[str, Any]:
    return {
        "signature": slot.signature,
        "resource_id": slot.resource_id,
        "resource_name": slot.resource_name,
        "features": list(slot.features),
        "start_local": slot.start_local.isoformat(),
        "end_local": slot.end_local.isoformat(),
        "duration_minutes": slot.duration_minutes,
        "price": slot.price,
        "club_day_url": slot.club_day_url,
    }


def club_to_dict(club: ClubInfo) -> dict[str, Any]:
    return {
        "name": club.name,
        "tenant_id": club.tenant_id,
        "timezone": club.timezone,
        "slug": club.slug,
        "sport_id": club.sport_id,
        "club_url": club.club_url,
        "resources": [
            {
                "resource_id": resource.resource_id,
                "name": resource.name,
                "features": list(resource.features),
                "sport": resource.sport,
            }
            for resource in club.resources
        ],
    }


def club_run_to_dict(club_run: ClubRun, include_seen: bool = True) -> dict[str, Any]:
    slots = club_run.matches if include_seen else club_run.new_slots
    return {
        "club": club_to_dict(club_run.club),
        "notifications_allowed_now": club_run.notifications_allowed_now,
        "matching_slots_count": len(club_run.matches),
        "new_slots_count": len(club_run.new_slots),
        "slots": [slot_to_dict(slot) for slot in slots],
        "summary": format_run_summary(
            club=club_run.club,
            matches=list(club_run.matches),
            new_slots=list(club_run.new_slots),
            dry_run=include_seen,
        ),
    }


def windows_to_text(raw_windows: list[dict[str, Any]]) -> list[str]:
    lines = []
    for raw in raw_windows:
        days = ", ".join(raw.get("days", []))
        lines.append(f"{days}: {raw.get('start')} - {raw.get('end')}")
    return lines


def explain_filters(config: dict[str, Any]) -> dict[str, Any]:
    watch = config.get("watch", {})
    filters = config.get("filters", {})
    notifications = config.get("notifications", {})
    return {
        "clubs": get_club_sections(config),
        "look_ahead_days": watch.get("look_ahead_days", 7),
        "minimum_notice_minutes": watch.get("minimum_notice_minutes", 0),
        "watch_windows": windows_to_text(config.get("watch_windows", [])),
        "notification_windows": windows_to_text(config.get("notification_windows", [])),
        "required_features": filters.get("required_features", []),
        "excluded_name_substrings": filters.get("excluded_name_substrings", []),
        "include_resource_names": filters.get("include_resource_names", []),
        "exclude_resource_names": filters.get("exclude_resource_names", []),
        "allowed_durations": filters.get("allowed_durations", []),
        "notification_providers": notifications.get("providers", ["console"]),
        "notify_when_no_new_slots": bool(notifications.get("notify_when_no_new_slots", False)),
    }
