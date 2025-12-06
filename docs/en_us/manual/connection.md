---
order: 3
icon: mdi:plug
---
# Connection Settings

## Auto Detect

M9A can automatically detect ADB provided by **running** emulators and automatically fill in the ADB path, connection address, and connection configuration.

When using the International Server PC client, M9A can automatically detect and connect to **running** game windows.

When detection fails, if you confirm that the emulator and connection address you are using are correct, please try launching M9A with UAC administrator privileges and detect again. If it still fails, please [manually configure](#manual-configuration).

## Manual Configuration

Complete connection settings should include ADB path and ADB address. Other optional settings include touch control mode, emulator multi-instance, ADB extra parameters, etc.

### ADB Path

ADB path refers to the path of the ADB executable file required for M9A to connect to the emulator. ADB executable files are generally provided by emulators, but you can also install Google's ADB yourself.

#### Using ADB Provided by Emulator

Navigate to the emulator's installation path. On Windows, you can right-click the emulator process in Task Manager while it's running and select `Open file location`.

There should be an `.exe` file with `adb` in its name in the top-level or a sub-directory. You can use the search function, then select it.

> [!NOTE]
>
> Some examples:
> `adb.exe` `HD-adb.exe` `adb_server.exe` `nox_adb.exe`

#### Using ADB Provided by Google

[Click to download](https://dl.google.com/android/repository/platform-tools-latest-windows.zip), extract the archive, and then select `adb.exe` from within.

It's recommended to extract it directly into the M9A folder. This allows you to simply enter `.\platform-tools\adb.exe` as the ADB path, and it can be moved together with the M9A folder.

### ADB Address

ADB addresses running on the local machine should be `127.0.0.1:<PortNumber>` or `emulator-<FourDigitNumber>`.

Supported emulators and connection addresses are as follows:

- MuMu Player 12: `127.0.0.1:16384/16416/16448/16480/16512/16544/16576`
- LDPlayer 9: `emulator-5554/5556/5558/5560`, `127.0.0.1:5555/5557/5559/5561`
- BlueStacks 5: `127.0.0.1:5555/5556/5565/5575/5585/5595/5554`
- NoxPlayer: `127.0.0.1:62001/59865`
- MEmu Player: `127.0.0.1:21503`

> [!NOTE]
>
> The '/' above means **or**. Please choose based on your actual situation, don't write them all!

#### Emulator Documentation and Reference Addresses

- [Bluestacks 5](https://support.bluestacks.com/hc/en-us/articles/360061342631-How-to-migrate-your-apps-from-BlueStacks-4-to-BlueStacks-5#%E2%80%9C2%E2%80%9D) `127.0.0.1:5555`
- [MuMu Player Pro](https://mumu.163.com/mac/function/20240126/40028_1134600.html) `127.0.0.1:16384`
- [MuMu Player 12](https://mumu.163.com/help/20230214/35047_1073151.html) `127.0.0.1:16384`
- [LDPlayer 9](https://help.ldmnq.com/docs/LD9adbserver) `emulator-5554`
- [NoxPlayer](https://support.yeshen.com/zh-CN/qt/ml) `127.0.0.1:62001`
- [MEmu Player](https://bbs.xyaz.cn/forum.php?mod=viewthread&tid=365537) `127.0.0.1:21503`

For other emulators, you can refer to [Zhao Qingqing's blog post](https://www.cnblogs.com/zhaoqingqing/p/15238464.html) (Chinese).

#### Getting Multi-Instance Ports

- MuMu 12 Multi-instance manager shows the ports of running instances in the top right corner.
- Bluestacks 5 emulator settings allow viewing the current instance's port.
- _To be supplemented_

> [!NOTE]
>
> Alternative Methods
>
> - Method 1: Use ADB command to view emulator ports
>
>   1. Start **one** emulator and ensure no other Android devices are connected to the computer.
>   2. Open a terminal in the folder containing the ADB executable.
>   3. Execute the following command.
>
>   ```sh
>   # Windows Command Prompt
>   adb devices
>   # Windows PowerShell
>   .\adb devices
>   ```
>
>   Example output:
>
>   ```text
>   List of devices attached
>   127.0.0.1:<PortNumber>   device
>   emulator-<FourDigitNumber>  device
>   ```
>
>   Use `127.0.0.1:<PortNumber>` or `emulator-<FourDigitNumber>` as the connection address.
>
> - Method 2: Find established ADB connections (Windows)
>
>   1. Perform Method 1.
>   2. Press `Win+S`, type `Resource Monitor`, and open it.
>   3. Switch to the `Network` tab. In the `Listening Ports` section, find the emulator process name (e.g., `HD-Player.exe`) in the Image column.
>   4. Note down all listening ports for the emulator process.
>   5. In the `TCP Connections` section, find `adb.exe` in the Image column. The port listed in the `Remote Port` column that matches one of the emulator's listening ports is the emulator's debug port.

### Touch Control Mode

1. [Minitouch](https://github.com/DeviceFarmer/minitouch): An Android touch event injector written in C. It operates `evdev` devices and provides a socket interface for external programs to trigger touch events and gestures. Starting from Android 10, Minitouch is no longer available when SELinux is in `Enforcing` mode.
2. [MaaTouch](https://github.com/MaaAssistantArknights/MaaTouch): A reimplementation of Minitouch in Java by MAA, using the native Android `InputDevice` and adding extra features. Usability on higher Android versions is yet to be tested.
3. Adb Input: Directly calls ADB to use Android's `input` command for touch operations. It offers the highest compatibility but is the slowest.

### M9A and Emulator Multi-Instance

> [!NOTE]
> If you need to run multiple emulator instances simultaneously, you can copy the M9A folder multiple times. Use **different M9A instances**, the **same adb.exe**, and **different connection addresses** to connect to each emulator instance.

### ADB Extra Parameters

This setting only exists in MFAWPF/MFAAvalonia.

**Generally, you don't need to modify this; keep it as `{}`.**

This corresponds to the `"AdbDevice"` `"Config"` field value in `debug/config.json`,
