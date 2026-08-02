# Contributing to Twin

Thanks for helping improve Twin. This project is a personal cognitive OS —
local-first understanding, memory, judgment and context for a single user.

## Development setup

```bash
git clone https://github.com/caribeedu/twin.git
cd twin
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
twin init --skip-setup      # create ~/.twin defaults without the wizard
```

Install docs and provider wizard: [docs/SETUP.md](docs/SETUP.md).
How to operate Twin after install: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Tests

```bash
pytest -q
```

CI also runs connector and interpretation evals (see `.github/workflows/ci.yml`).
Prefer adding focused tests next to the behavior you change.

## Pull requests

1. Keep the change scoped — one concern per PR when practical.
2. Match existing style and module boundaries; avoid drive-by refactors.
3. Update docs only when the user-facing contract or install path changes.
4. Fill in the PR template (summary + test plan).
5. Ensure CI is green before merge.

By opening a PR you agree that your contribution is licensed under the
project [MIT License](LICENSE).

## Reporting issues

Use GitHub Issues with the bug or feature templates. For security-sensitive
reports, follow [SECURITY.md](SECURITY.md) instead of filing a public issue.

## Packaging note

The PyPI distribution is **`twin-cognition`**. The importable package and CLI
remain **`twin`**. End users install with:

```bash
pip install "twin-cognition[api,mcp,postgres,crypto]"
```
