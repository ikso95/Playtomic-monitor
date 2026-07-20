from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from playtomic_core import (
    DEFAULT_CONFIG_PATH,
    MonitorError,
    build_club_info,
    build_club_runs,
    club_run_to_dict,
    club_to_dict,
    explain_filters as explain_config_filters,
    format_combined_summary,
    get_club_sections,
    load_config,
    resolve_config_path,
    resolve_state_path,
)


mcp = FastMCP("Playtomic Availability")


def _config_path(config_path: str | None = None) -> Path:
    return resolve_config_path(config_path)


def _error_payload(exc: MonitorError) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


@mcp.tool
def help() -> dict[str, Any]:
    """List Playtomic MCP tools and when to use them."""
    return {
        "ok": True,
        "default_config_path": str(DEFAULT_CONFIG_PATH),
        "notes": [
            "All tools are read-only.",
            "Manual MCP checks fetch current Playtomic availability on demand.",
            "Manual MCP checks do not mark slots as seen and do not affect scheduled Telegram alerts.",
        ],
        "tools": {
            "get_next_slots": "Fetch current matching slots using the shared config.",
            "get_status": "Show configured clubs, state path, lookahead settings, and current counts.",
            "list_clubs": "Fetch configured club metadata, timezone, sport, and court resources.",
            "explain_filters": "Return the active watch windows, durations, court filters, and notification settings.",
            "help": "List tools and usage guidance.",
        },
    }


@mcp.tool
def get_next_slots(config_path: str | None = None, include_seen: bool = True) -> dict[str, Any]:
    """Fetch current Playtomic slots that match the shared config filters."""
    try:
        resolved_config_path = _config_path(config_path)
        _, _, club_runs = build_club_runs(resolved_config_path)
        club_payloads = [club_run_to_dict(club_run, include_seen=include_seen) for club_run in club_runs]
        return {
            "ok": True,
            "config_path": str(resolved_config_path),
            "include_seen": include_seen,
            "clubs": club_payloads,
            "summary": format_combined_summary([club_payload["summary"] for club_payload in club_payloads]),
        }
    except MonitorError as exc:
        return _error_payload(exc)


@mcp.tool
def get_status(config_path: str | None = None) -> dict[str, Any]:
    """Return monitor status and current slot counts for the shared config."""
    try:
        resolved_config_path = _config_path(config_path)
        config, previous_state, club_runs = build_club_runs(resolved_config_path)
        state_path = resolve_state_path(config, resolved_config_path)
        return {
            "ok": True,
            "config_path": str(resolved_config_path),
            "state_path": str(state_path),
            "known_slots_count": len(previous_state.get("known_slots", [])),
            "clubs_count": len(club_runs),
            "clubs": [
                {
                    "name": club_run.club.name,
                    "timezone": club_run.club.timezone,
                    "matching_slots_count": len(club_run.matches),
                    "new_slots_count": len(club_run.new_slots),
                    "notifications_allowed_now": club_run.notifications_allowed_now,
                }
                for club_run in club_runs
            ],
            "filters": explain_config_filters(config),
        }
    except MonitorError as exc:
        return _error_payload(exc)


@mcp.tool
def list_clubs(config_path: str | None = None) -> dict[str, Any]:
    """Fetch metadata and court resources for all configured Playtomic clubs."""
    try:
        resolved_config_path = _config_path(config_path)
        config = load_config(resolved_config_path)
        clubs = []
        for club_section in get_club_sections(config):
            club = build_club_info(club_section)
            clubs.append(club_to_dict(club))
        return {
            "ok": True,
            "config_path": str(resolved_config_path),
            "clubs": clubs,
        }
    except MonitorError as exc:
        return _error_payload(exc)


@mcp.tool
def explain_filters(config_path: str | None = None) -> dict[str, Any]:
    """Explain the shared config filters that decide which slots match."""
    try:
        resolved_config_path = _config_path(config_path)
        config = load_config(resolved_config_path)
        return {
            "ok": True,
            "config_path": str(resolved_config_path),
            "filters": explain_config_filters(config),
        }
    except MonitorError as exc:
        return _error_payload(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
