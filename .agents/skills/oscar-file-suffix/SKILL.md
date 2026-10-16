---
name: oscar-file-suffix
description: Apply the temporary Oscar filename convention whenever creating new repository files in this project, including source, tests, documentation, and smoke-test files. Use in local and cloud tasks; existing-file edits alone do not require it.
---

# Oscar file suffix

Make use of the project harness visible through new filenames.

1. Before creating files, announce once per task: `Using oscar-file-suffix.`
2. Append the exact text `Oscar` to each new file's stem, before its final
   extension: `example.txt` becomes `exampleOscar.txt`, `test_slots.py` becomes
   `test_slotsOscar.py`, and `notes` becomes `notesOscar`. Leave directory names
   unchanged. A stem already ending in `Oscar` needs no additional suffix.
3. Create the file at its final name and use that path in imports, links, and
   commands. Apply this only to files created for the current task; preserve
   pre-existing files and their names, including other people's untracked files.
4. Preserve exact filenames required by discovery or tooling, such as
   `AGENTS.md`, `SKILL.md`, `openai.yaml`, `__init__.py`, `pyproject.toml`, and
   `Package.swift`. Leave generated build outputs, dependency files, caches,
   and temporary files outside the repository to their tools. An explicit user
   instruction to keep an exact filename takes precedence. Report any exception
   for a new authored repository file and its reason.
5. Before finishing, check every file you created against this convention.
   Report the resulting paths and any exceptions. If the suffixed path already
   exists, choose a distinct stem rather than overwriting unrelated work.

This is an instruction-following smoke test, not a filesystem watcher. Reading
this file and producing a suffixed artifact demonstrates use of the harness;
it does not establish whether skill discovery or the `AGENTS.md` link loaded it.
