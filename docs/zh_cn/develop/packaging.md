---
order: 10
icon: mdi:package-variant
---

# Python Agent 打包与使用指南

本文档介绍 M9A 项目中 Python Agent 的打包流程和使用方式，供其他项目参考和复制修改。

## 概述

M9A 的 Python Agent 是基于 MaaFramework 的 Python 绑定开发的自动化任务执行器。项目采用了以下技术方案：

- **虚拟环境管理**：Linux 和开发模式下自动创建和使用 `.venv` 虚拟环境
- **依赖管理**：支持本地 whl 文件和在线镜像源两种安装方式
- **配置系统**：通过 JSON 配置文件管理 pip 源、热更新等选项
- **热更新机制**：支持资源文件的在线更新
- **跨平台支持**：Windows、Linux、macOS 三平台支持

## 项目结构

### 源码结构

```bash
project/
├──.github/workflows/
│   └── install.yml              # CI/CD 打包流程
├── agent/
│   ├── main.py                  # Agent 主入口文件
│   ├── utils/                   # 工具模块（日志、配置、热更新等）
│   └── custom/                  # 自定义业务逻辑
├── assets/                      # 资源文件（图片、配置等）
├── tools/ci/
│   ├── setup_embed_python.py    # 设置嵌入式 Python
│   ├── download_deps.py         # 下载 Python 依赖
│   ├── install.py               # 打包脚本（Full 版本）
│   └── install_cli.py           # 打包脚本（Lite 版本）
└── requirements.txt             # Python 依赖列表
```

### 打包后的结构

```bash
install/                     # 打包产物目录（CI/CD 生成）
├── agent/
│   ├── main.py              # Agent 主入口文件
│   ├── utils/               # 工具模块（日志、配置、热更新等）
│   └── custom/              # 自定义业务逻辑
├── python/                  # 嵌入式 Python 环境（Windows/macOS）
│   ├── python.exe           # Windows
│   └── bin/python3          # macOS
├── deps/                    # Python 依赖 whl 文件
│   ├── package1.whl
│   ├── package2.whl
│   └── ...
├── resource/                # Assets下的 resource 文件夹
└── interface.json           # 版本信息
```

## Agent 主入口文件解析

### 核心功能模块

`agent/main.py` 包含以下核心功能：

#### 1. 虚拟环境管理

```python
def ensure_venv_and_relaunch_if_needed():
    """
    确保venv存在，并且如果尚未在脚本管理的venv中运行，
    则在其中重新启动脚本。支持 Linux、Windows、macOS 三平台。
    """
```

**工作流程：**

1. 检查当前是否在虚拟环境中运行（通过 `sys.prefix != sys.base_prefix` 判断）
2. 如果不在虚拟环境中：
   - 检查 `.venv` 目录是否存在，不存在则创建
   - 使用虚拟环境中的 Python 重新启动脚本
   - 退出当前进程，返回子进程的退出码
3. 如果已在虚拟环境中，继续执行

**平台差异：**

- Windows: 使用 `.venv/Scripts/python.exe`
- Linux/macOS: 优先使用 `.venv/bin/python3`，其次 `.venv/bin/python`

**触发条件：**

- **Linux 系统**：始终启用（生产环境也使用虚拟环境）
- **开发模式**（`interface.json` 版本为 "DEBUG"）：所有平台都启用
- **Windows/macOS 生产环境**：不启用（使用嵌入式 Python）

#### 2. 依赖安装机制

```python
def install_requirements(req_file="requirements.txt", pip_config=None) -> bool:
```

**安装策略（按优先级）：**

1. **本地 whl 文件安装**（最优先）
   - 检查 `deps/` 目录是否存在 `.whl` 文件
   - 使用 `pip install --find-links deps/ --no-index` 从本地安装
   - 优点：离线可用，速度快，版本可控

2. **在线镜像源安装**（本地失败时回退）
   - 使用配置的主镜像源（默认：清华源）
   - 添加备用镜像源（默认：中科大源）
   - 命令示例：`pip install -i <主源> --extra-index-url <备用源>`

3. **pip 全局配置安装**（无配置镜像源时）
   - 使用用户本地的 pip 配置
   - 适用于有自定义 pip 配置的环境

**重要参数：**

- `--no-warn-script-location`: 抑制脚本位置警告
- `--break-system-packages`: 允许在系统 Python 中安装（Linux 需要）

#### 3. 配置系统

项目使用 JSON 配置文件管理各项设置，配置文件位于 `config/` 目录：

**pip_config.json**

```json
{
  "enable_pip_install": true,
  "mirror": "https://pypi.tuna.tsinghua.edu.cn/simple",
  "backup_mirror": "https://mirrors.ustc.edu.cn/pypi/simple"
}
```

**hot_update.json**

```json
{
  "enable_hot_update": true
}
```

配置文件特点：

- 首次运行时自动创建默认配置
- 读取失败时使用默认配置，不中断程序
- 用户可手动修改配置文件

#### 4. 版本检测与热更新

