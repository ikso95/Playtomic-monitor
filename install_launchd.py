#!/usr/bin/env python3

from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path

from playtomic_monitor import MonitorError, load_config


DEFAULT_INTERVAL_SECONDS = 1200


def build_plist(config_path: Path, interval: int, label: str) -> dict[str, object]:
    project_dir = Path(__file__).resolve().parent
    tmp_dir = project_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    return {
        "Label": label,
        "ProgramArguments": [
            "/usr/bin/env",
            "python3",
            str(project_dir / "playtomic_monitor.py"),
            "--config",
            str(config_path),
        ],
        "WorkingDirectory": str(project_dir),
        "RunAtLoad": True,
        "StartInterval": interval,
        "StandardOutPath": str(tmp_dir / "launchd.stdout.log"),
        "StandardErrorPath": str(tmp_dir / "launchd.stderr.log"),
    }


def run_launchctl(action: str, plist_path: Path) -> None:
    subprocess.run(
        ["launchctl", action, str(plist_path)],
        check=False,
    )


def parse_interval_seconds(value: object, source: str) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise MonitorError(f"Invalid launchd interval in {source}: {value!r}") from exc

    if interval <= 0:
        raise MonitorError(f"launchd interval must be positive in {source}: {interval}")

    return interval


def resolve_interval(config_path: Path, cli_interval: int | None) -> int:
    if cli_interval is not None:
        return parse_interval_seconds(cli_interval, "--interval")

    config = load_config(config_path)
    launchd_config = config.get("launchd", {})
    if not isinstance(launchd_config, dict):
        raise MonitorError("Config section [launchd] must be a table.")

    raw_interval = launchd_config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    return parse_interval_seconds(raw_interval, "[launchd].interval_seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the Playtomic monitor as a launchd agent.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent / "config.toml"),
        help="Path to config.toml",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Polling interval in seconds. Overrides [launchd].interval_seconds in the config file.",
    )
    parser.add_argument(
        "--label",
        default="com.oskarlis.playtomic.monitor",
        help="launchd label",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Unload any existing agent with the same label and load the new one.",
    )
    parser.add_argument(
        "--unload",
        action="store_true",
        help="Unload the existing agent after writing the plist.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    interval = resolve_interval(config_path=config_path, cli_interval=args.interval)
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{args.label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    plist = build_plist(config_path=config_path, interval=interval, label=args.label)
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle)

    print(f"Wrote {plist_path}")
    print(f"Polling every {interval} seconds")

    if args.unload or args.load:
        run_launchctl("unload", plist_path)

    if args.load:
        run_launchctl("load", plist_path)
        print(f"Loaded {args.label}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
