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

包名与 MaaFW 版本都由 `tools/android-packaging.mjs` 解析（放在脚本里而不是 workflow 内联，是为了可单测、也方便别的项目复用；用 Node 而非 Python 是刻意的——纯 pipeline 项目不引入 Python）：资产前缀取 `maa-project.json` 的 `project.displayName`（不可用时退回 `slug`），MaaFW tag 取子模块内核的 `CORE_TAG`。

发布与桌面共用同一批 `v*` tag：一个版本 tag 会同时触发桌面 Release 与 Android 的三个包，两边把资产传进**同一个 GitHub Release**（共用 `release-<ref>` concurrency group 串行，避免并发建 Release；Release 正文与变更日志仍由桌面流程维护）。APK 的 `versionName` / `versionCode` 取自最外层仓库的 `git describe` 与提交数，所以 tag 统一后与应用内自更新的版本比较自动对齐。

改 `Android/`、`agent/`、`tasks/`、`resource/`、`data/`、`locales/`、`config/`、`requirements.txt` 或 `interface.json` 等会触发构建。

release 时跑三个 job，出三个包：

| job | 资产 | 内容 |
| --- | --- | --- |
| `build` | `M9A-<tag>-universal.apk` | 双 ABI 通用包 |
| `abi-split`（arm64-v8a） | `M9A-<tag>-arm64-v8a.apk` | 只铺 arm64 的 MaaFramework 与 agent 运行时 |
| `abi-split`（x86_64） | `M9A-<tag>-x86_64.apk` | 同上，x86_64 |

`abi-split` 每个包只建自己的那份运行时（`build_agent_bundle.py --abi <abi>`）并写 `build.releaseAbi=<abi>`；debug 包同理只建 arm64。配方里**不写死 `abi`**，外壳按 `agent-dist` 里实际存在的运行时打包，所以单 ABI 包里连 `bundle.zip` 也只有一份运行时，体积约为 universal 的一半。应用内更新优先选本机 ABI 的资产、选不到才回退 universal，所以单 ABI 包的 ABI 标记必须保留，而 universal 包不能带任何标记。

MaaFW 版本以**内核（MaaAgentCoreAndroid）为准**：

- APK 里的 Python 绑定（`maa`）就是内核自带的那个版本；公开索引没有 Android 版 `maafw` 轮子，`requirements.txt` 的 `maafw==X` 在 Android 上不生效（`build_agent_bundle.py` 会按 `core ships …` 丢弃它）
- 所以 **client 侧（`jniLibs/*.so`）跟着内核版本走**：CI 从子模块 `build_agent_bundle.py` 的 `CORE_TAG` 解析出版本并据此铺 MaaFramework，保证 APK 里 client 与 agent 同版本
- 与 `requirements.txt` 或 `maa-project.json` 声明的版本不一致时 CI 打 warning（当前内核 5.12.3，桌面侧已到 5.13.0）
- 手动跑 workflow 时 `maafw_tag` 仍可覆盖 client 侧（会破坏前后一致，一般不用）

内核更新后随子模块 `CORE_TAG` 一起跟上即可：换子模块 pointer → CI 的 tag 与缓存键都会跟着变，不需要额外步骤。

发布还会把三个包分别推到 MirrorChyan 的 `M9A_exec`（`mirrorchyan` job，排在 `release` 之后，因此 Release 里三个 APK 都已就位；只在 `MAA1999` 仓库的 `v*` tag 上跑）：universal → `arch: any`，arm64-v8a → `arch: arm64`，x86_64 → `arch: x64`。应用内更新因此查的是这条「可执行包」流——配方里的 `update.mirrorchyanRid: M9A_exec` 会压过 PI 的 `mirrorchyan_rid`（后者是桌面资源包）。

Release 需要仓库 Secrets：`KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`，以及 `MirrorChyanUploadToken`。手动跑时可用 `maafw_tag` 指定 MaaFramework 的 tag，留空则按 `maa-project.json` 解析。