```python
def agent(is_dev_mode=False):
    # 版本检查
    version_info = check_resource_version()

    # 热更新（基于 manifest 时间戳优化）
    manifest_result = check_manifest_updates()
    if manifest_result["has_any_update"]:
        update_result = check_and_update_resources()
```

**热更新流程：**

1. 检查远程 manifest 文件的时间戳
2. 对比本地缓存，判断是否有更新
3. 只下载有变化的资源文件
4. 更新本地 manifest 缓存

## CI/CD 打包流程

### 打包流程概览

GitHub Actions 工作流 (`.github/workflows/install.yml`) 定义了完整的打包流程：

```yaml
jobs:
  meta:      # 版本号和发布类型判断
  windows:   # Windows 平台打包
  linux:     # Linux 平台打包
  macos:     # macOS 平台打包
  changelog: # 生成更新日志
  release:   # 发布到 GitHub Releases
```

### 各平台打包步骤

#### Windows 平台

```yaml
steps:
  # 1. 下载 MaaFramework
  - name: Download MaaFramework
    uses: robinraju/release-downloader@v1
    with:
      repository: MaaXYZ/MaaFramework
      fileName: "MAA-win-${{ matrix.arch }}*"
      tag: ${{ env.MAA_FRAMEWORK_VERSION }}
      out-file-path: "deps"
      extract: true

  # 2. 设置嵌入式 Python
  - name: Setup Embed Python on Windows
    run: python tools/ci/setup_embed_python.py

  # 3. 下载 Python 依赖
  - name: Download Python dependencies
    run: ./install/python/python.exe tools/ci/download_deps.py --deps-dir install/deps

  # 4. 执行打包
  - name: Install
    run: ./install/python/python.exe ./tools/ci/install.py ${{ needs.meta.outputs.tag }} $PLATFORM_TAG

  # 5. 创建 CLI 版本
  - name: Create CLI version
    run: ./install/python/python.exe ./tools/ci/install_cli.py ${{ needs.meta.outputs.tag }}
```

**关键点：**

- 使用嵌入式 Python（`install/python/python.exe`）
- 依赖下载到 `install/deps/` 目录
- 生成两个版本：Full（包含 GUI）和 Lite（仅 CLI）

#### Linux 平台

```yaml
steps:
  # 1. 下载 MaaFramework
  - name: Download MaaFramework for Linux
    uses: robinraju/release-downloader@v1

  # 2. 下载 Python 依赖
  - name: Download Python dependencies
    run: python tools/ci/download_deps.py --deps-dir install/deps

  # 3. 执行打包
  - name: Install on Linux
    run: python ./tools/ci/install.py ${{ needs.meta.outputs.tag }} $PLATFORM_TAG

  # 4. 创建 CLI 版本
  - name: Create CLI version
    run: python ./tools/ci/install_cli.py ${{ needs.meta.outputs.tag }}
```

**关键点：**

- 使用系统 Python（不使用嵌入式 Python）
- 运行时会自动创建 `.venv` 虚拟环境
- 依赖同样下载到 `install/deps/` 目录

#### macOS 平台

```yaml
steps:
  # 1. 下载 MaaFramework
  - name: Download MaaFramework for macOS
    uses: robinraju/release-downloader@v1

  # 2. 设置嵌入式 Python
  - name: Setup Embed Python on macOS
    run: python3 tools/ci/setup_embed_python.py

  # 3. 下载 Python 依赖
  - name: Download Python dependencies
    run: ./install/python/bin/python3 tools/ci/download_deps.py --deps-dir install/deps

  # 4. 执行打包
  - name: Install on macOS
    run: ./install/python/bin/python3 ./tools/ci/install.py ${{ needs.meta.outputs.tag }} $PLATFORM_TAG
```

**关键点：**

- 使用嵌入式 Python（`install/python/bin/python3`）
- 需要设置可执行权限：`chmod +x install/python/bin/python3`
- 打包流程与 Windows 类似

### 打包产物

每个平台会生成两个版本：

1. **Full 版本**（`M9A-{platform}-{arch}-{version}-Full`）
   - 包含完整的 GUI 界面（MFAAvalonia）
   - 包含 Python Agent 和所有依赖
   - 包含 MaaFramework 运行时
   - 适合普通用户使用

2. **Lite 版本**（`M9A-{platform}-{arch}-{version}-Lite`）
   - 仅包含命令行界面（MaaPiCli）
   - 包含 Python Agent 和所有依赖
   - 不包含 GUI 相关文件
   - 适合服务器部署或自动化脚本

## Agent 使用方式

### 启动流程

Agent 通过 MaaFramework 的 `AgentServer` 启动：

```python
# main.py 入口
if __name__ == "__main__":
    main()

def main():
    # 1. 读取版本信息，判断是否为开发模式
    current_version = read_interface_version()
    is_dev_mode = current_version == "DEBUG"

    # 2. Linux/开发模式下启动虚拟环境
    if sys.platform.startswith("linux") or is_dev_mode:
        ensure_venv_and_relaunch_if_needed()

    # 3. 检查并安装依赖
    check_and_install_dependencies()

    # 4. 启动 AgentServer
    agent(is_dev_mode=is_dev_mode)
```

