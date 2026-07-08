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
|   |-- cliff.toml                # Changelog generation configuration
|   |-- dependabot.yml            # Dependabot configuration
|   `-- PULL_REQUEST_TEMPLATE.md  # PR template
|-- .vscode/                      # VSCode editor configuration
|   |-- extensions.json           # Recommended extensions list
|   |-- launch.json               # Debug configuration
|   |-- settings.json             # Project settings
|   `-- tasks.json                # Task configuration
|-- agent/                        # Agent module
|   |-- custom/                   # Custom recognition and tasks
|   |-- utils/                    # Utility functions
|   |-- __init__.py               # Module initialization
|   |-- agent_runtime.py          # Agent server entry
|   |-- bootstrap.py              # Agent bootstrap & venv management
|   `-- main.py                   # Main entry point
|-- data/                         # Data
|-- docs/                         # Documentation directory
|   |-- en_us/                    # English documentation
|   |-- zh_cn/                    # Chinese documentation
|   `-- .markdownlint.yaml        # Markdown linting configuration
|-- MaaCommonAssets/              # MAA common resources (submodule)
|   `-- OCR/                      # OCR models
|-- resource/                     # Project pipelines & resources
|-- tasks/                        # Task pipeline definitions
|-- tests/                        # Tests
|-- tools/                        # Tool scripts directory
|   |-- activity_data/            # Activity data processing tools
|   |-- ci/                       # Continuous integration scripts
|   |-- registry/                 # PC registry tools
|   |-- schema/                   # Interface & pipeline schemas
|   |-- build-release.mjs         # Release package builder
|   |-- check-project.mjs         # Project validation
|   |-- configure.py              # OCR model configuration
|   |-- optimize-images.mjs       # Image optimization
|   |-- sync-runtime.mjs          # Runtime synchronisation
|   |-- sync-schema.mjs           # Schema synchronisation
|   `-- validate-schema.mjs       # Schema validation
|-- .editorconfig                 # Editor configuration
|-- .gitattributes                # Git attributes configuration
|-- .gitignore                    # Git ignore configuration
|-- .gitmodules                   # Git submodules configuration
|-- .node-version                 # Node.js version
|-- .prettierignore               # Prettier ignore configuration
|-- .prettierrc.mjs               # Code formatting configuration
|-- .python-version               # Python version
|-- CONTACT                       # Contact information
|-- CONTRIBUTING.md               # Contribution guide
|-- interface.json                # MaaFramework project interface declaration
|-- LICENSE                       # License file
|-- logo.ico                      # Application icon
|-- maa-project.json              # MAA project configuration
|-- maa-project.lock.json         # MAA project lock file
|-- maatools.config.mts           # MAA Tools configuration
|-- package.json                  # Node.js project configuration
|-- pnpm-lock.yaml                # pnpm dependency lock file
|-- pnpm-workspace.yaml           # pnpm workspace configuration
|-- pyproject.toml                # Python project configuration
|-- README.en.md                  # English documentation
|-- README.md                     # Chinese documentation
|-- requirements.txt              # Python dependency list
`-- uv.lock                       # uv lock file
```
