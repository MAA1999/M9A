---
order: 3
icon: mdi:plug
---
# 连接设置

## 自动检测

M9A 可以自动检测**已启动**模拟器提供的 ADB 并自动填充 ADB 路径、连接地址和连接配置。

使用国际服 PC 端时 M9A 可以自动检测**已启动**的游戏窗口并连接。

检测失败时，若您确定正在使用的模拟器和连接地址正确，请尝试使用 UAC 管理员权限启动 M9A 并再次检测。若仍失败，请[手动配置](#手动配置)。

## 手动配置

完整的连接设置应包括 ADB 路径和 ADB 地址。其他可选设置包括触控模式、模拟器多开、ADB 额外参数等。

### ADB 路径

ADB 路径是指 M9A 连接模拟器所需的 ADB 可执行文件路径。ADB 可执行文件一般由模拟器提供，您也可以自行安装谷歌提供的 ADB。

#### 使用模拟器提供的 ADB

前往模拟器安装路径，Windows 可在模拟器运行时在任务管理器中右键进程点击 `打开文件所在的位置`。

顶层或下层目录中应该会有一个名字中带有 `adb` 的 exe 文件，可以使用搜索功能，然后选择。

> [!NOTE]
>
> 一些例子  
> `adb.exe` `HD-adb.exe` `adb_server.exe` `nox_adb.exe`

#### 使用谷歌提供的 ADB

[点击下载](https://dl.google.com/android/repository/platform-tools-latest-windows.zip)后解压，然后选择其中的 `adb.exe`。

推荐直接解压到 M9A 文件夹下，这样可以直接在 ADB 路径中填写 `.\platform-tools\adb.exe`，也可以随着 M9A 文件夹一起移动。

### ADB 地址

运行在本机的 ADB 地址应该是 `127.0.0.1:<端口号>` 或 `emulator-<四位数字>`。

支持的模拟器及连接地址如下：

- MuMu 模拟器 12：`127.0.0.1:16384/16416/16448/16480/16512/16544/16576`
- 雷电模拟器 9：`emulator-5554/5556/5558/5560`, `127.0.0.1:5555/5557/5559/5561`
- BlueStacks 5：`127.0.0.1:5555/5556/5565/5575/5585/5595/5554`
- 夜神模拟器：`127.0.0.1:62001/59865`
- 逍遥模拟器：`127.0.0.1:21503`

> [!NOTE]
>
> 上面的 `/` 代表**或者**，请根据实际情况填写，不要照搬！

#### 模拟器相关文档及参考地址

- [Bluestacks 5](https://support.bluestacks.com/hc/zh-tw/articles/360061342631-%E5%A6%82%E4%BD%95%E5%B0%87%E6%82%A8%E7%9A%84%E6%87%89%E7%94%A8%E5%BE%9EBlueStacks-4%E8%BD%89%E7%A7%BB%E5%88%B0BlueStacks-5#%E2%80%9C2%E2%80%9D) `127.0.0.1:5555`
- [MuMu 模拟器 Pro](https://mumu.163.com/mac/function/20240126/40028_1134600.html) `127.0.0.1:16384`
- [MuMu 模拟器 12](https://mumu.163.com/help/20230214/35047_1073151.html) `127.0.0.1:16384`
- [雷电模拟器 9](https://help.ldmnq.com/docs/LD9adbserver) `emulator-5554`
- [夜神模拟器](https://support.yeshen.com/zh-CN/qt/ml) `127.0.0.1:62001`
- [逍遥模拟器](https://bbs.xyaz.cn/forum.php?mod=viewthread&tid=365537) `127.0.0.1:21503`

其他模拟器可参考 [赵青青的博客](https://www.cnblogs.com/zhaoqingqing/p/15238464.html)。

#### 获取多开端口

- MuMu 12 多开器右上角可查看正在运行的多开端口。
- Bluestacks 5 模拟器设置内可查看当前的多开端口。
- _待补充_

> [!NOTE]
>
> 备选方案
>
> - 方案 1 : 使用 ADB 命令查看模拟器端口
>
>   1. 启动**一个**模拟器，并确保没有其他安卓设备连接在此计算机上。  
>   2. 在存放有 ADB 可执行文件的文件夹中启动终端。  
>   3. 执行以下命令。  
>
>   ```sh  
>   # Windows 命令提示符  
>   adb devices  
>   # Windows PowerShell  
>   .\adb devices  
>   ```  
>
>   以下为输出内容的例子：  
>
>   ```text  
>   List of devices attached  
>   127.0.0.1:<端口号>   device  
>   emulator-<四位数字>  device  
>   ```
>
>   使用 `127.0.0.1:<端口>` 或 `emulator-<四位数字>` 作为连接地址。
>
> - 方案 2 : 查找已建立的 ADB 连接
>
>   1. 执行方案 1。  
>   2. 按 `徽标键+S` 打开搜索栏，输入 `资源监视器` 并打开。  
>   3. 切换到 `网络` 选项卡，在 `侦听端口` 的名称列中查找模拟器进程名，如 `HD-Player.exe`。  
>   4. 记录模拟器进程的所有侦听端口。  
>   5. 在 `TCP 连接` 的名称列中查找 `adb.exe`，在远程端口列中与模拟器侦听端口一致的端口即为模拟器调试端口。

### 触控模式

1. [Minitouch](https://github.com/DeviceFarmer/minitouch)：使用 C 编写的 Android 触控事件器，操作 `evdev` 设备，提供 Socket 接口供外部程序触发触控事件和手势。从 Android 10 开始，Minitouch 在 SELinux 为 `Enforcing` 模式时不再可用。
2. [MaaTouch](https://github.com/MaaAssistantArknights/MaaTouch)：由 MAA 基于 Java 对 Minitouch 的重新实现，使用安卓原生的 `InputDevice`，并添加了额外特性。高版本 Android 可用性尚待测试。
3. Adb Input：直接调用 ADB 使用安卓的 `input` 命令进行触控操作，兼容性最强，速度最慢。

### M9A 和模拟器多开

> [!NOTE]
> 若需要多开模拟器同时操作，可将 M9A 文件夹复制多份，使用 **不同的 M9A**、**同一个 adb.exe**、**不同的连接地址** 来进行连接。

### ADB 额外参数

此设置仅在 MFAWPF/MFAAvalonia 存在。

**一般来说你不需要修改，保持 `{}` 即可**。

对应 `debug/config.json` 中 `"AdbDevice"` `"Config"` 字段的值,  
