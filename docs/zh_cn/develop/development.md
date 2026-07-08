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
    **--recursive 一定不要忘！\*\***--recursive 一定不要忘！\***\*--recursive 一定不要忘！**  
    OCR异常失败很可能就是没加recursive导致
    :::

    如已克隆但发现资源缺失，可运行：

    ```bash
    git submodule update --init --recursive
    ```

    从子模块复制 OCR 模型：

    ```bash
    python tools/configure.py
    ```

4. 配置编程环境

    - 安装 python（3.13）
    - 安装 Node.js（≥24）和 pnpm
    - 安装 [uv](https://docs.astral.sh/uv/)（Python 包和项目管理工具）
    - 下载并安装 VSCode
    - 选择性安装调试/开发工具

        | 工具                                                                                           | 简介                                               |
        | ---------------------------------------------------------------------------------------------- | -------------------------------------------------- |
        | [MaaDebugger](https://github.com/MaaXYZ/MaaDebugger)                                           | 独立调试工具                                       |
        | [Maa Pipeline Support](https://marketplace.visualstudio.com/items?itemName=nekosu.maa-support) | VSCode 插件，提供调试、截图、获取 ROI 、取色等功能 |
        | [MFAToolsPlus](https://github.com/SweetSmellFox/MFAToolsPlus)                                  | 跨平台开发工具箱，提供便捷的数据获取和模拟测试方法 |
        | [ImageCropper(不推荐)](https://github.com/MaaXYZ/MaaFramework/tree/main/tools/ImageCropper)    | 独立截图及获取 ROI 工具                            |
        | [MaaLogAnalyzer](https://github.com/Windsland52/MAALogAnalyzer)                                | 可视化分析基于 MaaFramework 开发应用的日志         |

    ::: tip
    推荐使用 VSCode 插件进行开发调试、MaaLogAnalyzer 进行用户日志分析
    :::

5. 安装项目依赖

    在项目根目录运行以下命令安装依赖：

    ```bash
    pnpm install
    uv sync
    ```

6. 开始开发

    使用调试/开发工具开发 M9A。

    开始愉快的改代码吧。

7. 提交 Pull Request

    完成开发后，提交 Pull Request 到 M9A 仓库。
