"""YAMLLint package for Sublime Text 4.

Lints *.yml / *.yaml files with `yamllint` and can auto-fix them with
`yamlfix`. See README.md for setup and yamllint.sublime-settings for
configuration options.
"""

import difflib
import fnmatch
import html
import os
import re
import shutil
import subprocess
import threading
import tempfile

import sublime
import sublime_plugin


SETTINGS_FILE = "yamllint.sublime-settings"
OUTPUT_PANEL_NAME = "yamllint"
REGION_ERROR_KEY = "yamllint-errors"
REGION_WARNING_KEY = "yamllint-warnings"
PHANTOM_SET_KEY = "yamllint"

# yamllint "parsable" format: file:line:col: [level] message (rule)
PARSABLE_RE = re.compile(
    r'^(?P<file>.*?):(?P<line>\d+):(?P<col>\d+):\s*'
    r'\[(?P<level>error|warning)\]\s*'
    r'(?P<message>.*?)(?:\s*\((?P<rule>[\w-]+)\))?$'
)

# Per-view state, keyed by view id.
_view_issues = {}
_phantom_sets = {}
_modify_timers = {}
_skip_next_fix_on_save = set()

DOC_MARKER_RE = re.compile(r'^(---|\.\.\.)\s*(#.*)?$')


def add_top_level_spacing(text):
    """yamlfix strips every blank line in the document, including the
    ones separating top-level entries (e.g. between plays in a
    playbook). This reinserts exactly one blank line before each
    top-level line (column 0) that immediately follows nested content —
    the only place blank-line intent survives a rewrite unambiguously.

    It only fires on a nested-to-column-0 transition, so a run of
    column-0 lines (a leading comment followed by the item it
    describes, or a genuinely flat top-level mapping with no nesting)
    is left untouched, and document markers (---/...) never get a
    blank line forced in front of them.
    """
    lines = text.split("\n")
    out = []
    started = False
    prev_indented = False
    for line in lines:
        is_blank = line.strip() == ""
        is_top_level = (not is_blank) and not line[:1].isspace()
        is_marker = bool(DOC_MARKER_RE.match(line))

        if is_top_level and not is_marker and started and prev_indented:
            if out and out[-1].strip() != "":
                out.append("")

        out.append(line)

        if not is_blank:
            started = True
            prev_indented = line[:1].isspace()

    return "\n".join(out)


def get_settings():
    return sublime.load_settings(SETTINGS_FILE)


def is_yaml_view(view):
    settings = get_settings()
    file_name = view.file_name() or ""
    patterns = settings.get("file_patterns", ["*.yml", "*.yaml"])
    if file_name:
        base = os.path.basename(file_name)
        if any(fnmatch.fnmatch(base, p) for p in patterns):
            return True
    syntax = view.settings().get("syntax", "") or ""
    return "YAML" in syntax


