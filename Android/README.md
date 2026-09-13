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

debug 与正式包统一走 **Build Android APK**（`macos-latest` + JDK 25 + NDK 29 + Python 3.13）。push / PR 到 `main` 打 debug 包；打 `v*` tag 或手动跑 workflow 选 `assemble=release` 出签名包并发布 Release。

发布与桌面共用同一批 `v*` tag：一个版本 tag 会同时触发桌面 Release 与 Android 的三个包，两边把资产传进**同一个 GitHub Release**（共用 `release-<ref>` concurrency group 串行，避免并发建 Release；Release 正文与变更日志仍由桌面流程维护）。APK 的 `versionName` / `versionCode` 取自最外层仓库的 `git describe` 与提交数，所以 tag 统一后与应用内自更新的版本比较自动对齐。

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
- **agent 侧**（包里 Python 的 `maa`）按 `requirements.txt` 的 `maafw==X` 走：CI 用 MaaFramework 对应 tag 的绑定源码现打一个 `py3-none-any` 轮子（`Build Android maafw wheel`），再以 `--require <wheel>` 覆盖内核自带的旧版本
- 两边主版本号不一致时 CI 打 warning；手动跑 workflow 时 `maafw_tag` 可覆盖 client 侧版本（填 `latest` 表示取 GitHub 最新正式版）

为什么自己打轮子：公开索引里没有 Android 版 `maafw` 轮子（CI 实测 `maafw==5.13.0` 在 Android tag 下解析不到任何版本），而绑定本身是纯 Python（无 `.so`，原生库由 APK 的 `jniLibs` 提供）。内核（MaaAgentCoreAndroid）只提供 CPython 与 numpy/strenum，所以内核停在 5.12.3 也不影响绑定升到 requirements 的版本——只要上下游没有 breaking change。

Release 需要仓库 Secrets：`KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`。手动跑时可用 `maafw_tag` 指定 MaaFramework 的 tag，留空则按 `maa-project.json` 解析。
