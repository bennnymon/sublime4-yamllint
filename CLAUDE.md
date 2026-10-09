# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Repository Overview

A Sublime Text 4 package that lints `*.yml`/`*.yaml` buffers with `yamllint` and
auto-fixes them with `yamlfix`. Both are external CLI tools invoked via
`subprocess`; the package itself has no third-party Python dependencies.

## Key Files

- `yamllint.py`: the entire plugin — commands, event listener, rendering.
- `yamllint.sublime-settings`: default settings with inline docs for every key.
- `Default.sublime-commands`, `Main.sublime-menu`, `Context.sublime-menu`:
  Command Palette / Tools menu / context menu entries.
- `Default (OSX|Linux|Windows).sublime-keymap`: keybindings (scoped to `source.yaml`).
- `messages.json` + `messages/install.txt`: message shown on install.
- `README.md`: user-facing docs, including a settings table.

## Architecture (`yamllint.py`)

- **Lint** (`YamllintLintCommand`): pipes the buffer (unsaved content included)
  into `yamllint -f parsable -`, parses lines with `PARSABLE_RE`, then renders
  regions, phantoms, status bar and output panel via `apply_lint_results`.
  Exit codes: 0 = clean, 1 = issues, 2 = usage/config error.
- **Fix** (`YamllintFixCommand`): yamlfix has no reliable stdin mode, so the buffer
  is written to a temp file, fixed in place, read back, and diffed into the view
  by `YamllintReplaceContentCommand` (only changed line ranges, keeps undo sane).
  Optional pre-step: tab expansion; optional post-step: `add_top_level_spacing`.
- **Events** (`YamllintEventListener`): lint on load/save/modify (debounced),
  fix on save. `_skip_next_fix_on_save` stops the re-save after an auto-fix from
  triggering yamlfix again.
- **Per-view state** lives in module-level dicts keyed by `view.id()`
  (`_view_issues`, `_phantom_sets`, `_modify_timers`, `_skip_next_fix_on_save`).
  Anything new added there must also be cleaned up in `on_close`.

## Critical Patterns

- **Python 3.8**: Sublime runs this plugin in its 3.8 plugin host (`.python-version`).
  Do not use 3.9+ features (`dict | dict`, `str.removeprefix`, `list[int]`
  annotations, `match`, etc.). Stick to the standard library.
- **Threading**: subprocess work runs in a `threading.Thread`. Every view/window/UI
  call from a worker thread must be wrapped in `sublime.set_timeout(..., 0)`.
- **Errors — loud vs. quiet**: user-triggered actions use `report_error` (modal,
  truncated at `MAX_DIALOG_CHARS`, full text in the panel). Automatic triggers pass
  `quiet=True` and use `report_error_quiet` (status bar + panel only). Never show
  a modal from an automatic trigger.
- **After a failed fix**, call `trigger_relint(view)` so the syntax error is
  highlighted immediately.
- **Output panel**: always write through `write_panel` / `get_output_panel`, which
  destroy and recreate the panel so output does not accumulate across runs.
- **Executables**: resolve via `find_executable`, which falls back to common
  install paths because macOS GUI apps don't inherit the shell `PATH`.
- **Command names** are derived from class names (`YamllintFooCommand` →
  `yamllint_foo`). Renaming a class means updating the commands file, both menus,
  all three keymaps and the README.

## Adding or Changing a Setting

A new setting touches all of these — keep them in sync:
1. Default value + comment in `yamllint.sublime-settings`
2. `settings.get("key", <same default>)` in `yamllint.py` (repeat the default)
3. Row in the README settings table, plus a section if the behavior needs explaining

## Development Workflow

- The package folder **must be named `YamlLint`**: menus and the settings command
  reference `${packages}/YamlLint/yamllint.sublime-settings`.
- Installed copy: `~/Library/Application Support/Sublime Text/Packages/YamlLint`.
  It is a plain copy, not a symlink — edits in this repo are not live until synced:
  ```bash
  rsync -a --delete --exclude .git --exclude CLAUDE.md --exclude tests ./ ~/Library/Application\ Support/Sublime\ Text/Packages/YamlLint/
  ```
  Sublime then reloads `yamllint.py` automatically.
- Tests for the pure text logic live in `tests/` (stdlib `unittest`, Sublime API
  stubbed): `python3 -m unittest discover tests`. Add a case there when changing
  `add_top_level_spacing`, `PARSABLE_RE` or the tab handling. Keep tests out of
  the package root — Sublime loads every top-level `.py` as a plugin.
- `yamllint` and `yamlfix` are installed in `~/.local/bin` for CLI testing.

## Git

- Conventional commit prefixes (`feat:`, `fix:`, `docs:`, …), short and imperative.
- Commit only when asked.
