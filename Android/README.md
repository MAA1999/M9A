# Android 客户端

外壳是 [MaaFwApp](https://github.com/Aliothmoon/MaaFwApp) 子模块，资源和 agent 用本仓库的树，改完直接出包。

## 首次

```bash
git submodule update --init --recursive Android/MaaFwApp
python Android/MaaFwApp/scripts/setup_maa_framework.py --abi arm64-v8a
python Android/MaaFwApp/scripts/build_agent_bundle.py \
    --out Android/agent-dist \
    --requirements requirements.txt \
    --exclude pillow --require pillow==11.0.0 \
    --extra-index-url https://chaquo.com/pypi-13.1/
```

OCR 模型由 `MaaCommonAssets` 子模块提供、不进 git，同步机制与桌面端一致（由 `maa-project.json` 的 `ocr` 字段驱动）。本地没跑过桌面端同步的话先执行：

```bash
pnpm dlx create-maa-project@latest --update ocr-models
```

在 `Android/MaaFwApp/local.properties` 里写（不进 git）：

```properties
sdk.dir=<Android SDK>
pi.profile=../profile.yaml
build.debugAbi=arm64-v8a
```

## 出包

```bash
./Android/MaaFwApp/gradlew -p Android/MaaFwApp :app:installDebug
```

改 `interface.json`、`tasks/`、`agent/` 后重新 `installDebug` 即可，不必再指外部路径。换了 `requirements.txt` 再跑一遍 `build_agent_bundle.py`。本地出 release 包时 `setup_maa_framework.py` 要用 `--abi all`、`build_agent_bundle.py` 要加 `--abi x86_64`，否则 x86_64 上会缺运行时。

升外壳：

```bash
git -C Android/MaaFwApp fetch
git -C Android/MaaFwApp checkout origin/main
git add Android/MaaFwApp
```

## CI

debug 与正式包统一走 **Build Android APK**（`macos-latest` + JDK 25 + NDK 29 + Python 3.13）。push / PR 到 `main` 打 debug 包；打 `android-v*` tag 或手动跑 workflow 选 `assemble=release` 出签名包并发布 Release。

改 `Android/`、`agent/`、`tasks/`、`resource/`、`data/`、`locales/`、`config/`、`requirements.txt` 或 `interface.json` 等会触发构建。

release 时跑三个 job，出三个包：

| job | 资产 | 内容 |
| --- | --- | --- |
| `build` | `M9A-<tag>-universal.apk` | 双 ABI 通用包 |
| `abi-split`（arm64-v8a） | `M9A-<tag>-arm64-v8a.apk` | 只铺 arm64 的 MaaFramework 与 agent 运行时 |
| `abi-split`（x86_64） | `M9A-<tag>-x86_64.apk` | 同上，x86_64 |

`abi-split` 会按本 ABI 生成 `Android/profile-<abi>.yaml`（只收窄 `agent.abi`）并写 `build.releaseAbi=<abi>`：单 ABI 包里连 `bundle.zip` 也只有一份运行时，体积约为 universal 的一半。应用内更新优先选本机 ABI 的资产、选不到才回退 universal，所以单 ABI 包的 ABI 标记必须保留，而 universal 包不能带任何标记。

MaaFW 版本分工与桌面一致：

- **client 侧**（APK 里的 `jniLibs/*.so`）按 `maa-project.json` 的 `maafw.channel` / `maafw.version` 解析：`version` 留空时按通道取最新，`beta` 通道收预发布
- **agent 侧**（包里 Python 的 `maa`）按 `requirements.txt` 的 `maafw==X` 安装，用 `--require` 覆盖内核（MaaAgentCoreAndroid）自带的旧版本
- 两边主版本号不一致时 CI 打 warning；手动跑 workflow 时 `maafw_tag` 可覆盖 client 侧版本（填 `latest` 表示取 GitHub 最新正式版）

内核只提供 CPython 与 numpy/strenum 等基础包，它的 `maa` 版本不再决定 Android 的绑定版本；若目标版本在 Android 索引里没有可用轮子，pip 阶段会直接失败，不会静默退回旧版本。

Release 需要仓库 Secrets：`KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`。手动跑时可以指定 MaaFramework 的 tag，默认 latest。
