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

debug 与正式包统一走 **Build Android APK**（`macos-latest` + JDK 25 + NDK 29 + Python 3.13）。push / PR 到 `main` 打 debug 包，打 `android-v*` tag 或手动跑 workflow 选 `assemble=release` 出签名包并发布 Release。

改 `Android/`、`agent/`、`tasks/`、`resource/`、`data/`、`locales/`、`config/`、`requirements.txt` 或 `interface.json` 等会触发构建。外壳 release 包固定双 ABI（arm64-v8a + x86_64），CI 会把两个 ABI 的 MaaFramework 和 agent 运行时都备齐。

Release 需要仓库 Secrets：`KEYSTORE_BASE64`、`KEYSTORE_PASSWORD`、`KEY_ALIAS`、`KEY_PASSWORD`。手动跑时可以指定 MaaFramework 的 tag，默认 latest。