### 命令行参数

Agent 需要接收 `socket_id` 参数用于与 MaaFramework 通信：

```python
# 从命令行参数获取 socket_id
socket_id = sys.argv[-1]

# 启动 AgentServer
AgentServer.start_up(socket_id)
AgentServer.join()
AgentServer.shut_down()
```

**调用示例：**

```bash
python agent/main.py <socket_id>
```

## 其他项目如何复制修改

### 1. 复制核心文件

从 M9A 项目复制以下文件到你的项目：

```bash
your-project/
├── .github/workflows/
│   └── install.yml                 # 根据需求修改
├── agent/
│   ├── main.py                     # 复制并修改
│   └── utils/                      # 工具模块
│       ├── __init__.py             # 必需：模块初始化，按需修改
│       ├── logger.py               # 必需：日志模块
│       ├── exceptions.py           # 可选：异常定义
│       ├── version_checker.py      # 可选：版本检查
│       ├── manifest_checker.py     # 可选：热更新-manifest检查，需修改
│       └── resource_updater.py     # 可选：热更新-资源更新，需修改
├── tools/ci/
│   ├── setup_embed_python.py       # 直接复制
│   ├── download_deps.py            # 直接复制
│   ├── install.py                  # 根据需求修改
│   └── install_cli.py              # 根据需求修改
└── requirements.txt                # 根据需求修改
```

### 2. 修改要点

#### agent/main.py

需要修改的部分：

1. **项目根目录设置**

   ```python
   # 根据你的项目结构调整
   current_script_dir = os.path.dirname(current_file_path)
   project_root_dir = os.path.dirname(current_script_dir)
   ```

2. **业务逻辑部分**

   ```python
   def agent(is_dev_mode=False):
       # 保留虚拟环境、依赖安装、配置管理等通用逻辑
       # 修改业务逻辑部分：

       # 替换为你的业务模块
       from your_module import YourAgent

       # 替换为你的初始化逻辑
       YourAgent.init()
       YourAgent.start()
   ```

3. **热更新逻辑**（可选）
   - 如果不需要热更新，可以删除相关代码
   - 如果需要，需要实现 `utils.manifest_checker` 和 `utils.resource_updater` 模块

#### .github/workflows/install.yml

需要修改的部分：

1. **环境变量**

   ```yaml
   env:
     MAA_FRAMEWORK_VERSION: "v5.4.2"  # 修改为你需要的版本
     # 添加你的其他依赖版本
   ```

2. **下载依赖步骤**

   ```yaml
   # 根据你的项目依赖修改
   - name: Download MaaFramework
     uses: robinraju/release-downloader@v1
     with:
       repository: MaaXYZ/MaaFramework  # 修改为你的依赖仓库
       fileName: "MAA-win-${{ matrix.arch }}*"
       tag: ${{ env.MAA_FRAMEWORK_VERSION }}
   ```

3. **打包步骤**
   - 保留 Python 环境设置和依赖下载步骤
   - 修改 `install.py` 和 `install_cli.py` 的调用参数
   - 根据需要添加或删除其他步骤（如图标转换、文件复制等）

### 3. 注意事项

#### 平台差异处理

1. **Python 环境**
   - Windows/macOS: 使用嵌入式 Python，需要 `setup_embed_python.py`
   - Linux: 使用系统 Python + 虚拟环境

2. **路径分隔符**
   - 使用 `pathlib.Path` 处理路径，自动适配不同平台
   - 避免硬编码 `/` 或 `\`

3. **可执行权限**
   - Linux/macOS 需要设置可执行权限：`chmod +x`
   - 在 CI/CD 的 release 步骤中处理

#### 依赖管理

1. **本地 whl 文件优先**
   - 打包时将所有依赖下载到 `deps/` 目录
   - 用户首次运行时优先使用本地 whl，无需联网
   - 本地安装失败时自动回退到在线安装

2. **镜像源配置**
   - 提供默认镜像源（清华、中科大等）
   - 允许用户通过配置文件自定义镜像源
   - 支持主源 + 备用源的双源策略

3. **版本锁定**
   - 在 `requirements.txt` 中锁定依赖版本
   - 避免因依赖更新导致的兼容性问题

#### 错误处理

1. **配置文件读取失败**
   - 使用默认配置，不中断程序
   - 记录警告日志，便于排查问题

2. **依赖安装失败**
   - 提供多种安装策略（本地 → 在线主源 → 在线备用源）
   - 记录详细的错误信息
   - 给出用户友好的提示

3. **虚拟环境创建失败**
   - 检查 Python 版本和 venv 模块可用性
   - 提供清晰的错误信息和解决建议

## 总结

M9A 的 Python Agent 打包方案具有以下优势：

1. **跨平台支持**：统一的代码库支持 Windows、Linux、macOS 三大平台
2. **离线可用**：打包时包含所有依赖，用户无需联网即可运行
3. **自动化程度高**：虚拟环境管理、依赖安装全自动化
4. **灵活配置**：通过 JSON 配置文件管理各项设置
5. **容错性强**：多级回退策略，确保在各种环境下都能正常运行
