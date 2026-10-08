"""Tests for .github/scripts/bump_formula.py (the release → formula bump logic)."""
import importlib.util
import os
import tempfile
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "bump_formula", os.path.join(_HERE, ".github", "scripts", "bump_formula.py"))
bump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump)

SHA_OLD = "a" * 64
SHA_NEW = "b" * 64
FORMULA = f'''class MacSysdash < Formula
  url "https://github.com/acme/mac-sysdash/archive/refs/tags/v1.38.1.tar.gz"
  sha256 "{SHA_OLD}"

  resource "psutil" do
    url "https://files.pythonhosted.org/packages/aa/c6/psutil-7.2.2.tar.gz"
    sha256 "{"c" * 64}"
  end
end
'''


class BumpFormulaTests(unittest.TestCase):
    def test_rewrites_only_top_level_url_and_sha(self):
        out = bump.rewrite(FORMULA, "acme/mac-sysdash", "v1.39.0", SHA_NEW)
        changed = [(a, b) for a, b in zip(FORMULA.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(changed, [
            ('  url "https://github.com/acme/mac-sysdash/archive/refs/tags/v1.38.1.tar.gz"',
             '  url "https://github.com/acme/mac-sysdash/archive/refs/tags/v1.39.0.tar.gz"'),
            (f'  sha256 "{SHA_OLD}"', f'  sha256 "{SHA_NEW}"'),
        ])
        self.assertIn('sha256 "' + "c" * 64 + '"', out)        # psutil untouched

    def test_rewrite_is_idempotent(self):
        once = bump.rewrite(FORMULA, "acme/mac-sysdash", "v1.39.0", SHA_NEW)
        self.assertEqual(bump.rewrite(once, "acme/mac-sysdash", "v1.39.0", SHA_NEW), once)

    def test_needs_bump_only_for_strictly_newer(self):
        self.assertTrue(bump.needs_bump(FORMULA, "v1.39.0"))
        self.assertTrue(bump.needs_bump(FORMULA, "v1.38.10"))     # numeric, not lexical
        self.assertTrue(bump.needs_bump(FORMULA, "v2.0.0"))
        self.assertFalse(bump.needs_bump(FORMULA, "v1.38.1"))     # same
        self.assertFalse(bump.needs_bump(FORMULA, "v1.37.9"))     # older line: no downgrade
        self.assertFalse(bump.needs_bump(FORMULA, "v1.9.99"))

    def test_refuses_sha_before_url(self):
        lines = FORMULA.splitlines(True)
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaises(bump.FormulaError):
            bump.rewrite("".join(lines), "acme/mac-sysdash", "v1.39.0", SHA_NEW)

    def test_refuses_blank_line_between_url_and_sha(self):
        text = FORMULA.replace('.tar.gz"\n  sha256', '.tar.gz"\n\n  sha256', 1)
        with self.assertRaises(bump.FormulaError):
            bump.current_tag(text)

    def test_refuses_formula_whose_first_url_is_inside_a_resource(self):
        text = '  resource "x" do\n' + FORMULA
        with self.assertRaises(bump.FormulaError):
            bump.current_tag(text)

    def test_rejects_bad_inputs(self):
        for tag in ("v1.2", "1.2.3", "v1.2.3-rc1", "v1.2.3;rm -rf /"):
            with self.assertRaises(bump.FormulaError):
                bump.rewrite(FORMULA, "acme/mac-sysdash", tag, SHA_NEW)
        with self.assertRaises(bump.FormulaError):
            bump.rewrite(FORMULA, "acme/mac-sysdash", "v1.39.0", "")
        with self.assertRaises(bump.FormulaError):
            bump.rewrite(FORMULA, "acme/x y", "v1.39.0", SHA_NEW)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.rb")
            with open(path, "w", encoding="utf-8") as f:
                f.write(FORMULA)
            self.assertEqual(bump.main(["check", path, "v1.39.0"]), 0)
            self.assertEqual(bump.main(["check", path, "v1.38.1"]), bump.SKIP)
            self.assertEqual(bump.main(["check", path, "v1.37.0"]), bump.SKIP)
            self.assertEqual(bump.main(["check", path, "nope"]), bump.SKIP)
            self.assertEqual(bump.main(["check", path, "v1.40.0-rc1"]), bump.SKIP)
            with open(path, "w", encoding="utf-8") as f:     # a broken formula is an error
                f.write("class X < Formula\nend\n")
            self.assertEqual(bump.main(["check", path, "v1.39.0"]), 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(FORMULA)
            self.assertEqual(bump.main(["apply", path, "acme/mac-sysdash", "v1.39.0", SHA_NEW]), 0)
            self.assertEqual(bump.main(["check", path, "v1.39.0"]), bump.SKIP)
            self.assertEqual(bump.main(["bogus"]), 1)


if __name__ == "__main__":
    unittest.main()
