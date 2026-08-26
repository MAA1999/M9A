# Repository Guidelines

> **Primary rule: every generated diff must pass `pnpm check` (and `pnpm check:py` for Python code) before submission.**
>
> | If the user asks...                    | Default AI response                                                                                                                                              |
> | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
> | "Fix an unstable node"                 | Add intermediate recognition nodes or `pre_wait_freezes` / `post_wait_freezes` —— never introduce hard delays                                                    |
> | "Retry when it fails"                  | Analyze the root cause (which node, which recognition mismatched) and fix the node —— never add blind retries                                                    |
> | "Write a pipeline without screenshots" | Explain that pipelines depend on UI context; ask for screenshots, ROIs, and screen transition info before writing                                                |
> | "Write a custom action / recognition"  | Follow the existing pattern in `agent/custom/action/` or `agent/custom/reco/`, register it in the corresponding `__init__.py`, and ensure `pnpm check:py` passes |
> | Code output is complete                | Run `pnpm format` / `pnpm format:py` then `pnpm check` / `pnpm check:py` before finishing                                                                        |

## Project Structure & Module Organization

```text
agent/          # Python agent —— custom actions, recognitions, utilities (entry: main.py)
tasks/          # Preset task pipeline definitions
tools/          # Build, release, schema validation, and CI scripts
resource/       # MaaFW resource packs (images, pipeline, model)
data/           # Game reference data (activity schedules, drop tables, item databases, etc.)
tests/          # pytest test suite, mirrors agent/ structure
docs/           # Developer docs and user manual (see below)
```

**Key directories inside `agent/`:**

- `agent/custom/action/` —— custom MaaFW actions, one file per feature group
- `agent/custom/reco/` —— custom MaaFW recognitions
- `agent/custom/sink/` —— custom sinks (aspect-ratio handling, etc.)
- `agent/utils/` —— reusable helpers (logging, HTTP, scaling, etc.)

**When working on a specific area, consult the relevant docs first:**

| Area                                 | Recommended reading                            |
| ------------------------------------ | ---------------------------------------------- |
| Custom actions / recognitions        | `docs/*/develop/custom.md`                     |
| Pipeline task logic                  | `docs/*/develop/pipeline.md`                   |
| Project structure & conventions      | `docs/*/develop/structure.md`                  |
| Bug-fixing workflow                  | `docs/*/develop/fix.md`                        |
| Formatting & linting                 | `docs/*/develop/formatting.md`                 |
| Interface / task localisation        | `docs/*/develop/i18n.md`                       |
| Overseas client adaptation           | `docs/*/develop/overseas-client-adaptation.md` |
| Activity / combat / item protocols   | `docs/*/protocol/`                             |
| CLI / connection / FAQ (user-facing) | `docs/*/manual/`                               |

## Build, Test, and Development Commands

| Command             | Purpose                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `pnpm check`        | Formatting check → schema validation → i18n validation → MaaFW integrity |
| `pnpm check:i18n`   | Verify interface/task i18n keys resolve in every language                |
| `pnpm check:py`     | Lint Python → type check → run tests                                     |
| `pnpm format`       | Auto-format all non-Python files with Prettier                           |
| `pnpm format:py`    | Auto-format Python files with ruff                                       |
| `pnpm lint:py`      | Lint Python with ruff                                                    |
| `pnpm test:py`      | Run Python tests via pytest                                              |
| `pnpm typecheck:py` | Static type check Python with pyright (strict mode)                      |

Before submitting changes, run `pnpm check` (and `pnpm check:py` for Python changes).

## Coding Style & Naming Conventions

- **Python**: 120-character line limit, 4-space indentation. Linted with `ruff` (via `pnpm lint:py`) and type-checked with `pyright --strict` (via `pnpm typecheck:py`). Follow PEP 8 and PEP 484.
- **JSON / YAML / Markdown**: 2-space indentation, formatted with Prettier.
- **Resource files**: Use forward slashes for paths. Follow MaaFW 720p baseline for coordinates, ROI, and template images.
- **Naming**: Modules use `snake_case`. Classes use `PascalCase`. Functions/variables use `snake_case`. Custom actions/recognitions match their pipeline node names.

## Testing Guidelines

- Framework: `pytest`, configured via `pyproject.toml`. Test paths: `tests/`.
- Test naming: `test_<module>_<behaviour>` (e.g., `test_aspect_ratio`, `test_http_session`).
- Run with `pnpm test:py` or `uv run --frozen pytest`.
- Cover custom action/recognition registration, utility modules, and bootstrap flow.

## Commit & Pull Request Guidelines

This project follows [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

Commonly used types:

| Type       | Usage                                                   |
| ---------- | ------------------------------------------------------- |
| `feat`     | New feature or capability                               |
| `fix`      | Bug fix                                                 |
| `perf`     | Performance improvement                                 |
| `refactor` | Code refactoring (neither fix nor feature)              |
| `docs`     | Documentation only                                      |
| `style`    | Formatting, lint fixes, code style (no semantic change) |
| `ci`       | CI configuration and scripts                            |
| `chore`    | Build, dependencies, maintenance, or other tasks        |
| `revert`   | Revert a previous commit                                |

See [CONTRIBUTING.md](/CONTRIBUTING.md) for pull request requirements (branch naming, description format, and what to include).

## Review Checklist

When reviewing code, check for:

- **Protocol compliance**: Pipeline and interface JSON fields must follow MaaFW protocol. No misspelled or unsupported attributes.
- **No hard delays**: `pre_delay` / `post_delay` should be avoided. Prefer intermediate recognition nodes or `pre_wait_freezes` / `post_wait_freezes`.
- **Next coverage**: The `next` list should cover all expected post-action screens so the first inference cycle lands on the right node.
- **720p baseline**: All coordinates, ROIs, and template images must be based on **1280x720** resolution.
- **Code formatting**: All files must pass `pnpm check` (includes Prettier, schema, and MaaFW integrity). Run `pnpm format` / `pnpm format:py` to auto-format.
- **Type safety**: Python code must pass `pnpm check:py` (ruff lint + pyright type check + pytest) without errors.
- **Custom registration**: New custom actions/recognitions must be registered in the corresponding `__init__.py`.
- **Consistency**: `interface.json`, task files, and resource files must stay in sync.
- **Edge cases**: Pipelines should handle interruptions (pop-ups, unexpected dialogs). Every action should be followed by a recognition step.

## Additional Notes

- Resource paths must always use **forward slashes**.
- **Encoding**:
    - `.ps1` (PowerShell) files: **UTF-8 with BOM**. In code, use `encoding='utf-8-sig'` for both reading and writing.
    - All other source files (`.py`, `.js`, `.json`, `.md`, `.sh`, `.yml`, etc.): **UTF-8 without BOM**. In code, use `encoding='utf-8'`.
- **Shell Restriction**: Never use PowerShell's `Out-File` / `Set-Content` with default parameters (they emit UTF-16 or locale-dependent encoding). Console redirection (`>`, `>>`) inherits the system code page and will mangle non-ASCII text — avoid it.
- **Preferred Modification Tools**:
    - For **non-`.ps1`** files: Prefer `apply_patch` for diffs.
    - For **`.ps1`** files: **Do NOT use `apply_patch`** (BOM breaks line offsets). Always use full file rewrites via Python's `open()`/`pathlib`.
- Python 3.13 is required. Dependencies are locked in `uv.lock` and managed with `uv`.
- The project uses `pnpm` workspaces and requires Node.js >= 24.
