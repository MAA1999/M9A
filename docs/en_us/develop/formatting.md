---
order: 11
icon: mdi:format-align-left
---
# Code Formatting

M9A uses a series of formatting tools to ensure that the code and resource files in the repository are clean and consistent, making them easier to maintain and read.

The repository automatically runs formatting daily, and you can also run formatting manually locally.

## Formatting Tools

| File Type | Formatting Tool |
| --- | --- |
| JSON/Yaml | [prettier](https://prettier.io/) |
| Markdown | [MarkdownLint](https://github.com/DavidAnson/markdownlint-cli2) |
| Python | [black](https://black.readthedocs.io/) |

## Install Dependencies

```bash
pnpm install          # Install Node.js dependencies (prettier, etc.)
pip install black     # Install Python formatting tool
```

## Manual Formatting

Run the following commands in the project root directory:

```bash
pnpm format:all
```

Or format separately:

```bash
pnpm format:json  # Format JSON/Yaml
pnpm format:py    # Format Python
```
