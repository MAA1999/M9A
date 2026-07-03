# Contributing to M9A

感谢你帮助改进 M9A。请让每次改动保持聚焦，清楚说明对用户可见行为的影响，并提供足够的验证信息，方便维护者 review。

Thanks for helping improve M9A. Keep each change focused, describe the user-visible impact clearly, and include enough validation for maintainers to review it.

## 开发 / Development

提交改动前请先运行本地检查：

Run local checks before sending changes:

```bash
pnpm check
```

如果项目包含 Python Agent 代码，也请运行 Python 检查：

If the project includes Python Agent code, also run Python checks:

```bash
pnpm check:py
```

## Issue

提交 Issue 前请确认：

Before opening an issue:

- 已更新到最新版本，并确认问题仍然存在 / update to the latest release and confirm the issue still exists
- 已搜索 open 和 closed issues / search open and closed issues
- 标题简短明确，避免“卡住了”“有问题”等模糊描述 / use a short, specific title
- 以文件形式上传完整日志，不要粘贴长日志或截图日志 / attach logs as files instead of pasting long log text or screenshots of logs

如果问题涉及识别、点击或任务流程，请同时提供相关 task/pipeline 节点、资源包路径、截图和可用的调试图片。

For recognition, touch, or task-flow problems, include the affected task or pipeline node, resource pack path, screenshots, and debug images when available.

## Pull Request

建议使用聚焦的分支名，例如 `feat/add-task`、`fix/recognition-node`、`docs/update-guide`。

Use a focused branch name such as `feat/add-task`, `fix/recognition-node`, or `docs/update-guide`.

一个 PR 应只解决一个明确问题，避免混入无关格式化、重构或功能改动。

A pull request should solve one clear problem and avoid mixing unrelated formatting, refactors, or feature work.

PR 描述应包含：

In the PR description, include:

- 关联 Issue，或没有 Issue 时说明需求来源 / the related issue, or why the change is needed if there is no issue
- 2 到 5 条变更摘要 / 2 to 5 bullets summarizing what changed
- 实际执行的验证命令和结果 / exact validation commands and their results
- 涉及识别、界面、工作流或 Bug 修复时的截图、日志或资源路径 / screenshots, logs, or resource paths for recognition, UI, workflow, or bug fixes

推荐使用约定式提交：

Prefer conventional commit style:

```text
feat(scope): short description
fix(scope): short description
docs: short description
```

## MaaFW 项目注意事项 / MaaFW Project Notes

- 资源路径使用正斜杠 / Keep resource paths using forward slashes.
- 保持 `maa-project.json` 中资源包顺序稳定 / Keep resource packs ordered in `maa-project.json`.
- 坐标、ROI、模板图片遵循 MaaFW 720p 基准约定 / Use the MaaFW 720p baseline convention for coordinates, ROI, and template images.
- 保持 `interface.json`、task 文件和 resource 文件一致 / Keep `interface.json`, task files, and resource files consistent.
- 不要提交本地缓存、构建产物、调试截图、下载的 runtime 文件或大体积模型文件，除非它们确实属于项目内容 / Do not commit local caches, build outputs, debug screenshots, downloaded runtime files, or large model files unless they are intentionally part of the project.
