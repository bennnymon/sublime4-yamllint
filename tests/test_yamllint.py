"""Tests for the plugin's pure text logic. Run from the repo root:

    python3 -m unittest discover tests
"""

import os
import sys
import types
import unittest

# yamllint.py imports Sublime's API modules, which only exist inside
# Sublime Text; stub just enough of them to import the module.
sublime = types.ModuleType("sublime")
sublime_plugin = types.ModuleType("sublime_plugin")
for name in ("TextCommand", "WindowCommand", "EventListener"):
    setattr(sublime_plugin, name, type(name, (), {}))
sys.modules.setdefault("sublime", sublime)
sys.modules.setdefault("sublime_plugin", sublime_plugin)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yamllint  # noqa: E402


class AddTopLevelSpacingTest(unittest.TestCase):
    def check(self, before, after):
        self.assertEqual(yamllint.add_top_level_spacing(before), after)

    def test_separates_plays_in_a_playbook(self):
        self.check(
            "---\n- name: a\n  hosts: all\n- name: b\n  hosts: all\n",
            "---\n- name: a\n  hosts: all\n\n- name: b\n  hosts: all\n",
        )

    def test_separates_top_level_keys_after_nested_content(self):
        self.check("a:\n  x: 1\nb: 2\n", "a:\n  x: 1\n\nb: 2\n")

    def test_flat_mapping_untouched(self):
        self.check("a: 1\nb: 2\n", "a: 1\nb: 2\n")

    def test_comment_stays_with_following_item(self):
        self.check(
            "a:\n  x: 1\n# about b\nb: 2\n",
            "a:\n  x: 1\n\n# about b\nb: 2\n",
        )

    def test_no_blank_before_document_marker(self):
        self.check("a:\n  x: 1\n---\nb: 2\n", "a:\n  x: 1\n---\nb: 2\n")

    def test_indentless_list_under_key_not_split(self):
        text = "b:\n- name: x\n  v: 1\n- name: y\n  v: 2\nc: 1\n"
        self.check(text, "b:\n- name: x\n  v: 1\n- name: y\n  v: 2\n\nc: 1\n")

    def test_idempotent(self):
        once = yamllint.add_top_level_spacing("- a:\n    x: 1\n- b: 2\n")
        self.assertEqual(yamllint.add_top_level_spacing(once), once)


class LeadingTabsTest(unittest.TestCase):
    def expand(self, text):
        return yamllint.LEADING_WS_RE.sub(lambda m: m.group().expandtabs(2), text)

    def test_indentation_tabs_expanded(self):
        self.assertEqual(self.expand("a:\n\tb:\n\t\tc: 1\n"), "a:\n  b:\n    c: 1\n")

    def test_tab_inside_value_kept(self):
        self.assertEqual(self.expand('k: "a\tb"\n\tv: "x\ty"\n'), 'k: "a\tb"\n  v: "x\ty"\n')


class ParsableRegexTest(unittest.TestCase):
    def test_parses_line_with_rule(self):
        m = yamllint.PARSABLE_RE.match(
            'stdin:3:5: [error] wrong indentation: expected 2 but found 4 (indentation)'
        )
        self.assertEqual(
            (m["line"], m["col"], m["level"], m["rule"]),
            ("3", "5", "error", "indentation"),
        )
        self.assertEqual(m["message"], "wrong indentation: expected 2 but found 4")


if __name__ == "__main__":
    unittest.main()
