---
order: 4
icon: material-symbols:terminal
---
# MaaPiCli 使用

本节将介绍 MaaPiCli 的使用方法（翻译）

## 选择ADB

当您初次下载，没有配置时会出现下面界面：

```plaintext
Welcome to use Maa Project Interface CLI!
MaaFramework: v4.0.0

Version: v0.0.1

### Select ADB ###

        1. Auto detect
        2. Manual input

Please input [1-2]:
```

这里 Version 后跟着的是当前资源版本。  
`### Select ADB ###` 翻译过来是当前操作为 `选择 ADB（Android Debug Bridge，这里一般用来操作模拟器）`。  
后面列出选项：

1. 自动检测（推荐，在目标模拟器启动时选择）
2. 手动输入（参考[ADB 路径](./connection.md#adb-路径)和[ADB 连接地址](./connection.md#adb-地址)填写）

后面 `Please input [1-2]:` 翻译过来是 `请输入 [选项范围]`，请根据需要选择。

这里我们输入 1 后回车，进入下一步。

## 选择设备

紧跟上一步，选择自动检测可到此步骤，显示为：

```plaintext
Finding device...

## Select Device ##

        1. MuMuPlayer12
                D:/Program Files/Netease/MuMu Player 12/shell/adb.exe
                127.0.0.1:16384

Please input [1-1]:
```

这里因为只开了一个模拟器，只显示一条选项，直接输入 1 后回车，完成此步骤

## 选择资源

```plaintext
### Select resource ###

        1. 官服
        2. B 服
        3. 国际服（EN）
        4. 国际服（JP）

Please input [1-4]:
```

这里根据需要的资源进行选择，主要和 `启动游戏`、`银行购买` 和 `活动刷取` 等各个服务器有所区别的功能有关。

## 添加任务

这里是添加任务，显示如下：

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

首先显示的总菜单，根据需求选择，这里可以同时选多个功能，像：

```plaintext
Please input multiple [1-15]: 1 2 3 4 5 6 7 8 9 10
```

后面便会显示每个任务的选项供于选择。

下面以单选常规作战为例，选择后显示：

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

`## Input option of "作战关卡" for "常规作战" ##` 翻译过来指 `输入“常规作战”的“作战关卡”的选项`，根据需要选择即可。

## 功能菜单

初次启动配置完，或者之前配置过的，便会到当前界面，内容如下：

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

展示了 Controller（当前控制器，于选择设备设置）、Resource（当前资源）、Tasks（当前待执行任务列表）。  
并给出功能菜单（Select action），依次为：  

1. 更换控制器
2. 更换资源
3. 添加任务
4. 移动任务
5. 删除任务
6. 运行任务
7. 退出

确定 Tasks 部分配置完成便可在输入 6 并回车后运行任务。

## 进阶使用

- 在命令行中添加 `-d` 参数运行即可跳过交互直接运行任务，如 `./MaaPiCli.exe -d`
- 2.0 版本已支持 mumu 后台保活，会在 run task 时获取 mumu 最前台的 tab，并始终使用这个 tab（即使之后被切到后台了）
