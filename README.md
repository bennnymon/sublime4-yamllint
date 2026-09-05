# YAMLLint for Sublime Text 4

Lint `*.yml` / `*.yaml` files against [yamllint](https://yamllint.readthedocs.io/)
standards directly in Sublime Text — inline error/warning underlines, gutter
icons, an output panel, and one-command auto-fixing via
[yamlfix](https://lyz-code.github.io/yamlfix/).

## Features

- Lints on load and on save (configurable), plus an on-demand command.
- Inline squiggly underlines + gutter icons for errors/warnings, with
  optional phantom messages shown right below the offending line.
- Output panel listing every issue, click-to-jump to `file:line:col`.
- "Go to Next/Previous Issue" navigation commands.
- One-shot auto-fix of the current buffer via `yamlfix`, re-linted
  automatically afterwards.
- Fully configurable: custom `yamllint`/`yamlfix` executable paths, config
  file, inline config overrides, extra CLI args, debounced lint-on-type.

## Requirements

Python 3 with `yamllint` (and, for auto-fix, `yamlfix`) installed:

```bash
pip install yamllint yamlfix
```

Verify they're on your `PATH`:

```bash
yamllint --version
yamlfix --version
```

> **macOS note:** GUI apps (including Sublime Text) often don't inherit your
> shell's `PATH`, so the package may not find `yamllint`/`yamlfix` even
> though they work in a terminal. If you see an "executable not found"
> error, run `which yamllint` / `which yamlfix` in a terminal and paste the
> resulting path into `yamllint_path` / `yamlfix_path` in the package
> settings (see below).

## Installation

This package is not (yet) on Package Control. Install it manually:

1. In Sublime Text: **Preferences > Browse Packages…** — this opens your
   `Packages` folder.
2. Copy this `YamlLint` folder into that `Packages` folder (or into
   `Packages/User/YamlLint`).
3. Restart Sublime Text, or run **Preferences: Reload Plugins** from the
   Command Palette.

## Usage

Open any `.yml`/`.yaml` file — it's linted automatically. Issues are shown
inline and listed in the `yamllint` output panel.

**Command Palette** (`Cmd/Ctrl+Shift+P`):

- `YAMLLint: Lint Current File`
- `YAMLLint: Fix Current File (yamlfix)`
- `YAMLLint: Clear Results`
- `YAMLLint: Show Output Panel`
- `YAMLLint: Go to Next Issue` / `Go to Previous Issue`
- `Preferences: YAMLLint Settings`

**Menu:** `Tools > YAMLLint`

**Keybindings:**

| Action        | macOS              | Windows/Linux        |
|---------------|---------------------|-----------------------|
| Lint file     | `Cmd+Alt+Y`         | `Ctrl+Alt+Y`          |
| Fix file      | `Cmd+Alt+Shift+Y`   | `Ctrl+Alt+Shift+Y`    |

Keybindings live in a `.sublime-keymap` file, **not** in
`yamllint.sublime-settings` — Sublime Text keeps commands and their
shortcuts in separate files by design. To rebind them, open
`Preferences > Key Bindings` (this opens `Default (User).sublime-keymap`,
plus this package's defaults for reference on the right) and add entries
for the `yamllint_lint` and `yamllint_fix` commands, e.g.:

```json
[
    {
        "keys": ["ctrl+shift+l"],
        "command": "yamllint_lint",
        "context": [{ "key": "selector", "operator": "equal", "operand": "source.yaml" }]
    },
    {
        "keys": ["ctrl+shift+f"],
        "command": "yamllint_fix",
        "context": [{ "key": "selector", "operator": "equal", "operand": "source.yaml" }]
    }
]
```

The `context` block is optional but recommended — it keeps the shortcut
scoped to YAML files instead of overriding it everywhere. Other commands
this package exposes, in case you want to bind those too:
`yamllint_clear`, `yamllint_show_panel`, `yamllint_goto_next_issue`,
`yamllint_goto_prev_issue`.

## Configuration

Open **Preferences > Package Settings > YAMLLint > Settings** (or the
Command Palette entry `Preferences: YAMLLint Settings`) to edit your user
overrides. Available keys (see `yamllint.sublime-settings` for defaults and
inline docs):

| Setting | Description |
|---|---|
| `yamllint_path` | Explicit path to the `yamllint` executable. |
| `yamlfix_path` | Explicit path to the `yamlfix` executable. |
| `config_file` | Path to a yamllint config (`.yamllint.yml` etc.), passed to both yamllint and yamlfix. Leave empty for yamllint's own auto-discovery. |
| `config_data` | Inline yamllint config overrides (`-d`), used when `config_file` is empty. |
| `extra_args` | Extra CLI args appended to the `yamllint` call. |
| `yamlfix_config_file` | Config file used only for the fix command (overrides `config_file`). |
| `yamlfix_extra_args` | Extra CLI args appended to the `yamlfix` call. |
| `yamlfix_expand_tabs` / `yamlfix_tab_width` | Convert tabs to spaces before fixing (default `true` / `2`) — raw tabs make YAML unparsable. |
| `fix_on_save` | Run yamlfix automatically on save and re-save the result (default `false`). See below. |
| `lint_on_save` | Lint automatically on save (default `true`). |
| `lint_on_load` | Lint automatically on open (default `true`). |
| `lint_on_modify` | Lint while typing, debounced (default `false`). |
| `lint_on_modify_delay` | Debounce delay in ms for `lint_on_modify`. |
| `show_phantoms` | Show inline phantom messages (default `true`). |
| `show_gutter_icons` | Show gutter icons (default `true`). |
| `show_panel_on_issues` | Auto-open the output panel when issues are found. |
| `file_patterns` | Extra filename patterns treated as YAML. |

### Fixing automatically on save

Set `"fix_on_save": true` to have `yamlfix` run every time you save a YAML
file, rewriting the buffer and re-saving it so the file on disk ends up
fixed too — no separate "Fix Current File" needed. It's off by default
since it silently rewrites your file on every save; turn it on once you're
comfortable with what `yamlfix` does to your files (try it manually a few
times first via the Fix command).

This only covers what auto-fix has always covered — formatting/style
issues, plus the tab-to-space normalization described above. A file with
a genuine syntax error still saves normally; you just get a status bar
note ("auto-fix failed — see 'yamllint' output panel") instead of a
dialog, since a dialog on every save of a file you're actively fixing up
would get old fast. Manual `Fix Current File` still shows the full dialog,
since that's an explicit action where you want the feedback.

### Using a custom yamllint ruleset

Point at a project-specific config:

```json
{
    "config_file": "${project_path}/.yamllint.yml"
}
```

(Note: Sublime settings files don't expand `${project_path}` themselves —
use an absolute path, or rely on yamllint's automatic discovery of
`.yamllint`/`.yamllint.yaml`/`.yamllint.yml` next to the linted file, which
is the default behavior when `config_file` is empty.)

### Common tweak: raising the line-length limit

yamllint's `default` ruleset flags any line over 80 characters. To raise
that (e.g. to 200), either set it inline via `config_data`:

```json
{
    "config_data": "{extends: default, rules: {line-length: {max: 200}}}"
}
```

or point `config_file` at your own config:

```json
{
    "config_file": "/absolute/path/to/.yamllint.yml"
}
```

```yaml
# .yamllint.yml
extends: default
rules:
  line-length:
    max: 200
```

`config_data` is the quicker option for a single tweak like this;
`config_file` is worth it once you're customizing several rules, and it
doubles as the config used if you also run `yamllint` from the command
line or in CI.

## How linting works

The current buffer content (including unsaved changes) is piped into
`yamllint -f parsable -`, so you get feedback before you even save. Results
are parsed and rendered as regions/phantoms/panel entries.

## How auto-fix works

`yamlfix` doesn't support reliable stdin/stdout fixing across versions, so
the buffer content is written to a temp file with the same extension,
`yamlfix` is run on it in place, and the result is diffed back into your
buffer (only changed line ranges are touched, so undo stays sane). The
temp file is removed immediately afterwards. The file is then re-linted.

Before handing the content to `yamlfix`, raw tab characters are converted
to spaces (`yamlfix_expand_tabs` / `yamlfix_tab_width`, on by default) —
a tab breaks YAML parsing entirely and is the most common reason a fix
silently fails with a syntax error instead of applying.

### What auto-fix can and can't do

`yamlfix` only rewrites **formatting/style** issues it can unambiguously
resolve: spacing, quoting, flow vs. block style, trailing whitespace,
missing document start, indentation depth, and similar. It (deliberately)
cannot fix problems that require a judgment call or that make the file
impossible to parse in the first place, for example:

- Invalid/malformed YAML syntax beyond tabs (unmatched brackets, bad
  escapes, etc.) — the file has to parse before any fixer can touch it.
- Duplicate keys — which one should win is a semantic decision, not a
  formatting one.
- Anything `yamllint` flags that isn't backed by a corresponding `yamlfix`
  rule.

For these, the fix command reports the underlying error (with the full
detail in the `yamllint` output panel) so you can resolve it by hand, then
re-run the fix.

Why not fix everything else and just skip the broken part? Because a YAML
parser needs the *whole* document to form one valid tree before it can
rewrite anything — a real syntax error aborts that parse entirely, so
there's no "everything else" left for `yamlfix` to touch, even in an
otherwise-unrelated part of the file. This holds for any YAML formatter,
not just `yamlfix`. What the fix command does instead: on failure, it
immediately re-runs `yamllint` on the buffer and refreshes the inline
highlights, since yamllint's checks are more tolerant (many run at the
tokenizer level and don't need a full successful parse) — so you
typically see the exact syntax error location highlighted alongside any
other detected issues right away, without needing another save or edit.

## Uninstalling

Delete the `YamlLint` folder from your Sublime `Packages` directory.

## License

MIT — do whatever you like with it.
