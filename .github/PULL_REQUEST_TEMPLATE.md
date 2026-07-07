<!-- Thanks for contributing! Keep the diff focused — one logical change per PR. -->

## What & why

<!-- What does this change, and what problem does it solve? -->

## Checklist

- [ ] Tests pass: `./venv/bin/python -m unittest discover -s tests`
- [ ] Added/updated tests for new behavior (where it makes sense)
- [ ] For user-visible changes: bumped `VERSION` in `server.py` **and** added a `CHANGELOG.md` entry (SemVer)
- [ ] No new dependencies (backend: stdlib + `psutil`; frontend: none) and no build step
- [ ] `/api/stats` shape stays backward-compatible (or the change is documented)
- [ ] No TCC-protected paths touched on a hot path; filesystem access wrapped in `try/except`

## Notes for reviewers

<!-- Anything worth calling out: trade-offs, follow-ups, screenshots for UI changes. -->
