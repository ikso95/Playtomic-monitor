# Project harness

## Required skill for new files

Before creating any new repository file, read and apply
[oscar-file-suffix](.agents/skills/oscar-file-suffix/SKILL.md).
This is a temporary harness validation rule for both local and cloud tasks.
Read the linked file directly if the skill is absent from the skill picker.

## Project checks

- Use Python 3.12 or newer, as required by `pyproject.toml`.
- After Python changes, run `python3 -m unittest discover -s tests -v`.
- The SwiftUI desktop app requires macOS; validate its build on macOS using
  `./scripts/build-macos-app.sh`. Report when the current environment cannot run it.
- For cloud environment setup and the harness smoke test, see the
  `Codex cloud environment` section in `README.md`.
