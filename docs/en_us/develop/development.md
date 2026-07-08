---
order: 1
icon: iconoir:developer
---

# Notes Before Development

::: tip
You only need to read this page if you want to take part in the development of M9A!
Users should refer to the [M9A User Manual](../manual/newbie.md).
For developing MaaFramework or your own projects, please visit [MaaXYZ/MaaFramework](https://maafw.xyz).
:::

## A Brief Overview of the GitHub Pull Request Process

### I don't know programming and just want to make small changes to JSON files/documents. What should I do?

Check out the [GitHub Pull Request Guide for Beginners](https://maa.plus/docs/en-us/develop/pr-tutorial.html).

### I have programming experience but haven't participated in related projects. What should I do?

1. If you forked the repository a long time ago, go to `Settings` in your repository, scroll to the bottom, and delete it.

2. Open the [M9A Main Repository](https://github.com/MAA1999/M9A), click `Fork`, and then click `Create fork`.

3. Clone your own repository locally and pull the submodules:

    ```bash
    git clone --recursive https://github.com/<your-username>/M9A.git
    ```

    ::: warning
    **Do not forget `--recursive`! Do not forget `--recursive`! Do not forget `--recursive`!**  
    OCR failures are often caused by forgetting to include `--recursive`.
    :::

    If you already cloned but find resources missing, run:

    ```bash
    git submodule update --init --recursive
    ```

    Copy the OCR model from the submodule:

    ```bash
    python tools/configure.py
    ```

4. Set up the development environment:

    - Install Python 3.13
    - Install Node.js (≥24) and pnpm
    - Install [uv](https://docs.astral.sh/uv/) (Python Package and Project Management Tool)
    - Download and install VSCode.
    - Optionally install debugging/development tools:

        | Tool                                                                                                 | Description                                                                                 |
        | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
        | [MaaDebugger](https://github.com/MaaXYZ/MaaDebugger)                                                 | Standalone debugging tool                                                                   |
        | [Maa Pipeline Support](https://marketplace.visualstudio.com/items?itemName=nekosu.maa-support)       | VSCode plugin for debugging, screenshots, ROI extraction, color picking, etc.               |
        | [MFAToolsPlus](https://github.com/SweetSmellFox/MFAToolsPlus)                                        | Cross-platform toolbox providing convenient data acquisition and simulation testing methods |
        | [ImageCropper(Not recommended)](https://github.com/MaaXYZ/MaaFramework/tree/main/tools/ImageCropper) | Standalone tool for screenshots and ROI extraction                                          |
        | [MaaLogAnalyzer](https://github.com/Windsland52/MAALogAnalyzer)                                      | Visual analysis of logs from MaaFramework-based applications                                |

    ::: tip
    It is recommended to use the VSCode plugin for development and debugging, and MaaLogAnalyzer for user log analysis.
    :::

5. Install project dependencies

    Run the following commands in the project root to install dependencies:

    ```bash
    pnpm install
    uv sync
    ```

6. Start developing:

    Develop M9A with the debugging tools installed in the previous step.

    Enjoy coding!

7. Submit a Pull Request

    Submit a Pull Request to the M9A repository.
