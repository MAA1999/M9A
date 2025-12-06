---
order: 2
icon: hugeicons:structure-01
---
# Project Structure

```bash
.
|-- .github/                      # GitHub configuration
|   |-- ISSUE_TEMPLATE/           # Issue templates
|   |-- workflows/                # GitHub Actions workflows
|   `-- cliff.toml                # Changelog generation configuration
|-- .vscode/                      # VSCode editor configuration
|   |-- extensions.json           # Recommended extensions list
|   `-- settings.json             # Project settings
|-- agent/                        # Agent module
|   |-- custom/                   # Custom recognition and tasks
|   |-- utils/                    # Utility functions
|   |-- __init__.py               # Module initialization
|   `-- main.py                   # Main entry point
|-- assets/                       # Resource files directory
|   |-- MaaCommonAssets/          # MAA common resources (submodule)
|   |-- resource/                 # Project resource files
|   `-- interface.json            # Interface configuration file
|-- docs/                         # Documentation directory
|   |-- en_us/                    # English documentation
|   |-- zh_cn/                    # Chinese documentation
|   `-- .markdownlint.yaml        # Markdown linting configuration
|-- tools/                        # Tool scripts directory
|   |-- ci/                       # Continuous integration scripts
|   |-- image/                    # Image processing tools
|   `-- V1_upgrade.py             # Pipeline version upgrade script
|-- .gitignore                    # Git ignore configuration
|-- .gitmodules                   # Git submodules configuration
|-- .pre-commit-config.yaml       # Pre-commit hooks configuration
|-- .prettierrc                   # Code formatting configuration
|-- LICENSE                       # License file
|-- README.md                     # Chinese documentation
|-- README_en.md                  # English documentation
|-- package-lock.json             # npm dependency lock file
|-- package.json                  # Node.js project configuration
`-- requirements.txt              # Python dependency list
```
