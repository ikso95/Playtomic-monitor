#!/usr/bin/env python3

from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path


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
        default=3600,
        help="Polling interval in seconds. Default: 3600",
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
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{args.label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    plist = build_plist(config_path=config_path, interval=args.interval, label=args.label)
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle)

    print(f"Wrote {plist_path}")

    if args.unload or args.load:
        run_launchctl("unload", plist_path)

    if args.load:
        run_launchctl("load", plist_path)
        print(f"Loaded {args.label}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
