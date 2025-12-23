---
order: 1
icon: iconoir:developer
---
# 开发前须知

::: tip
只有当您想要开发 M9A 时才需要看当前页面！
用户请转到 [M9A 使用手册](../manual/newbie.md)
开发 MaaFramework 或开发自己的项目请到 [MaaXYZ/MaaFramework](https://maafw.xyz)
:::

## Github Pull Request 流程简述

### 我不懂编程，只是想改一点点 JSON 文件/文档等，要怎么操作？

欢迎收看 [牛牛也能看懂的 GitHub Pull Request 使用指南](https://maa.plus/docs/zh-cn/develop/pr-tutorial.html)

### 我有编程经验，但是没参与过相关项目，要怎么做？

1. 如果很久以前 fork 过，先在自己仓库的 `Settings` 里，翻到最下面，删除

2. 打开 [M9A 主仓库](https://github.com/MAA1999/M9A)，点击 `Fork`，继续点击 `Create fork`

3. 克隆你自己的仓库到本地，并拉取子模块

    ```bash
    git clone --recursive https://github.com/<你的用户名>/M9A.git
    ```

    ::: warning
    **--recursive 一定不要忘！****--recursive 一定不要忘！****--recursive 一定不要忘！**  
    OCR异常失败很可能就是没加recursive导致
    :::

    如已克隆但发现资源缺失，可运行：

    ```bash
    git submodule update --init --recursive
    ```

4. 下载 MaaFramework 的 [Release 包](https://github.com/MaaXYZ/MaaFramework/releases)，解压到 `deps` 文件夹中。

    ::: tip
    目前可跳过这步，仅在需要本地测试命令行版本时执行
    :::

5. 配置编程环境

    - 安装 python（≥3.11）
    - 下载并安装vscode
    - 选择性安装调试/开发工具

        | 工具 | 简介 |
        | --- | --- |
        | [MaaDebugger](https://github.com/MaaXYZ/MaaDebugger) | 独立调试工具 |
        | [Maa Pipeline Support](https://marketplace.visualstudio.com/items?itemName=nekosu.maa-support) | VSCode 插件，提供调试、截图、获取 ROI 、取色等功能 |
        | [MFA Tools(仅win)](https://github.com/SweetSmellFox/MFATools) | 独立截图、获取 ROI 及取色工具 |
        | [ImageCropper(不推荐)](https://github.com/MaaXYZ/MaaFramework/tree/main/tools/ImageCropper) | 独立截图及获取 ROI 工具 |
        | [MaaLogAnalyzer](https://github.com/Windsland52/MAALogAnalyzer) | 可视化分析基于 MaaFramework 开发应用的日志 |

    ::: tip
    推荐使用 VSCode 插件进行开发调试、MaaLogAnalyzer 进行用户日志分析
    :::

6. 开始开发

    在项目的根目录运行 `python ./tools/ci/configure.py` 配置OCR模型。

    使用上一个步骤中安装的调试/开发工具开发M9A，虚拟环境会自动创建在`.venv`目录中。

    开始愉快的改代码吧，可以看看别的文档。

7. git 操作

    通常用的最多的基本命令有：
    - `git add <file>`：添加文件到暂存区，`*` 代表全部文件
    - `git commit -m "message"`：提交暂存区到本地仓库。`message` 请遵循 [约定式提交规范](https://www.conventionalcommits.org/zh-hans/v1.0.0/)，让你的 commit 信息更加清晰
    - `git pull origin <branch>`：拉取远程仓库到本地仓库
    - `git push origin <branch>`：推送本地仓库到远程仓库

    ::: warning
    开发过程中，每一定数量，记得提交一个 commit, 别忘了写上 message
    假如你不熟悉 git 的使用，你可能需要创建并切换到一个新的分支，而不是直接提交在 main 上
    这样你的提交就能在新的分支上生长，不会受到 main 更新的打扰
    :::

    ```bash
    git checkout -b <branch-name> # 创建并切换到新的分支
    ```

    完成开发后，推送你修改的本地分支到远程仓库（fork 的仓库）

    ```bash
    git push origin <branch-name>
    ```

    当 M9A 仓库出现更改（如其他人的commit），你可能需要把这些更改同步到你的分支

    1. 关联 M9A 原仓库：

        ```bash
        git remote add upstream https://github.com/MAA1999/M9A.git
        ```

    2. 拉取远程仓库更新：

        ```bash
        git fetch upstream
        ```

    3. 变基（推荐）或者合并修改：

        ```bash
        git rebase upstream/main # 变基，使commit历史更清晰，完成你的个人pr时建议使用rebase而不是merge来合并修改
        ```

        或者

        ```bash
        git merge upstream/main
        ```

    git 参考资料：
    - [git 官方文档](https://git-scm.com/docs)
    - [git 简明指南](https://www.runoob.com/manual/git-guide/)
    - [git 教程|菜鸟教程](https://www.runoob.com/git/git-tutorial.html)

8. 提交 Pull Request

    你修改的代码已经提交到你的仓库，现在你需要提交一个 Pull Request 到 M9A 的仓库，等待维护者审核

    [GitHub Pull Request 参考](https://maa.plus/docs/zh-cn/develop/pr-tutorial.html)

## M9A 格式化要求

M9A 使用一系列的格式化工具来保证仓库中的代码和资源文件美观统一，以便于维护和阅读

请确保在提交之前已经格式化，或是启用 Pre-commit Hooks 进行自动格式化

目前启用的格式化工具如下：

| 文件类型 | 格式化工具 |
| --- | --- |
| JSON/Yaml | [prettier](https://prettier.io/) |
| Markdown | [MarkdownLint](https://github.com/DavidAnson/markdownlint-cli2) |

### 利用 Pre-commit Hooks 自动进行代码格式化

::: tip
实际协作中，在 vscode 中开发，安装推荐的插件后，基本就可以完成自动格式化了，故该部分可跳过。
:::

1. 确保你的电脑上有 Python 与 Node 环境

2. 在项目根目录下执行以下命令

    ```bash
    pip install pre-commit
    pre-commit install
    ```

如果pip安装后依然无法运行pre-commit，请确认pip安装地址已被添加到PATH

接下来，每次提交时都将会自动运行格式化工具，来确保你的代码格式符合规范

手动触发：
    ```bash
    pre-commit run --all-files
    ```
