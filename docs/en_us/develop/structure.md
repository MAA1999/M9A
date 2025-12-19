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
|   |-- interface.json            # MaaFramework standardized project structure declaration
|   `-- interface_cli.json        # Command-line interface configuration
|-- deps/                         # MaaFramework dependency libraries, where schemas are stored
|-- docs/                         # Documentation directory
|   |-- en_us/                    # English documentation
|   |-- zh_cn/                    # Chinese documentation
|   `-- .markdownlint.yaml        # Markdown linting configuration
|-- tools/                        # Tool scripts directory
|   |-- activity_data/            # Activity data processing tools
|   |-- ci/                       # Continuous integration scripts
|   |-- image/                    # Drop item image processing tools
|   |-- OptimizeTemplates/        # Template image optimization tools
|   |-- registry/                 # PC registry related tools
|   |-- migrate_pipeline_v5.py    # Pipeline v5 migration script
|   |-- minify_json.py            # JSON minification tool
|   `-- V1_upgrade.py             # Pipeline version upgrade script
|-- .editorconfig                 # Editor configuration
|-- .gitattributes                # Git attributes configuration
|-- .gitignore                    # Git ignore configuration
|-- .gitmodules                   # Git submodules configuration
|-- .pre-commit-config.yaml       # Pre-commit hooks configuration
|-- .prettierrc                   # Code formatting configuration
|-- CONTACT                       # Contact information
|-- LICENSE                       # License file
|-- README.md                     # Chinese documentation
|-- README_en.md                  # English documentation
|-- package-lock.json             # npm dependency lock file
|-- package.json                  # Node.js project configuration
`-- requirements.txt              # Python dependency list
```
