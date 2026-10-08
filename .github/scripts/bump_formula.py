#!/usr/bin/env python3
"""Point Formula/mac-sysdash.rb at a release tag — used by formula-bump.yml.

  bump_formula.py check FILE TAG [PENDING_TAG ...]
                                          exit 0: bump needed · 10: skip (not v<semver>, same or older
                                          than the pin or than a pending bump branch) · 1: error
  bump_formula.py apply FILE REPO TAG SHA rewrite the top-level url/sha256 in place

One parser for both questions, so "which version is pinned" and "which lines get
rewritten" can never disagree. Only the top-level url and the sha256 directly
under it are touched; anything else (a `resource` block, a reordered or blank-
separated pair) is refused rather than guessed at.
"""
import re
import sys

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_URL_RE = re.compile(
    r'^(?P<indent>\s*)url\s+"https://github\.com/[^/"]+/[^/"]+/archive/refs/tags/'
    r'(?P<tag>v[^"]+)\.tar\.gz"\s*$')
SKIP = 10


class FormulaError(ValueError):
    pass


def _parse_tag(tag):
    m = TAG_RE.match(tag or "")
    if not m:
        raise FormulaError(f"not a v<major>.<minor>.<patch> tag: {tag!r}")
    return tuple(int(x) for x in m.groups())


def _locate(lines):
    """Index of the top-level url line (before any resource block) and its indent."""
    for i, line in enumerate(lines):
        if re.match(r"^\s*resource\b", line):
            break
        m = _URL_RE.match(line)
        if m:
            sha = lines[i + 1] if i + 1 < len(lines) else ""
            if not re.match(r"^" + re.escape(m.group("indent")) + r'sha256\s+"[0-9a-fA-F]{64}"\s*$', sha):
                raise FormulaError("the top-level sha256 must directly follow url with the same indent")
            return i, m.group("indent"), m.group("tag")
    raise FormulaError("no top-level release url before the first resource block")


def current_tag(text):
    return _locate(text.splitlines(True))[2]


def needs_bump(text, tag, pending=()):
    """True only when `tag` is strictly newer than the pinned one and than every
    other pending bump (open chore/formula-v* branches): a late release for an older
    line must neither downgrade `brew upgrade` nor race a newer bump PR."""
    new = _parse_tag(tag)
    newer_pending = [p for p in pending if TAG_RE.match(p) and p != tag and _parse_tag(p) > new]
    return new > _parse_tag(current_tag(text)) and not newer_pending


def rewrite(text, repo, tag, sha):
    _parse_tag(tag)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha or ""):
        raise FormulaError(f"not a sha256: {sha!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise FormulaError(f"not an owner/repo: {repo!r}")
    lines = text.splitlines(True)
    i, indent, _ = _locate(lines)
    lines[i] = f'{indent}url "https://github.com/{repo}/archive/refs/tags/{tag}.tar.gz"\n'
    lines[i + 1] = f'{indent}sha256 "{sha}"\n'
    return "".join(lines)


def main(argv):
    try:
        if len(argv) >= 3 and argv[0] == "check":
            tag, pending = argv[2], argv[3:]
            if not TAG_RE.match(tag):
                # rc/beta/odd tags are not formula releases: skip, don't fail the job.
                print(f"skip: {tag!r} is not a v<major>.<minor>.<patch> tag")
                return SKIP
            with open(argv[1], encoding="utf-8") as f:
                text = f.read()
            if needs_bump(text, tag, pending):
                print(f"bump {current_tag(text)} -> {tag}")
                return 0
            print(f"skip: {tag} is not newer than the pinned {current_tag(text)}"
                  f" or a pending bump ({', '.join(pending) or 'none'})")
            return SKIP
        if len(argv) == 5 and argv[0] == "apply":
            path, repo, tag, sha = argv[1:]
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new = rewrite(text, repo, tag, sha)
            if new != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
            print(f"{path}: pinned {tag} ({sha})")
            return 0
    except (FormulaError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
