---
order: 1
icon: ri:guide-fill
---
<!-- markdownlint-disable MD033 -->
# Getting Started

## Prerequisites

### 1. Confirm System Version

<div align="center">

| | Windows | macOS | Linux | Android |
| :---: | :---: | :---: | :---: | :---: |
| System Requirements | Windows 10 and above | Self-test | Self-test | Not recommended |
| Environment Setup Required | Yes | Yes | Yes | Yes |
| Emulator Required | Yes | Yes | Emulator or containerized Android | No |
| Usage | GUI or CLI | GUI or CLI | GUI or CLI | CLI |

| | Notes |
| --- | --- |
| Windows Users | In most cases, please download the x86_64 architecture |
| Mac Users | M9A supports both Apple Silicon and Intel chip Mac computers<br>But it's more recommended for Intel chip Mac computers to use Mac's built-in multi-system installation of Windows<br>And use Windows version M9A and emulator |
| Android Users | M9A no longer provides Android version release packages<br>If you are very familiar with mobile phone operations and wish to use Android physical devices, please go to [MaaFramework](https://github.com/MaaXYZ/MaaFramework/) to install it yourself<br>You can refer to [Usage Method](https://github.com/MaaXYZ/MaaFramework/issues/475), and [MAA Documentation](https://maa.plus/docs/en-us/manual/device/android.html)<br>This method is complex and has certain risks, not recommended for beginner players |

</div>

***

### 2. Install Runtime Environment

>[!NOTE]
>
> Users can skip this section and proceed to step 3, after downloading and extracting the file, to run the dependency installation script. If the script fails to install automatically, then refer to this section.

<div align="center">

<table>
    <thead>
        <tr>
            <th rowspan="2"><div align="center">Launch Method</div></th>
            <th colspan="2"><div align="center">Windows</div></th>
            <th colspan="2"><div align="center">macOS</div></th>
            <th colspan="2"><div align="center">Linux</div></th>
        </tr>
        <tr>
            <th><div align="center">CLI (MaaPiCli)</div></th>
            <th><div align="center">GUI (MFAAvalonia)</div></th>
            <th><div align="center">CLI</div></th>
            <th><div align="center">GUI</div></th>
            <th><div align="center">CLI</div></th>
            <th><div align="center">GUI</div></th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><div align="center">Install<br>VCRedist Required</div></td>
            <td colspan="2"><div align="center">Click <a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank">vc_redist.x64</a> to download or install via winget (see below)</div></td>
            <td colspan="4"><div align="center">No</div></td>
        </tr>
        <tr>
            <td><div align="center">Install<br>.NET 10 Required</div></td>
            <td><div align="center">No</div></td>
            <td><div align="center">Go to <a href="https://dotnet.microsoft.com/download/dotnet/10.0" target="_blank">.NET official download page</a> to download the corresponding version or<br>install via winget (see below)</div></td>
            <td><div align="center">No</div></td>
            <td><div align="center"><a href="https://dotnet.microsoft.com/download/dotnet/10.0" target="_blank">.NET official download page</a></div></td>
            <td><div align="center">No</div></td>
            <td><div align="center">Same as Mac</div></td>
        </tr>
        <tr>
            <td><div align="center">Install<br>Python Required</div></td>
            <td colspan="4"><div align="center">Included in package, no other operations needed</div></td>
            <td colspan="2"><div align="center">3.10≤python<3.14</div></td>
        </tr>
    </tbody>
</table>

</div>

#### 1. VCRedist x64

Windows users **must install VCRedist x64**: This is the basic requirement for running M9A (whether it is the command line version or the graphical interface version).

<details>
  <summary>Detailed Installation Methods</summary>
  <p></p>
  <blockquote>
    <ul>
      <li>
        Direct download: Click
        <a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank">vc_redist.x64</a>
        to download and install
      </li>
      <li>
        <code>winget</code> installation: Right-click the Windows Start button, select "Command Prompt" or "PowerShell (Administrator)", then paste the following command in the terminal and press Enter:
        <pre><code>winget install Microsoft.VCRedist.2017.x64</code></pre>
      </li>
    </ul>
  </blockquote>
</details>

#### 2. .NET 10

All users using GUI need to download and install .NET 10 suitable for your system.

<details>
  <summary>Detailed Installation Methods</summary>
  <p></p>
  <blockquote>
    <ul>
      <li>
        Self-download: Click
        <a href="https://dotnet.microsoft.com/download/dotnet/10.0" target="_blank">.NET official download page</a>
        , select the version suitable for your system to download and install.
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
                <td>You need to download</td>
                <td colspan="1">.NET Desktop Runtime</td>
                <td colspan="2">.NET Runtime</td>
              </tr>
              <tr>
                <td>Installer</td>
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
        (Windows users only) <code>winget</code> installation: Right-click the Windows Start button, select "Command Prompt" or "PowerShell (Administrator)", then paste the following command in the terminal and press Enter:
        <pre><code>winget install Microsoft.DotNet.DesktopRuntime.10</code></pre>
      </li>
    </ul>
  </blockquote>
</details>

#### 3. Python

Linux users need to install Python separately.

<details>

<summary>Details</summary>

<p></p>

<blockquote>

- Your system needs to have **Python version ≥ 3.10** installed. This is required for M9A to start and manage its internal environment.
- M9A will automatically create and use an independent virtual environment and install the required Python dependency packages (from `requirements.txt`) when it is run for the first time. You **do not** need to manually create a virtual environment or install these dependencies.

</blockquote>

</details>

***

### 3. Download the Correct Version

M9A download (update) address: [GitHub Releases page](https://github.com/MAA1999/M9A/releases). Click the link, then select the latest version archive suitable for your system in the `Assets` section.

Chinese users can also download at high speed through [MirrorChyan](https://mirrorchyan.com/en/download?rid=M9A&source=m9agh-enmd3).

<div align="center">

| | Windows | macOS | Linux |
| :---: | :---: | :---: | :---: |
| You need to download | `M9A-win-x86_64-vXXX.zip` | `M9A-macos-x86_64-vXXX.tar.gz` or `M9A-macos-aarch64-vXXX.tar.gz`<br>depending on your architecture | `M9A-linux-x86_64-vXXX.tar.gz` or `M9A-linux-aarch64-vXXX.tar.gz`<br>depending on your architecture |

</div>

<details>
  <summary>Method for Mac users to check processor architecture</summary>
  <p></p>
  <blockquote>
    <ol>
      <li>Click the Apple logo in the top-left corner of the screen.</li>
      <li>Select "About This Mac".</li>
      <li>In the window that appears, you can see the processor information.</li>
    </ol>
    <ul>
      <li>If using Intel X86 processor, please download <code>M9A-macos-x86_64-vXXX.tar.gz</code></li>
      <li>If using Apple Silicon series such as M1, M2, etc. ARM architecture processors, please download <code>M9A-macos-aarch64-vXXX.tar.gz</code></li>
    </ul>
  </blockquote>
</details>

***

### 4. Confirm Emulator and Device Support

<div align="center">

| | Windows | macOS | Linux | Android |
| :---: | :---: | :---: | :---: | :---: |
| Emulator Support | Supports mainstream emulators | Supports mainstream emulators | Self-test | / |
| ADB Function Required | Yes | Yes | Yes | Yes |
| Notes |  | [PlayCover is temporarily not supported](https://github.com/MaaXYZ/MaaFramework/issues/405) |  |  |

</div>

For emulator support details, please refer to MAA documentation. **For reference only**, please refer to [MaaFramework](https://github.com/MaaXYZ/MaaFramework) actual support status.

<details>

  <summary>MAA Emulator and Device Support Documentation</summary>

  <p></p>

  <blockquote>

  <div align="center">

  | | Windows | macOS | Linux | Android |
  | -------- | -------- | ------- | ------- | ------- |
  | Reference Documentation | [Windows Emulators](https://maa.plus/docs/en-us/manual/device/windows.html) | If your device has Apple Silicon, please refer to:<br>[Mac emulators running on Apple Silicon platform](https://maa.plus/docs/en-us/manual/device/macos.html#apple-silicon-%E8%8A%AF%E7%89%87)<br>If your device has Intel chip:<br>1. Recommended to use Mac's built-in multi-system to install Windows<br>and refer to Windows section documentation<br>2. Refer to [Mac emulators running on Intel platform](https://maa.plus/docs/en-us/manual/device/macos.html#intel-%E8%8A%AF%E7%89%87) | [Linux Emulators and Containers](https://maa.plus/docs/en-us/manual/device/linux.html) | [Android Physical Devices](<https://maa.plus/docs/en-us/manual/device/android.html>) |

  </div>

  </blockquote>

</details>

***

### 5. Correctly Set the Resolution

M9A supports mainstream emulators and PC clients, but you need to set the resolution of the emulator and PC client to meet the operating requirements. The resolution for the emulator and PC client should be `landscape` `16:9` ratio, with a recommended (and minimum) resolution of `1280x720`. Running errors caused by not meeting this requirement will not be resolved.

#### International Version PC client

Can't change to `16:9` ratio when using the International Version PC client? Use the PC client initialization script.

<details>
  <summary>Details</summary>
  <p></p>
  <blockquote>
    <ul>
    <li>
      <details>
        <summary>Open the script</summary>
          <ol>
            <li>Locate ModifyPCRegistry.bat (Game PC registry modification) in the M9A root directory</li>
            <li>Double-click to run</li>
          </ol>
      </details>
    </li>
    <li>
      <details>
        <summary>Step 1</summary>
          <ol>
            <li>After opening, enter 1 in the command line</li>
            <li>As shown below</li>
          </ol>
          <img src="/images/en-us/newbie-init-script-step1.webp" alt="Step 1">
      </details>
    </li>
    <li>
      <details>
        <summary>Step 2</summary>
          <ol>
            <li>Enter a/b/c/d according to the resolution you want to select</li>
            <li>As shown below</li>
          </ol>
          <img src="/images/en-us/newbie-init-script-step2.webp" alt="Step 2">
      </details>
    </li>
    </ul>
  </blockquote>
</details>

>[!WARNING]
>
> Note that after changing the resolution, the emulator homepage should be horizontal (tablet version), don't select vertical (mobile version)!

***

### 6. Getting Started

M9A supports both command line (MaaPiCli) and graphical interface (MFAAvalonia), but before use, you need to extract the archive correctly and change the in-game display language to Simplified Chinese

> [!IMPORTANT]
> Don't run the program directly from the compression software!

For general users, it's recommended to use M9A through **MFAAvalonia**.

#### Windows

Confirm complete extraction and ensure M9A is extracted to an independent folder. Recommended extraction path like: `D:\M9A`. Except for closing the built-in administrator-approved Administrator account, please do not extract M9A to paths requiring UAC permissions such as `C:\`, `C:\Program Files\`, etc.

- After extraction, run `MaaPiCli.exe` or `MFAAvalonia.exe`

#### macOS

<details>
  <summary>Details</summary>
  <p></p>
  <blockquote>

1. Open terminal, extract the distributed archive:

    **Option 1: Extract to system directory (requires administrator privileges)**

    ```shell
    sudo mkdir -p /usr/local/bin/M9A
    sudo tar -xzf <downloaded M9A archive path> -C /usr/local/bin/M9A
    ```

    **Option 2: Extract to user directory (recommended, no sudo required)**

    ```shell
    mkdir -p ~/M9A
    tar -xzf <downloaded M9A archive path> -C ~/M9A
    ```

2. Enter the extraction directory and run the program:

    ```shell
    cd /usr/local/bin/M9A
    ./MaaPiCli
    ```

If you want to use the **graphical interface**, follow step 2 but execute `MFAAvalonia` instead of `MaaPiCli`.

⚠️Gatekeeper security prompt handling:

In macOS 10.15 (Catalina) and later, Gatekeeper may prevent unsigned applications from running.  
If you encounter errors such as "Cannot open because the developer cannot be verified", please choose one of the following solutions:

```shell
# Solution 1: Take MaaPiCli as an example to remove the quarantine attribute (recommended, subject to the actual path)
sudo xattr -rd com.apple.quarantine /usr/local/bin/M9A/MaaPiCli
# Or user directory version: xattr -rd com.apple.quarantine ~/M9A/MaaPiCli

# Solution 2: Add to Gatekeeper whitelist
sudo spctl --add /usr/local/bin/M9A/MaaPiCli
# Or user directory version: spctl --add ~/M9A/MaaPiCli

# Solution 3: Process the entire directory at once
sudo xattr -rd com.apple.quarantine /usr/local/bin/M9A/*
# Or user directory version: xattr -rd com.apple.quarantine ~/M9A/*
```

  </blockquote>
</details>

#### Linux

Same as macOS, download the corresponding version archive, extract and run `MaaPiCli` or `MFAAvalonia`.

***

### 7. Configure M9A

You can configure M9A according to your needs for a better user experience.

Some configuration items may cause M9A to **run abnormally** when configured incorrectly or not configured, so it's recommended to read this section before starting to use.

This chapter will mainly introduce how to configure M9A through the graphical interface (MFAAvalonia). If you are using the command line version (MaaPiCli), please refer to [MaaPiCli Operation Instructions](./cli.md).

The following demonstrations are for reference only, please refer to the actual software situation.

#### First Launch

<details open>
  <summary>MFA Main Interface Display</summary>
  <p></p>
  <blockquote>
    <img src="/images/en-us/newbie-main-interface.webp" alt="Main Interface">
  </blockquote>
</details>

In the main interface, you can see six major sections: **`Resource Type`** **`Task List`** **`Task Settings`** **`Task Description`** **`Connection`** **`Log`**.

> [!CAUTION]
> When starting MFA for the first time, M9A will initialize. After the `Log` section shows "**AgentServer Started**" until you see "**All tasks completed**", please do not click `Stop Tasks`.

When M9A is running tasks, some settings in the main interface cannot be modified, such as the `Connection` section. At this time, you can first enter the global settings interface to configure.

***

#### M9A Settings Interface

Click the gear button in the lower left corner of the main interface to enter the M9A settings interface.

Users using MFA update-related functions should configure `Update Settings`. Users with multi-instance and auto-start needs should configure `Startup Settings`.

**`Update Settings`**

- `Resource Download Source` is used to specify the download source used for updates. `CDK` refers to MirrorChyan CDK, `Token` refers to GitHub Personal Access Token.
- When configured incorrectly, M9A will not be able to use update-related functions normally.

<details open>
  <summary>Details</summary>
  <p></p>
  <blockquote>
    <ul>
      <details open>
        <summary>Resource Download Source</summary>
        <ul>
          <li>Uses <code>MirrorChyan</code> by default.</li>
          <li>Users who haven't purchased MirrorChyan should change to <code>GitHub</code>.</li>
        </ul>
      </details>
      <details open>
        <summary>CDK or Token</summary>
        <ul>
          <li>Users updating through MirrorChyan should fill in CDK. <a href="https://mirrorchyan.com/en/get-start?rid=MFAAvalonia%5E&source=m9agh-enmd4" target="_blank">About MirrorChyan</a></li>
          <li>Users updating through GitHub can fill in Token to improve GitHub API access rate limits. <a href="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token" target="_blank">Token acquisition method 1</a> <a href="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic" target="_blank">method 2</a></li>
        </ul>
      </details>
    </ul>
  </blockquote>
</details>

  <details>
    <summary>Github source rate limit causing update failure</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/en-us/newbie-rate-limit.webp" alt="rate limit exceeded">
      </ul>
    </blockquote>
  </details>

***

**`Startup Settings`**

- `Software Path` is used to specify the executable file path of the emulator. When configured incorrectly, M9A will not be able to start the emulator correctly.
- `Additional Commands` is used to specify parameters when the emulator starts. Generally speaking, `Additional Commands` is only used to configure emulator multi-instance numbers.

<details open>
  <summary>Details</summary>
  <p></p>
  <blockquote>
    <ul>
      <details>
        <summary>Software Path</summary>
        <ul>
          <li>MuMu 12 Emulator Reference</li>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Path Format</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>MuMu 12 Emulator<br>Below 5.0</td>
                  <td><code>{Installation Directory}\shell\MuMuPlayer.exe</code></td>
                </tr>
                <tr>
                  <td>MuMu 12 Emulator<br>5.0 and above</td>
                  <td><code>{Installation Directory}\nx_device\12.0\shell\MuMuNxDevice.exe</code></td>
                </tr>
              </tbody>
            </table>
        </ul>
      </details>
      <details>
        <summary>Additional Commands</summary>
          <ul>
            <li>X is the multi-instance number</li>
            <table>
              <thead>
                <tr>
                <th></th>
                <th>Parameter Format</th>
                <th>Example</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                <td>MuMu Emulator</td>
                <td><code>-v X</code></td>
                <td><code>-v 0</code></td>
                </tr>
                <tr>
                <td>LDPlayer</td>
                <td><code>index=X</code></td>
                <td><code>index=0</code></td>
                </tr>
              </tbody>
            </table>
          </ul>
      </details>
      <details>
        <summary>MuMu Emulator Automatic Path Acquisition Method</summary>
          <ol>
            <li>Ensure there is a emulator shortcut with 1999 application installed on the desktop.</li>
            <li>Click the icon to the right of the <code>Software Path</code> input box to enter the file selection interface, select the 1999 shortcut on the desktop, and the path will be automatically filled in.</li>
          </ol>
          <ul>
            <img src="/images/en-us/newbie-emulator-path-example.webp" alt="image_439">
          </ul>
      </details>
    </ul>
  </blockquote>
</details>

***

#### M9A Main Interface

At least configure **`Resource Type`** and **`Connection`**. When configured incorrectly, M9A cannot be used normally.

**`Resource Type`**

  <details open>
      <summary>Details</summary>
      <p></p>
      <blockquote>
        <ul>
          <li>You need to select the 1999 server installed in the emulator.</li>
          <li>Currently supports: <b>Official Server</b>, <b>Bilibili Server</b>, <b>International Server (EN)</b>, <b>International Server (JP)</b>, <b>OPPO Server</b>, <b>Xiaomi Server</b>.</li>
        </ul>
      </blockquote>
    </details>

***

**`Connection`**

  M9A requires correct ADB connection to execute tasks on the **target** emulator. In most cases, you only need to keep only the target emulator running and click "Refresh" to complete the connection. If you need to manually configure ADB parameters, please refer to [Connection Settings](./connection.md).

  <details>
    <summary>Illustration</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/en-us/newbie-main-interface-connection.webp" alt="image_440">
      </ul>
    </blockquote>
  </details>

  <details open>
    <summary>Details</summary>
    <p></p>
    <blockquote>
      <ul>
        <details open>
          <summary>Current Controller</summary>
            <ul>
              <li>Shows the currently connected ADB controller (emulator and ADB address).</li>
            </ul>
        </details>
        <details open>
          <summary>Interface Button Descriptions</summary>
            <ul>
              <li>Click <b>Custom</b>: Modify ADB parameters (generally no manual modification required).</li>
              <li>Click <b>Refresh</b>: Re-detect all running emulators.</li>
              <li><b>Connection Status</b>: Green indicates connected.</li>
            </ul>
        </details>
      </ul>
    </blockquote>
  </details>

When using the International Server PC client, simply click the PC icon in the connection area to automatically detect and connect to any open PC client window.  
> [!WARNING]
>
> When connecting to a PC, run M9A in **administrator mode**, and **do not minimize the game window**!

***
  <details>
    <summary>Illustration</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/en-us/newbie-main-interface-connection-pc.webp" alt="connection-pc">
      </ul>
    </blockquote>
  </details>

***

**`Task List`**

  <details>
    <summary>Illustration</summary>
    <p></p>
    <blockquote>
      <ul>
        <img src="/images/en-us/newbie-main-interface-task-lists.webp" alt="image_441">
      </ul>
    </blockquote>
  </details>

  <details open>
    <summary>Details</summary>
    <p></p>
    <blockquote>
      <ul>
        <li>The checkbox before the task name is used to enable/disable tasks</li>
        <li>Right-clicking the checkbox will execute that task once</li>
        <li>Click the add task button in the upper right corner to add tasks not visible in the current list or repeatedly add existing tasks</li>
        <li>Click the button to the right of the task to view <b>Task Settings</b> and <b>Task Description</b></li>
        <li>Drag task names to adjust task order</li>
      </ul>
    </blockquote>
  </details>

>[!IMPORTANT]
>
> Most tasks need to be configured correctly before use, and some tasks also need to be executed in specific scenarios according to task descriptions. Before enabling tasks, please ensure you have read and understood the **Task Description** for that task, and configure **Task Settings** according to actual situations. For more information about tasks, please refer to [Feature Introduction](./introduction.md).

***

#### Settings

##### pip Settings

  M9A supports configuring pip installation related settings through the `config/pip_config.json` file. Generally, you don't need to modify this file unless you have special requirements.

  <details>
    <summary>config/pip_config.json Example</summary>
    <p></p>
    <blockquote>

  ```jsonc
  {
    "enable_pip_install": true,  // Whether to enable pip installation, default true
    "mirror": "https://pypi.tuna.tsinghua.edu.cn/simple",  // Mirror source
    "backup_mirror": "https://mirrors.ustc.edu.cn/pypi/simple"  // Backup mirror sources
  }
  ```

  </blockquote>
  </details>

##### Resource Hot Update Configuration

  M9A supports configuring hot update settings for certain resources (such as activity opening times) via the `config/hot_update.json` file.

  <details>
    <summary>config/hot_update.json Example</summary>
    <p></p>
    <blockquote>

  ```jsonc
  {
    "enable_hot_update": true  // Whether to enable hot update for certain resources, default is true
  }
  ```

  </blockquote>
  </details>

***