def find_executable(name, configured_path):
    if configured_path:
        expanded = os.path.expanduser(configured_path)
        if os.path.isfile(expanded):
            return expanded

    found = shutil.which(name)
    if found:
        return found

    # GUI apps on macOS/Linux often don't inherit the shell's PATH, so also
    # probe a handful of common install locations before giving up.
    home = os.path.expanduser("~")
    candidates = [
        "/usr/local/bin/" + name,
        "/opt/homebrew/bin/" + name,
        "/usr/bin/" + name,
        os.path.join(home, ".local", "bin", name),
        os.path.join(home, ".pyenv", "shims", name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def run_process(cmd, cwd=None, input_text=None):
    startupinfo = None
    if sublime.platform() == "windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=startupinfo,
        env=os.environ.copy(),
    )
    data = input_text.encode("utf-8") if input_text is not None else None
    stdout, stderr = proc.communicate(input=data)
    return (
        proc.returncode,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


# sublime.error_message() renders a fixed-size modal that can't be resized
# or scrolled; a long message (e.g. a full Python traceback from yamlfix)
# can grow taller than the screen with its OK button unreachable. Long
# messages go to the output panel instead, with only a short pointer shown
# in the dialog.
MAX_DIALOG_CHARS = 600


def get_output_panel(window):
    """(Re-)creates the yamllint output panel so callers can write fresh
    content into it — create_output_panel() returns the *same* panel across
    calls, so without destroying it first every run would just append to
    whatever the previous run already printed."""
    window.destroy_output_panel(OUTPUT_PANEL_NAME)
    panel = window.create_output_panel(OUTPUT_PANEL_NAME)
    panel.settings().set("result_file_regex", r'^(.+):(\d+):(\d+): ')
    return panel


def write_panel(window, text):
    panel = get_output_panel(window)
    panel.set_read_only(False)
    panel.run_command("append", {"characters": text.rstrip("\n") + "\n"})
    panel.set_read_only(True)


def report_error(view, message):
    """Shows a (possibly truncated) modal dialog for an explicit, user-
    triggered action, with full detail always available in the panel."""
    def show():
        window = view.window()
        if window:
            write_panel(window, message)
        if len(message) > MAX_DIALOG_CHARS:
            if window:
                window.run_command("show_panel", {"panel": "output.{}".format(OUTPUT_PANEL_NAME)})
            dialog_text = (
                message[:MAX_DIALOG_CHARS].rstrip()
                + "\n\n… truncated — full details are in the 'yamllint' output panel."
            )
        else:
            dialog_text = message
        sublime.error_message(dialog_text)

    sublime.set_timeout(show, 0)


def trigger_relint(view):
    """Re-runs the linter so the buffer's current state (including a
    syntax error yamlfix just choked on) gets highlighted right away,
    instead of waiting for the next save/edit to refresh it."""
    sublime.set_timeout(lambda: view.run_command("yamllint_lint", {"quiet": True}), 0)


def report_error_quiet(view, message):
    """Non-modal counterpart used for automatic triggers (e.g. fix on
    save): never interrupts with a dialog, just updates the status bar and
    writes full detail to the panel for when the user wants to look."""
    def show():
        window = view.window()
        if window:
            write_panel(window, message)
        view.set_status("yamllint", "YAMLLint: auto-fix failed — see 'yamllint' output panel")

    sublime.set_timeout(show, 0)


# ---------------------------------------------------------------------------
# Linting
# ---------------------------------------------------------------------------

class YamllintLintCommand(sublime_plugin.TextCommand):
    """Lints the current view's content with yamllint."""

    def run(self, edit, quiet=False):
        threading.Thread(target=self.lint_async, args=(quiet,)).start()

    def lint_async(self, quiet):
        view = self.view
        settings = get_settings()
        exe = find_executable("yamllint", settings.get("yamllint_path", ""))
        if not exe:
            if not quiet:
                report_error(
                    view,
                    "YAMLLint: 'yamllint' executable not found.\n\n"
                    "Install it with:\n    pip install yamllint\n\n"
                    "or set \"yamllint_path\" in Preferences > Package "
                    "Settings > YAMLLint > Settings."
                )
            return

        content = view.substr(sublime.Region(0, view.size()))
        file_name = view.file_name()
        cwd = os.path.dirname(file_name) if file_name else None

        cmd = [exe, "-f", "parsable"]
        config_file = settings.get("config_file", "")
        config_data = settings.get("config_data", "")
        if config_file:
            cmd += ["-c", os.path.expanduser(config_file)]
        elif config_data:
            cmd += ["-d", config_data]
        cmd += list(settings.get("extra_args", []))
        cmd += ["-"]

        try:
            code, stdout, stderr = run_process(cmd, cwd=cwd, input_text=content)
        except Exception as exc:
            if not quiet:
                report_error(view, "YAMLLint: failed to run yamllint:\n{}".format(exc))
            return

        # yamllint exits 0 (clean), 1 (issues found) or 2 (usage/config error).
        if code not in (0, 1):
            if not quiet:
                report_error(
                    view,
                    "yamllint reported an error (exit {}):\n\n{}".format(
                        code, stderr.strip() or stdout.strip()
                    )
                )
            return

        issues = []
        for line in stdout.splitlines():
            match = PARSABLE_RE.match(line.strip())
            if not match:
                continue
            issues.append({
                "line": int(match.group("line")),
                "col": int(match.group("col")),
                "level": match.group("level"),
                "message": match.group("message").strip(),
                "rule": match.group("rule") or "",
            })

        sublime.set_timeout(lambda: apply_lint_results(view, issues, stderr), 0)


def apply_lint_results(view, issues, stderr):
    _view_issues[view.id()] = issues
    settings = get_settings()

    draw_marks(view, issues, settings)
    update_panel(view, issues, stderr)

    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warning")
    if issues:
        view.set_status("yamllint", "YAMLLint: {} error(s), {} warning(s)".format(errors, warnings))
    else:
        view.set_status("yamllint", "YAMLLint: OK")

    window = view.window()
    if issues and window and settings.get("show_panel_on_issues", False):
        window.run_command("show_panel", {"panel": "output.{}".format(OUTPUT_PANEL_NAME)})


def draw_marks(view, issues, settings):
    view.erase_regions(REGION_ERROR_KEY)
    view.erase_regions(REGION_WARNING_KEY)

    error_regions = []
    warning_regions = []

    for issue in issues:
        line_no = max(issue["line"] - 1, 0)
        try:
            line_region = view.line(view.text_point(line_no, 0))
        except Exception:
            continue
        col = max(issue["col"] - 1, 0)
        start = min(line_region.begin() + col, line_region.end())
        end = min(start + 1, line_region.end())
        region = sublime.Region(start, end) if end > start else line_region

        if issue["level"] == "error":
            error_regions.append(region)
        else:
            warning_regions.append(region)

    show_icons = settings.get("show_gutter_icons", True)
    icon_error = "circle" if show_icons else ""
    icon_warning = "dot" if show_icons else ""
    flags = sublime.DRAW_NO_FILL | sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_OUTLINE

    if error_regions:
        view.add_regions(
            REGION_ERROR_KEY, error_regions,
            "region.redish markup.error.yamllint", icon_error, flags
        )
    if warning_regions:
        view.add_regions(
            REGION_WARNING_KEY, warning_regions,
            "region.yellowish markup.warning.yamllint", icon_warning, flags
        )

    if settings.get("show_phantoms", True):
        draw_phantoms(view, issues)
    else:
        clear_phantoms(view)


def get_phantom_set(view):
    vid = view.id()
    if vid not in _phantom_sets:
        _phantom_sets[vid] = sublime.PhantomSet(view, PHANTOM_SET_KEY)
    return _phantom_sets[vid]


def clear_phantoms(view):
    get_phantom_set(view).update([])


PHANTOM_TEMPLATE = """
<body id="yamllint-phantom">
    <style>
        div.yamllint-{level} {{
            padding: 2px 8px;
            margin: 2px 0;
            border-radius: 3px;
            background-color: color(var(--background) blend(var(--{color}) 85%));
            color: var(--{color});
            font-size: 0.9rem;
        }}
    </style>
    <div class="yamllint-{level}">{icon} {message} <i>({rule})</i></div>
</body>
"""


def draw_phantoms(view, issues):
    phantom_set = get_phantom_set(view)
    phantoms = []
    for issue in issues:
        line_no = max(issue["line"] - 1, 0)
        try:
            line_region = view.line(view.text_point(line_no, 0))
        except Exception:
            continue
        is_error = issue["level"] == "error"
        body = PHANTOM_TEMPLATE.format(
            level=issue["level"],
            color="redish" if is_error else "yellowish",
            icon="✖" if is_error else "⚠",
            message=html.escape(issue["message"]),
            rule=html.escape(issue["rule"] or ""),
        )
        phantoms.append(sublime.Phantom(line_region, body, sublime.LAYOUT_BELOW))
    phantom_set.update(phantoms)


def update_panel(view, issues, stderr):
    window = view.window()
    if not window:
        return

    file_name = view.file_name() or "untitled"
    lines = []
    if issues:
        for issue in sorted(issues, key=lambda i: (i["line"], i["col"])):
            rule = " ({})".format(issue["rule"]) if issue["rule"] else ""
            lines.append("{}:{}:{}: [{}] {}{}".format(
                file_name, issue["line"], issue["col"], issue["level"], issue["message"], rule
            ))
    else:
        lines.append("{}: no issues found".format(file_name))

    if stderr.strip():
        lines.append("")
        lines.append("--- stderr ---")
        lines.append(stderr.strip())

    write_panel(window, "\n".join(lines))


class YamllintClearCommand(sublime_plugin.TextCommand):
    """Clears all yamllint markers/phantoms/status for the current view."""

    def run(self, edit):
        view = self.view
        view.erase_regions(REGION_ERROR_KEY)
        view.erase_regions(REGION_WARNING_KEY)
        clear_phantoms(view)
        view.erase_status("yamllint")
        _view_issues.pop(view.id(), None)
        window = view.window()
        if window:
            window.destroy_output_panel(OUTPUT_PANEL_NAME)


class YamllintShowPanelCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.window.run_command("show_panel", {"panel": "output.{}".format(OUTPUT_PANEL_NAME)})


class YamllintGotoNextIssueCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        goto_issue(self.view, forward=True)


class YamllintGotoPrevIssueCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        goto_issue(self.view, forward=False)


def goto_issue(view, forward=True):
    issues = _view_issues.get(view.id(), [])
    if not issues:
        sublime.status_message("YAMLLint: no issues")
        return

    sel = view.sel()[0] if len(view.sel()) else sublime.Region(0, 0)
    cur_row, _ = view.rowcol(sel.begin())
    rows = sorted(set(issue["line"] - 1 for issue in issues))

    if forward:
        candidates = [r for r in rows if r > cur_row]
        target = candidates[0] if candidates else rows[0]
    else:
        candidates = [r for r in rows if r < cur_row]
        target = candidates[-1] if candidates else rows[-1]

    pt = view.text_point(target, 0)
    view.sel().clear()
    view.sel().add(sublime.Region(pt))
    view.show_at_center(pt)


# ---------------------------------------------------------------------------
# Auto-fix (yamlfix)
# ---------------------------------------------------------------------------

class YamllintFixCommand(sublime_plugin.TextCommand):
    """Runs yamlfix on the current view's content and applies the result.

    With quiet=True (used by the fix_on_save auto-trigger) failures are
    reported via the status bar/output panel instead of a modal dialog, so
    saving a file that still has real syntax errors doesn't interrupt you
    with a popup on every keystroke-adjacent save.
    """

    def run(self, edit, quiet=False):
        threading.Thread(target=self.fix_async, args=(quiet,)).start()

    def fix_async(self, quiet=False):
        view = self.view
        report = report_error_quiet if quiet else report_error
        settings = get_settings()
        exe = find_executable("yamlfix", settings.get("yamlfix_path", ""))
        if not exe:
            report(
                view,
                "YAMLLint: 'yamlfix' executable not found.\n\n"
                "Install it with:\n    pip install yamlfix\n\n"
                "or set \"yamlfix_path\" in Preferences > Package Settings "
                "> YAMLLint > Settings."
            )
            trigger_relint(view)
            return

        original_content = view.substr(sublime.Region(0, view.size()))
        original_file = view.file_name()
        suffix = os.path.splitext(original_file)[1] if original_file else ".yaml"
        suffix = suffix or ".yaml"

        # Raw tab characters make YAML unparsable (they're only valid as
        # content, never as indentation), so yamlfix/yamllint reject them
        # with a syntax error before any style rule ever gets a chance to
        # run. This is the single most common reason "fix" appears to do
        # nothing, so normalize tabs to spaces first unless disabled.
        content = original_content
        if settings.get("yamlfix_expand_tabs", True) and "\t" in content:
            tab_width = int(settings.get("yamlfix_tab_width", 2))
            content = content.expandtabs(tab_width)

        tmp_dir = tempfile.mkdtemp(prefix="sublime-yamllint-")
        tmp_path = os.path.join(tmp_dir, "buffer" + suffix)

        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            cmd = [exe]
            config_file = settings.get("yamlfix_config_file", "") or settings.get("config_file", "")
            if config_file:
                cmd += ["--config-file", os.path.expanduser(config_file)]
            cmd += list(settings.get("yamlfix_extra_args", []))
            cmd += [tmp_path]

            cwd = os.path.dirname(original_file) if original_file else tmp_dir
            code, stdout, stderr = run_process(cmd, cwd=cwd)

            if code != 0:
                report(
                    view,
                    "yamlfix failed (exit {}):\n\n{}\n\n"
                    "Note: yamlfix can only fix formatting/style issues. "
                    "Structural problems (invalid YAML syntax, duplicate "
                    "keys, etc.) must be corrected by hand first. The "
                    "'yamllint' highlights below show everything it could "
                    "still detect, syntax error included.".format(
                        code, stderr.strip() or stdout.strip()
                    )
                )
                trigger_relint(view)
                return

            with open(tmp_path, "r", encoding="utf-8") as fh:
                fixed = fh.read()
        except Exception as exc:
            report(view, "YAMLLint: failed to run yamlfix:\n{}".format(exc))
            trigger_relint(view)
            return
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if settings.get("yamlfix_restore_top_level_spacing", False):
            fixed = add_top_level_spacing(fixed)

        if fixed == original_content:
            if not quiet:
                sublime.set_timeout(lambda: sublime.status_message("YAMLLint: already formatted, no changes"), 0)
            return

        sublime.set_timeout(lambda: self.apply_fix(fixed, quiet), 0)

    def apply_fix(self, fixed_content, quiet=False):
        view = self.view
        view.run_command("yamllint_replace_content", {"text": fixed_content})
        view.run_command("yamllint_lint", {"quiet": True})
        if not quiet:
            sublime.status_message("YAMLLint: file fixed")
            return

        # Triggered from on_post_save_async: the file on disk still has the
        # pre-fix content, so persist the fix too. This save re-enters
        # on_post_save_async; _skip_next_fix_on_save prevents a second,
        # redundant yamlfix run (the content is already fixed by then).
        if view.file_name() and view.is_dirty():
            _skip_next_fix_on_save.add(view.id())
            view.set_status("yamllint", "YAMLLint: auto-fixed on save")
            view.run_command("save")


class YamllintReplaceContentCommand(sublime_plugin.TextCommand):
    """Replaces the buffer content with `text`, touching only changed line
    ranges so undo history and cursor position stay reasonable."""

    def run(self, edit, text):
        view = self.view
        old_lines = view.substr(sublime.Region(0, view.size())).splitlines(keepends=True)
        new_lines = text.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

        def line_offset(lines, idx):
            return sum(len(l) for l in lines[:idx])

        delta = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            start = line_offset(old_lines, i1) + delta
            end = line_offset(old_lines, i2) + delta
            replacement = "".join(new_lines[j1:j2])
            view.replace(edit, sublime.Region(start, end), replacement)
            delta += len(replacement) - (end - start)


# ---------------------------------------------------------------------------
# Automatic linting (save / load / modify)
# ---------------------------------------------------------------------------

class YamllintEventListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        settings = get_settings()
        if settings.get("lint_on_load", True) and is_yaml_view(view):
            view.run_command("yamllint_lint", {"quiet": True})

    def on_post_save_async(self, view):
        settings = get_settings()
        if not is_yaml_view(view):
            return

        if settings.get("lint_on_save", True):
            view.run_command("yamllint_lint", {"quiet": True})

        if settings.get("fix_on_save", False):
            vid = view.id()
            if vid in _skip_next_fix_on_save:
                # This save was triggered by our own apply_fix() persisting
                # a previous auto-fix; the content is already fixed, so
                # don't run yamlfix (and re-save) again for no reason.
                _skip_next_fix_on_save.discard(vid)
                return
            view.run_command("yamllint_fix", {"quiet": True})

    def on_modified_async(self, view):
        settings = get_settings()
        if not settings.get("lint_on_modify", False) or not is_yaml_view(view):
            return

        vid = view.id()
        timer = _modify_timers.get(vid)
        if timer:
            timer.cancel()

        delay = settings.get("lint_on_modify_delay", 800) / 1000.0

        def fire():
            sublime.set_timeout(lambda: view.run_command("yamllint_lint", {"quiet": True}), 0)

        t = threading.Timer(delay, fire)
        t.daemon = True
        _modify_timers[vid] = t
        t.start()

    def on_close(self, view):
        vid = view.id()
        _view_issues.pop(vid, None)
        _phantom_sets.pop(vid, None)
        _skip_next_fix_on_save.discard(vid)
        timer = _modify_timers.pop(vid, None)
        if timer:
            timer.cancel()
