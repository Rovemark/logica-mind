# Contributing to Logica Mind

Thanks for your interest in improving Logica Mind. This guide covers how to set
up a development environment, run the test suite, build the dashboard, and open a
pull request.

## Development setup

Logica Mind targets Python 3.10+. The core library runs with the standard
library only; the development extras pull in the test runner and tooling.

```bash
# Clone and enter the repo, then:
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run the full suite (roughly 182 tests; it is fully offline and needs no API
keys — it uses the default SQLite store and the offline hashing embedder):

```bash
pytest -q
```

Please make sure the suite passes before opening a pull request.

## Building the dashboard

The web dashboard is a React/Vite/Tailwind app under `logica_mind/web/app`. The
**built output** under `logica_mind/web/dist` is committed to the repository and
CI gates on it: if you change anything in `logica_mind/web/app`, rebuild and
commit the regenerated `dist`, or CI will fail with a "dist is out of date"
error.

```bash
cd logica_mind/web/app
npm ci
npm run build
# commit the regenerated logica_mind/web/dist
```

## Branch and pull request conventions

- Branch off `main`. Use a short, descriptive branch name, e.g.
  `fix/recall-dedup` or `feat/redis-store`.
- Keep each pull request focused on a single change.
- Write a clear PR title and description; reference any related issue.
- Ensure `pytest -q` passes and, if you touched the dashboard, that the
  committed `dist` is rebuilt.
- Fill out the pull request template checklist.

## License of contributions

Logica Mind is released under the Apache License, Version 2.0. By submitting a
contribution, you agree that it is licensed under the same terms. As stated in
Section 5 of the Apache-2.0 license, any contribution you intentionally submit
for inclusion in the work is provided under the terms and conditions of the
Apache-2.0 license, without any additional terms or conditions.
