---
order: 2
icon: ph:question-fill
---
# Frequently Asked Questions (FAQ)

## Software Fails to Run / Crashes / Reports Errors

Most problems can be solved in this section.
They are divided into Download/Installation Issues, Runtime Library Issues, Agent Long Time Wait Issues, Resource Loading Issues, and Connection Issues.
Most issues fall under **Runtime Library Issues** and **Connection Issues**.

### Download/Installation Issues

The complete M9A software package is named in the format "M9A-`Platform`-`Architecture`-`Version`.zip". Others are "parts" that cannot be used alone. Please read carefully.  
In most cases, you need the x64 architecture M9A, meaning you should download `M9A-win-x86_64-vXXX.zip`, not `M9A-win-aarch64-vXXX.zip`.

### Crashes During Runtime

This issue might occur if you have a dedicated graphics card and GPU acceleration is enabled.

> Solution:
>
> Using MaaPiCli: Change the value of the `gpu` field in `config/maa_pi_config.json` to -2 to disable GPU.
>
> Using MFAWPF: In [Settings]-[Performance Settings], uncheck [Enable GPU Acceleration].

### Runtime Library Issues (Windows)

If you encounter the following when opening the software, you need to update the runtime libraries:

1. When using MFA, you see:

    ```plaintext
    MFA encountered a problem
    "Exception has been thrown by the target of an invocation. The constructor for type 'MFAWPF.Views.MainWindow' threw an exception." Line number '14' and line position '24'.
    Unable to load DLL 'MaaToolkit' or one of its dependencies: The dynamic link library (DLL) initialization routine failed. (0x8007045A)
    Details
    System.Windows.Markup.XamlParseException: Exception has been thrown by the target of an invocation. The constructor for type 'MFAWPF.Views.MainWindow' threw an exception. Line number '14' and line position '24'.
    ---> System.DllNotFoundException: Unable to load DLL 'MaaToolkit' or one of its dependencies: The dynamic link library (DLL) initialization routine failed. (0x8007045A)
    ```

2. When using MaaPiCli, you see `Application Error: The application was unable to start correctly`

The above generally indicate runtime library issues. You need to [update the runtime libraries](./newbie.md#_2-install-runtime-environment).

If updating the runtime libraries still doesn't solve the problem, both startup methods **crash immediately**, and no log files are generated in the current directory, it's likely another dependency-related issue.
Please report it on the [project Issues page](https://github.com/MAA1999/M9A/issues).

### Agent Long Time Wait (Windows)

When using a generic UI (such as MFAAvalonia), there is a long period of unresponsiveness or a prompt of `...No such file or directory`, requiring the full package to be downloaded again.

### Resource Loading Issues

When this problem occurs, it prompts **Resource loading failed**.
The solution is to delete the entire folder and then [download](https://github.com/MAA1999/M9A/releases) and install M9A again.

### Connection Issues

When this problem occurs, it prompts **Error occurred while connecting to the emulator**.
There are many reasons for connection failure. Please try the following steps one by one.

#### 1. Confirm ADB and Connection Address are Correct

Refer to [Connection Settings](./connection.md)

> [!TIP]
>
> Make sure you're not connecting to another emulator/device!

#### 2. Close Existing ADB Processes

After closing M9A, check `Task Manager` - `Details` for any processes containing `adb` in their name. If found, end them and try connecting again.

#### 3. Correctly Use Multiple ADB Instances

When ADB versions differ, newly started processes will close older ones. Therefore, if you need to run multiple ADB instances simultaneously (e.g., MAA, Android Studio, Alas, phone assistants), ensure their versions are the same.

#### 4. Change Touch Control Mode

Some emulators (like BlueStacks China, NoxPlayer, etc.) might have older adb versions. Try changing the adb or **changing the touch control mode**.

#### 5. Switch to MaaPiCli

If you fail to connect using MFAWPF, try using MaaPiCli instead. [Usage Guide](./cli.md)

#### 6. Avoid Game Boosters

Some boosters require restarting MAA, ADB, and the emulator after starting or stopping acceleration before connecting again.

If using UU Booster and MuMu 12 together, refer to the [official documentation](https://mumu.163.com/help/20240321/35047_1144608.html).

#### 7. Restart Your Computer

Restarting solves 97% of problems. (Confirmed)

#### 8. Change Emulator

Please refer to [Emulator and Device Support](https://maa.plus/docs/en/manual/device/).
Generally, MuMu12 or LDPlayer 9 are recommended.

## Slow File Download Speed

1. Update using [MirrorChyan](MirrorChyan.md).
2. Ask for help in the community group / search online for related solutions.

## Other Issues

When you are **sure you have read the common issues above** and **tried to solve them yourself without success**, you can:

1. Go to the [project Issues page](https://github.com/MAA1999/M9A/issues) and submit relevant materials **according to the template requirements**.
2. Join the M9A Communication QQ Group: 175638678. Ask your question **after reading the group announcement**.
