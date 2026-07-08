---
order: 8
icon: mdi:format-align-left
---

# Code Formatting

M9A uses a series of formatting tools to ensure that the code and resource files in the repository are clean and consistent, making them easier to maintain and read.

CI checks code formatting automatically, and you can also run it manually locally.

## Formatting Tools

| File Type              | Formatting Tool                                |
| ---------------------- | ---------------------------------------------- |
| JSON / YAML / Markdown | [prettier](https://prettier.io/)               |
| Python                 | [ruff](https://docs.astral.sh/ruff/formatter/) |

## Install Dependencies

```bash
pnpm install          # Install Node.js dependencies (prettier, etc.)
```

ruff is included in the project's Python dev dependencies and will be available after running `uv sync`.

## Manual Formatting

Run the following commands in the project root directory:

```bash
pnpm format          # prettier format all files
pnpm format:py       # ruff format Python code
```

Or run ruff directly:

```bash
ruff check --fix .  # Lint and auto-fix Python issues
ruff format .       # Format Python code
```
