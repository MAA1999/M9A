---
title: Development Docs
icon: ph:code-bold
index: false
dir:
    order: 2
---

# Development Docs

This section is for developers who want to contribute code to M9A or adapt it to new content. Start with "Getting started" to learn how M9A is built and how the repository is laid out, then move on to the writing guides or the engineering practices.

If you only want to tweak a bit of JSON or documentation and are not familiar with Git, begin with the pull request walkthrough in [Notes Before Development](development.md).

## Getting started

- [Notes Before Development](development.md) — the GitHub pull request flow, cloning the repository with its submodules, and setting up the Python development environment.
- [Project Structure](structure.md) — what each top-level directory is for, and where the release and packaging scripts live.

## Writing guides

- [Custom Module Writing Guide](custom.md) — registering custom modules through AgentServer to extend what a MaaFramework JSON flow can do.
- [Pipeline Writing Guide](pipeline.md) — the core MaaFramework concept: describing how an automated task runs, and how it recognises the screen, in JSON.
- [Interface Localisation](i18n.md) — how the project text in `interface.json` and `tasks/` is translated.

## Engineering practices

- [Code Formatting](formatting.md) — the formatting tools the repository uses, and how to run the checks locally and in CI.
- [Documentation Writing](doc.md) — the MarkdownLint rules for this site and how to use the VuePress containers.
- [Bug Troubleshooting](fix.md) — a general process for locating, analysing, and fixing bugs.
- [Foreign Server Adaptation](overseas-client-adaptation.md) — what has to be adapted for the global servers and the global PC client.
