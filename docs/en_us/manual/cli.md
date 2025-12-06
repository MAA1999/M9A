---
order: 4
icon: material-symbols:terminal
---
# MaaPiCli Usage Instructions

## Select ADB

When you download for the first time and there is no configuration, the following interface will appear:

```plaintext
Welcome to use Maa Project Interface CLI!
MaaFramework: v4.0.0

Version: v0.0.1

### Select ADB ###

        1. Auto detect
        2. Manual input

Please input [1-2]:
```

Here, the number after Version indicates the current resource version.

`### Select ADB ###` translates to the current operation being Select ADB (Android Debug Bridge, usually used here to operate emulators)

The following options are listed:

1. Auto detect (recommended, select when the target emulator is running)
2. Manual input (refer to [ADB Path](./connection.md#adb-path) and [ADB Connection Address](./connection.html#adb-address) to fill in)
The following Please input [1-2]: translates to Please input [option range], please select as needed.

Here we enter 1 and press Enter to proceed to the next step.

## Select Device

Following the previous step, selecting auto-detect will lead to this step, displayed as:

```plaintext
Finding device...

## Select Device ##

        1. MuMuPlayer12
                D:/Program Files/Netease/MuMu Player 12/shell/adb.exe
                127.0.0.1:16384

Please input [1-1]:
```

Here, because only one emulator is running, only one option is displayed. Directly enter 1 and press Enter to complete this step.

## Select Resource

Plaintext

```plaintext
### Select resource ###

        1. 官服
        2. B 服
        3. 国际服（EN）
        4. 国际服（JP）

Please input [1-4]:
```

Select the required resource here. This mainly relates to functions that differ between servers, such as Start Game, Bank Purchase, and Event Farming.

## Add Task

Here is where you add tasks, displayed as follows:

```plaintext
### Add task ###

        1. 启动游戏
        2. 收取荒原
        3. 每日心相（意志解析）
        4. 常规作战
        5. 活动刷取
        6. 自动深眠
        7. 自动醒梦
        8. 银行购物
        9. 领取奖励
        10. 轶事派遣
        11. 雨中悬想：迷思海
        12. 切换账号
        13. 关闭游戏
        14. 局外演绎：黄昏的音序
        15. (测试中)推图模式

Please input multiple [1-15]:
```

The main menu is displayed first. Select according to your needs. You can select multiple functions at the same time, like:

```plaintext
Please input multiple [1-15]: 1 2 3 4 5 6 7 8 9 10
```

Then, the options for each task will be displayed for selection.

The following uses selecting "Regular Battle" as an example. After selection, it is displayed as:

```plaintext
## Input option of "作战关卡" for "常规作战" ##

        1. ---按关卡综合效率排序，刷取推荐来源：必要的记录https://www.kdocs.cn/l/cd5MWeCl5bKw ---
        2. 啮咬盒(床下怪物)：7-26 厄险（效率1）
        3. 啮咬盒(银光子弹)：5-19 厄险（效率2）
        4. 啮咬盒：9-3 厄险（效率3）
        5. 盐封曼德拉(狂人絮语)：3-13 厄险（效率1）
        6. 盐封曼德拉(不腐猴爪)：8-17 厄险（效率2）
        7. 盐封曼德拉：9-16 厄险（效率3）
        8. 双头形骨架：4-20 厄险（效率1）
        9. 双头形骨架：9-13 厄险（效率2）
        ...

Please input [1-42]:
```

`## Input option of "作战关卡" for "常规作战" ##` translates to Enter the option for "Battle Stage" of "Regular Battle", select as needed

## Function Menu

After the initial configuration is complete, or if it has been configured before, you will arrive at the current interface, with the following content:

```plaintext
Controller:

        ADB 默认方式
                D:/Program Files/Netease/MuMu Player 12/shell/adb.exe
                127.0.0.1:16384

Resource:

        官服

Tasks:

        - 常规作战
                - 作战关卡: 啮咬盒(床下怪物)：7-26 厄险（效率1）
                - 复现次数: x4
                - 刷完全部体力: Yes
                - 吃全部临期糖: Yes

### Select action ###

        1. Switch controller
        2. Switch resource
        3. Add task
        4. Move task
        5. Delete task
        6. Run tasks
        7. Exit

Please input [1-7]:
```

Displays Controller (current controller, set in device selection), Resource (current resource), Tasks (current list of tasks to be executed).
And provides a function menu (Select action), which are:

1. Switch controller
2. Switch resource
3. Add task
4. Move task
5. Delete task
6. Run tasks
7. Exit

Once you confirm that the Tasks section is configured correctly, you can enter 6 and press Enter to run the tasks.

## Advanced Usage

- Adding the -d parameter in the command line to run will skip the interactive process and directly run the tasks, such as ./MaaPiCli.exe -d
- Version 2.0 and above supports MuMu background keep-alive. It will get the foreground tab of MuMu when running tasks and always use this tab (even if it is switched to the background later).
