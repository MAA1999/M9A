---
order: 1
icon: ri:guide-fill
---
<!-- markdownlint-disable MD033 -->
# 新手上路

## 前置准备

### 1. 确认版本系统

<div align="center">

| | Windows | macOS | Linux | Android |
| :---: | :---: | :---: | :---: | :---: |
| 系统要求 | Windows 10 及以上 | 自行尝试 | 自行尝试 | 不推荐 |
| 需要配置环境 | 是 | 是 | 是 | 是 |
| 需要模拟器 | 是 | 是 | 模拟器或容器化安卓 | 否 |
| 使用方式 | 图形界面或命令行 | 图形界面或命令行 | 图形界面或命令行 | 命令行 |

| | 备注 |
| --- | --- |
| Windows 用户 | 绝大部分情况请下载 x86_64 架构 |
| Mac 用户 | M9A 同时支持搭载 Apple Silicon 和 Intel 芯片的 Mac 电脑<br>但更推荐搭载 Intel 芯片的 Mac 电脑使用 Mac 自带的多系统安装 Windows<br>并使用 Windows 版 M9A 和模拟器 |
| Android 用户 | M9A 已不再提供 Android 版本发行包<br>如您非常了解手机操作并希望使用 Android 实体设备，请前往 [MaaFramework](https://github.com/MaaXYZ/MaaFramework/) 自行安装<br>可参考 [使用方法](https://github.com/MaaXYZ/MaaFramework/issues/475) ，以及 [MAA文档](https://maa.plus/docs/zh-cn/manual/device/android.html) <br>此方法较为复杂且具有一定风险，不推荐入门玩家使用此方法 |

</div>

***

### 2. 安装运行环境

>[!NOTE]
>
> 用户可跳过这节，在第3步下载解压后运行依赖库安装脚本，脚本自动安装失败后再看这节

<div align="center">

<table>
    <thead>
        <tr>
            <th rowspan="2"><div align="center">启动方式</div></th>
            <th colspan="2"><div align="center">Windows</div></th>
            <th colspan="2"><div align="center">macOS</div></th>
            <th colspan="2"><div align="center">Linux</div></th>
        </tr>
        <tr>
            <th><div align="center">命令行（MaaPiCli）</div></th>
            <th><div align="center">图形界面（MFAAvalonia）</div></th>
            <th><div align="center">命令行</div></th>
            <th><div align="center">图形界面</div></th>
            <th><div align="center">命令行</div></th>
            <th><div align="center">图形界面</div></th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><div align="center">需安装<br>VCRedist</div></td>
            <td colspan="2"><div align="center">点击 <a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank">vc_redist.x64</a> 下载或通过 winget 安装（详见下方）</div></td>
            <td colspan="4"><div align="center">否</div></td>
        </tr>
        <tr>
            <td><div align="center">需安装<br>.NET 10</div></td>
            <td><div align="center">否</div></td>
            <td><div align="center">前往 <a href="https://dotnet.microsoft.com/zh-cn/download/dotnet/10.0" target="_blank">.NET 官方下载页面</a> 下载对应版本或<br>通过 winget 安装（详见下方）</div></td>
            <td><div align="center">否</div></td>
            <td><div align="center"> <a href="https://dotnet.microsoft.com/zh-cn/download/dotnet/10.0" target="_blank">.NET 官方下载页面</a> </div></td>
            <td><div align="center">否</div></td>
            <td><div align="center">同 Mac</div></td>
        </tr>
        <tr>
            <td><div align="center">需安装<br>Python</div></td>
            <td colspan="4"><div align="center">压缩包自带，无需其他操作</div></td>
            <td colspan="2"><div align="center">3.10≤python<3.14</div></td>
        </tr>
    </tbody>
</table>

</div>

#### 1. VCRedist x64

Windows 用户**必须安装 VCRedist x64**：这是运行 M9A (无论是命令行版本还是图形界面版本) 的基础需求。

<details>
  <summary>详细安装方式</summary>
  <p></p>
  <blockquote>
    <ul>
      <li>
        直接下载：点击
        <a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank">vc_redist.x64</a>
        下载并安装
      </li>
      <li>
        <code>winget</code> 安装：右键 Windows 开始按钮，选择“命令提示符”或“PowerShell (管理员)”，然后在终端内粘贴以下命令并回车：
        <pre><code>winget install Microsoft.VCRedist.2017.x64</code></pre>
      </li>
    </ul>
  </blockquote>
</details>

#### 2. .NET 10

所有使用图形界面的用户都需要自行下载并安装适用于您系统的 .NET 10 。

<details>
  <summary>详细安装方式</summary>
  <p></p>
  <blockquote>
    <ul>
      <li>
        自行下载：点击
        <a href="https://dotnet.microsoft.com/download/dotnet/10.0" target="_blank">.NET 官方下载页面</a>
        ，选择适合您系统的版本下载并安装。
        <div align="center">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Windows</th>
                <th>macOS</th>
                <th>Linux</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>您需要下载</td>
                <td colspan="1">.NET 桌面运行时</td>
                <td colspan="2">.NET 运行时</td>
              </tr>
              <tr>
                <td>安装程序</td>
                <td>x64</td>
                <td colspan="2">
                  <a href="https://builds.dotnet.microsoft.com/dotnet/scripts/v1/dotnet-install.sh" target="_blank">dotnet-install.sh</a>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </li>
      <li>
        （仅 Windows 用户）<code>winget</code> 安装：右键 Windows 开始按钮，选择“命令提示符”或“PowerShell (管理员)”，然后在终端内粘贴以下命令并回车：
        <pre><code>winget install Microsoft.DotNet.DesktopRuntime.10</code></pre>
      </li>
    </ul>
  </blockquote>
</details>

#### 3. Python

Linux 用户需要单独安装 Python 。

<details>

<summary>详情</summary>

<p></p>

<blockquote>

- 您的系统需要安装 **Python 版本 ≥ 3.10**。这是 M9A 启动和管理其内部环境所必需的。
- M9A 首次运行时会自动创建并使用独立的虚拟环境，并安装所需的 Python 依赖包 (来自 `requirements.txt`)。您**无需**手动创建虚拟环境或安装这些依赖。

</blockquote>

 </details>

***

### 3. 下载正确的版本

M9A 下载（更新）地址： [GitHub 发布页](https://github.com/MAA1999/M9A/releases)  。点击链接后，在 `Assets` 处选择适配您系统的最新版压缩包下载。

国内用户也可通过 [Mirror 酱](https://mirrorchyan.com/zh/download?rid=M9A&source=m9agh-md3) 高速下载。

<div align="center">

| | Windows | macOS | Linux |
| :---: | :---: | :---: | :---: |
| 您需要下载 | `M9A-win-x86_64-vXXX.zip` | `M9A-macos-x86_64-vXXX.tar.gz` 或 `M9A-macos-aarch64-vXXX.tar.gz`<br>取决于您的架构 | `M9A-linux-x86_64-vXXX.tar.gz` 或 `M9A-linux-aarch64-vXXX.tar.gz`<br>取决于您的架构 |

</div>

<details>
  <summary>Mac用户查看处理器架构方法</summary>
  <p></p>
  <blockquote>
    <ol>
      <li>点击屏幕左上角的苹果标志。</li>
      <li>选择“关于本机”。</li>
      <li>在弹出的窗口中，你可以看到处理器的信息。</li>
    </ol>
    <ul>
      <li>若使用 Intel X86 处理器，请下载 <code>M9A-macos-x86_64-vXXX.tar.gz</code></li>
      <li>若使用 Apple Silicon 系列如：M1、M2 等 ARM 架构处理器，请下载 <code>M9A-macos-aarch64-vXXX.tar.gz</code></li>
    </ul>
  </blockquote>
</details>

***

### 4. 确认模拟器和设备支持

<div align="center">

| | Windows | macOS | Linux | Android |
| :---: | :---: | :---: | :---: | :---: |
| 模拟器支持 | 支持主流模拟器 | 支持主流模拟器 | 自行尝试 | / |
| 需要adb功能 | 是 | 是 | 是 | 是 |
| 备注 |  | [暂不支持 PlayCover](https://github.com/MaaXYZ/MaaFramework/issues/405) |  |  |

</div>

模拟器支持详情可参阅 MAA 文档。**仅供参考**，请以 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 实际支持情况为准。

<details>

  <summary>MAA 模拟器和设备支持文档</summary>

  <p></p>

  <blockquote>

  <div align="center">

  | | Windows | macOS | Linux | Android |
  | -------- | -------- | ------- | ------- | ------- |
  | 参考文档 | [Windows 模拟器](https://maa.plus/docs/zh-cn/manual/device/windows.html) | 如果你的设备搭载 Apple Silicon 请参阅：<br>[在 Apple Silicon 平台上运行的Mac模拟器](https://maa.plus/docs/zh-cn/manual/device/macos.html#apple-silicon-%E8%8A%AF%E7%89%87)<br>如果你的设备搭载 Intel 芯片：<br>1. 推荐使用 Mac 自带的多系统安装 Windows <br>并参考 Windows 部分文档<br>2. 参阅[在 Intel 平台上运行的 Mac 模拟器](https://maa.plus/docs/zh-cn/manual/device/macos.html#intel-%E8%8A%AF%E7%89%87) | [Linux 模拟器与容器](https://maa.plus/docs/zh-cn/manual/device/linux.html) | [Android 实体设备](<https://maa.plus/docs/zh-cn/manual/device/android.html>) |

  </div>

  </blockquote>

 </details>

***

### 5. 正确设置分辨率

M9A 支持主流模拟器与PC端，但您需要设置模拟器与PC端分辨率以达到运行要求。  
模拟器与PC端分辨率应为`横屏` `16:9` 比例，推荐（以及最低）分辨率为 `1280x720`，不符合要求造成的运行报错将不会被解决。

#### 国际服PC端

使用国际服PC端时无法改为`16:9`比例？使用PC端初始化脚本。

<details>
  <summary>详情</summary>
  <p></p>
  <blockquote>
    <ul>
    <li>
      <details>
        <summary>打开脚本</summary>
          <ol>
            <li>在M9A根目录找到游戏PC端注册表修改_ModifyPCRegistry.bat</li>
            <li>双击启动</li>
          </ol>
      </details>
    </li>
    <li>
      <details>
        <summary>步骤1</summary>
          <ol>
            <li>打开后在命令行输入1</li>
            <li>如下图</li>
          </ol>
          <img src="/images/zh-cn/newbie-init-script-step1.webp" alt="步骤1">
      </details>
    </li>
    <li>
      <details>
        <summary>步骤2</summary>
          <ol>
            <li>根据你要选择的分辨率选择输入a/b/c/d</li>
            <li>如下图</li>
          </ol>
          <img src="/images/zh-cn/newbie-init-script-step2.webp" alt="步骤2">
      </details>
    </li>
    </ul>
  </blockquote>
</details>

>[!WARNING]
>
> 注意修改分辨率后模拟器主页应该是横屏（平板版），不要选成竖屏（手机版）了！

***

### 6. 开始使用

M9A 支持通过命令行（MaaPiCli）和图形化界面（MFAAvalonia），但在使用前，需正确解压压缩包、游戏内显示语言请改为简体中文。

> [!IMPORTANT]
> 不要在压缩软件直接打开程序！

对于一般用户，推荐通过 **MFAAvalonia** 使用 M9A 。

#### Windows

确认解压完整，并确保将 M9A 解压到一个独立的文件夹中。推荐解压路径如：`D:\M9A`。除关闭内建管理员批准的Administrator账号外，请勿将 MAA 解压到如 `C:\`、`C:\Program Files\` 等需要 UAC 权限的路径。

- 解压后运行 `MaaPiCli.exe` 或 `MFAAvalonia.exe` 即可

#### macOS

<details>
  <summary>详情</summary>
  <p></p>
  <blockquote>

1. 打开终端，解压分发的压缩包：

    **选项1：解压到系统目录（需要管理员权限）**

    ```shell
    sudo mkdir -p /usr/local/bin/M9A
    sudo tar -xzf <下载的M9A压缩包路径> -C /usr/local/bin/M9A
    ```

    **选项2：解压到用户目录（推荐，无需sudo）**

    ```shell
    mkdir -p ~/M9A
    tar -xzf <下载的M9A压缩包路径> -C ~/M9A
    ```

2. 进入解压目录并运行程序：

    ```shell
    cd /usr/local/bin/M9A
    ./MaaPiCli
    ```

若想使用**图形操作页面**请按第二步操作，由执行 `MaaPiCli` 改为执行 `MFAAvalonia` 程序。

⚠️Gatekeeper 安全提示处理：

在 macOS 10.15 (Catalina) 及更高版本中，Gatekeeper 可能会阻止运行未签名的应用程序。  
如果遇到"无法打开，因为无法验证开发者"等错误，请选择以下任一方案:

```shell
# 方案1：以 MaaPiCli 为例，移除隔离属性（推荐，以实际路径为准）
sudo xattr -rd com.apple.quarantine /usr/local/bin/M9A/MaaPiCli
# 或用户目录版本：xattr -rd com.apple.quarantine ~/M9A/MaaPiCli

# 方案2：添加到 Gatekeeper 白名单
sudo spctl --add /usr/local/bin/M9A/MaaPiCli
# 或用户目录版本：spctl --add ~/M9A/MaaPiCli

# 方案3：一次性处理整个目录
sudo xattr -rd com.apple.quarantine /usr/local/bin/M9A/*
# 或用户目录版本：xattr -rd com.apple.quarantine ~/M9A/*
```

  </blockquote>
</details>

#### Linux

同macOS，下载对应版本的压缩包，解压后运行 `MaaPiCli` 或 `MFAAvalonia` 即可。

***

### 7. 配置 M9A

您可以根据自己的需求配置 M9A 以得到更好的使用体验。

部分配置项在配置错误或未配置时可能会导致 M9A **运行异常**，因此推荐您在开始使用前阅读本章节。

本章将主要介绍如何通过图形界面（MFAAvalonia）配置 M9A 。如果您正在使用命令行版本（MaaPiCli），请参考 [MaaPiCli操作说明](./cli.md) 。

下列演示仅供参考，请以软件实际情况为准。

#### 首次启动

<details open>
  <summary>MFA主页面展示</summary>
  <p></p>
  <blockquote>
    <img src="/images/zh-cn/newbie-main-interface.webp" alt="主界面">
  </blockquote>
</details>

在主界面中，可看到 **`资源类型`** **`任务列表`** **`任务设置`** **`任务说明`** **`连接`** **`日志`** 六大板块。

> [!CAUTION]
> 首次启动 MFA 时， M9A 将进行初始化。在 `日志` 板块显示 “**AgentServer 启动**”后，直到看见 “**任务已全部完成**” 前，请不要点击 `停止任务` 。

M9A 运行任务时，无法修改主界面的部分设置，如 `连接` 板块。此时，可先进入全局设置界面配置。

***

#### M9A 设置界面

点击主界面左下角的齿轮按钮进入 M9A 设置界面。

使用 MFA 更新相关功能的用户应配置 `更新设置` 。有多开和自启需求的用户应配置 `启动设置` 。

**`更新设置`**

- `资源下载源` 用于指定更新时使用的下载源。 `CDK` 指 Mirror 酱 CDK ， `Token` 指 GitHub Personal Access Token 。
- 配置错误时 M9A 将无法正常使用更新有关功能。

<details open>
  <summary>详情</summary>
  <p></p>
  <blockquote>
    <ul>
      <details open>
        <summary>资源下载源</summary>
        <ul>
          <li>默认使用 <code>Mirror 酱</code>。</li>
          <li>未购买 Mirror 酱的用户请改为 <code>GitHub</code>。</li>
        </ul>
      </details>
      <details open>
        <summary>CDK 或 Token</summary>
        <ul>
          <li>通过 Mirror 酱更新的用户应当填写 CDK 。<a href="https://mirrorchyan.com/zh/get-start?rid=MFAAvalonia%5E&source=m9agh-md4" target="_blank">关于 Mirror 酱</a></li>
          <li>通过 GitHub 更新的用户可填写 Token 以提高 Github API 的访问速率限制。<a href="https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#%E5%88%9B%E5%BB%BA-fine-grained-personal-access-token" target="_blank">Token 获取方法1</a> <a href="https://docs.github.com/zh/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#%E5%88%9B%E5%BB%BA-personal-access-token-classic" target="_blank">方法2</a></li>
        </ul>
      </details>
    </ul>
  </blockquote>
</details>

  <details>
    <summary>Github 源速率限制导致更新失败</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/zh-cn/newbie-rate-limit.webp" alt="rate limit exceeded">
      </ul>
    </blockquote>
  </details>

***

**`启动设置`**

- `软件路径` 用于指定模拟器的可执行文件路径。配置错误时 M9A 将无法正确启动模拟器。
- `附加命令` 用于指定模拟器启动时的参数。一般而言， `附加命令` 仅用于配置模拟器多开号。

<details open>
  <summary>详情</summary>
  <p></p>
  <blockquote>
    <ul>
      <details>
        <summary>软件路径</summary>
        <ul>
          <li>MuMu 12 模拟器参考</li>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>路径格式</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>MuMu 12 模拟器<br>5.0 以下</td>
                  <td><code>{安装目录}\shell\MuMuPlayer.exe</code></td>
                </tr>
                <tr>
                  <td>MuMu 12 模拟器<br>5.0 及以上</td>
                  <td><code>{安装目录}\nx_device\12.0\shell\MuMuNxDevice.exe</code></td>
                </tr>
              </tbody>
            </table>
        </ul>
      </details>
      <details>
        <summary>附加命令</summary>
          <ul>
            <li>X 为多开号</li>
            <table>
              <thead>
                <tr>
                <th></th>
                <th>参数格式</th>
                <th>示例</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                <td>MuMu 模拟器</td>
                <td><code>-v X</code></td>
                <td><code>-v 0</code></td>
                </tr>
                <tr>
                <td>雷电模拟器</td>
                <td><code>index=X</code></td>
                <td><code>index=0</code></td>
                </tr>
              </tbody>
            </table>
          </ul>
      </details>
      <details>
        <summary>MuMu 模拟器自动获取路径方法</summary>
          <ol>
            <li>确保桌面有安装 1999 应用的模拟器快捷方式。</li>
            <li>点击 <code>软件路径</code> 输入框右侧图标进入文件选择界面，选择桌面上的 1999 快捷方式，路径将自动填入。</li>
          </ol>
          <ul>
            <img src="/images/zh-cn/newbie-emulator-path-example.webp" alt="image_439">
          </ul>
      </details>
    </ul>
  </blockquote>
</details>

***

#### M9A 主界面

至少配置 **`资源类型`** 和 **`连接`** 。配置错误时将无法正常使用 M9A 。

**`资源类型`**

  <details open>
      <summary>详情</summary>
      <p></p>
      <blockquote>
        <ul>
          <li>需选择模拟器中安装的 1999 区服。</li>
          <li>目前支持：<b>官服</b>、<b>B服</b>、<b>国际服（EN）</b>、<b>国际服（JP）</b>、<b>OPPO服</b>、<b>小米服</b>。</li>
        </ul>
      </blockquote>
    </details>

***

**`连接`**

  M9A 需正确的 ADB 连接才能在**目标**模拟器执行任务。绝大多数情况下，您只需保持有且仅有目标模拟器启动，点击“刷新”即可完成连接。如需手动配置 ADB 参数，请参考 [连接设置](./connection.md)。

  <details>
    <summary>示意图</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/zh-cn/newbie-main-interface-connection.webp" alt="image_440">
      </ul>
    </blockquote>
  </details>

  <details open>
    <summary>详情</summary>
    <p></p>
    <blockquote>
      <ul>
        <details open>
          <summary>当前控制器</summary>
            <ul>
              <li>显示当前连接的 ADB 控制器（模拟器和 ADB 地址）。</li>
            </ul>
        </details>
        <details open>
          <summary>界面按钮说明</summary>
            <ul>
              <li>点击<b>自定义</b>：修改 ADB 参数（一般无需手动修改）。</li>
              <li>点击<b>刷新</b>：重新检测所有已启动模拟器。</li>
              <li><b>连接状态</b>：绿色为已连接。</li>
            </ul>
        </details>
      </ul>
    </blockquote>
  </details>
  
当您使用国际服 PC 端时，只需要点击连接区域的 PC 图标即可自动检测并连接已打开的 PC 端窗口。  
> [!WARNING]
>
> 连接PC时请**以管理员模式**运行M9A，并**不要将游戏窗口最小化**！

***
  <details>
    <summary>示意图</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/zh-cn/newbie-main-interface-connection-pc.webp" alt="PC连接">
      </ul>
    </blockquote>
  </details>

***

**`任务列表`**

  <details>
    <summary>示意图</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/zh-cn/newbie-main-interface-task-lists.webp" alt="image_441">
      </ul>
    </blockquote>
  </details>

  <details open>
    <summary>详情</summary>
    <p></p>
    <blockquote>
      <ul>
        <li>任务名前的复选框用于启用/禁用任务</li>
        <li>右键单击复选框将单次执行该任务</li>
        <li>点击右上角添加任务按钮可添加当前列表不可见任务或重复添加已有任务</li>
        <li>点击任务右侧按钮查看 <b>任务设置</b> 与 <b>任务说明</b></li>
        <li>拖动任务名可调整任务顺序</li>
      </ul>
    </blockquote>
  </details>

>[!IMPORTANT]
>
> 大部分任务需在使用前正确配置，少部分任务还需根据任务说明在特定场景执行。启用任务前，请确保您已阅读并理解了该任务的**任务说明**，并结合实际情况对**任务设置**进行配置。更多关于任务的说明请参阅 [功能介绍](./introduction.md) 。

***

#### 配置文件

##### pip 配置

  M9A 支持通过 `config/pip_config.json` 文件配置 pip 安装相关设置。一般情况下，您无需修改此文件，除非您有特殊需求。

  <details>
    <summary>config/pip_config.json 示例</summary>
    <p></p>
    <blockquote>

  ```jsonc
  {
      "enable_pip_install": true,  // 是否启用 pip 安装，默认 true
      "mirror": "https://pypi.tuna.tsinghua.edu.cn/simple", // 镜像源
      "backup_mirror": "https://mirrors.ustc.edu.cn/pypi/simple"  // 备用镜像源
  }
  ```

  </blockquote>
  </details>

##### 资源热更配置

  M9A 支持通过 `config/hot_update.json` 文件配置部分资源（例如活动开放时间）热更相关设置。

  <details>
    <summary>config/hot_update.json 示例</summary>
    <p></p>
    <blockquote>

  ```jsonc
  {
      "enable_hot_update": true  // 是否启用部分资源热更，默认 true
  }
  ```

  </blockquote>
  </details>

***
