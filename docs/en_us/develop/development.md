---
order: 1
icon: iconoir:developer
---
# Notes Before Development

> [!NOTE]
>
> You only need to read this page if you want to take part in the development of M9A!
>
> Users should refer to the [M9A User Manual](../manual/newbie.md).
>
> For developing MaaFramework or your own projects, please visit [MaaXYZ/MaaFramework](https://github.com/MaaXYZ/MaaFramework).

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

    > ⚠
    >
    > **Do not forget `--recursive`! Do not forget `--recursive`! Do not forget `--recursive`!**  
    > OCR failures are often caused by forgetting to include `--recursive`.

4. Download the [Release Package](https://github.com/MaaXYZ/MaaFramework/releases) of MaaFramework and extract it into the `deps` folder.

5. Set up the development environment:

    - Install python(≥3.11)
    - Download and install VSCode.
    - Optionally install debugging/development tools:

        | Tool | Description |
        | --- | --- |
        | [MaaDebugger](https://github.com/MaaXYZ/MaaDebugger) | Standalone debugging tool |
        | [Maa Pipeline Support](https://marketplace.visualstudio.com/items?itemName=nekosu.maa-support) | VSCode plugin for debugging, screenshots, ROI extraction, color picking, etc. |
        | [MFA Tools(Windows Only)](https://github.com/SweetSmellFox/MFATools) | Standalone tool for screenshots, ROI extraction, and color picking |
        | [ImageCropper(Not recommended)](https://github.com/MaaXYZ/MaaFramework/tree/main/tools/ImageCropper) | Standalone tool for screenshots and ROI extraction |

6. Start developing:

    Run `python ./tools/ci/configure.py` in the root directory of the project to configure the OCR model.

    Develop the M9A with the debugging/development tools installed in the previous step. The virtual environment will be automatically created in the `.venv` directory.

    Enjoy coding! Before starting, check out other parts.

7. Git operations:

    The most commonly used basic commands are:
    - `git add <file>`: Add files to the staging area. Use `*` to represent all files.
    - `git commit -m "message"`: Commit the staged files to the local repository. Please follow the [Conventional Commits Specification](https://www.conventionalcommits.org/en/v1.0.0/) for clear commit messages.
    - `git pull origin <branch>`: Pull updates from the remote repository to the local repository.
    - `git push origin <branch>`: Push local changes to the remote repository.

    > ⚠
    >
    > During development, remember to commit changes regularly with a message.
    > If you're not familiar with Git, you may need to create and switch to a new branch instead of committing directly to `main`.
    > This way, your commits will grow on the new branch without being affected by updates to `main`.

    ```bash
    git checkout -b <branch-name> # Create and switch to a new branch
    ```

    After development, push your modified local branch to the remote repository (your fork):

    ```bash
    git push origin <branch-name>
    ```

    If there are changes in the M9A repository (e.g., commits from others), you may need to sync these changes to your branch:

    1. Link the original M9A repository:

        ```bash
        git remote add upstream https://github.com/MAA1999/M9A.git
        ```

    2. Fetch updates from the remote repository:

        ```bash
        git fetch upstream
        ```

    3. Rebase (recommended) or merge the changes:

        ```bash
        git rebase upstream/main # Rebase for a cleaner commit history. Rebase is recommended over merge when completing your personal PR.
        ```

        Or:

        ```bash
        git merge upstream/main
        ```

    Git reference materials:
    - [Git Official Documentation](https://git-scm.com/docs)
    - [Git Simplified Guide](https://www.runoob.com/manual/git-guide/)
    - [Git Tutorial | Runoob](https://www.runoob.com/git/git-tutorial.html)

8. Submit a Pull Request:

    Your modified code has been committed to your repository. Now, you need to submit a Pull Request to the M9A repository and wait for the maintainers to review it.

    [GitHub Pull Request Reference](https://maa.plus/docs/en-us/develop/pr-tutorial.html)

## M9A Formatting Requirements

M9A uses a series of formatting tools to ensure that the code and resource files in the repository are clean and consistent, making them easier to maintain and read.

Please ensure that your code is formatted before submission, or enable Pre-commit Hooks for automatic formatting.

Currently enabled formatting tools:

| File Type | Formatting Tool |
| --- | --- |
| JSON/Yaml | [prettier](https://prettier.io/) |
| Markdown | [MarkdownLint](https://github.com/DavidAnson/markdownlint-cli2) |

### Automatically Format Code Using Pre-commit Hooks

> [!NOTE]
>
> In actual collaboration, when developing in vscode, after installing the recommended plugin, automatic formatting can basically be completed, so this part can be skipped.

1. Ensure that Python and Node environments are installed on your computer.

2. Run the following commands in the project's root directory:

    ```bash
    pip install pre-commit
    pre-commit install
    ```

If `pre-commit` cannot run after installation, ensure that the pip installation path has been added to the PATH environment variable.

From now on, formatting tools will automatically run during each commit to ensure your code meets the formatting standards.

Manually trigger formatting:

```bash
pre-commit run --all-files
```
