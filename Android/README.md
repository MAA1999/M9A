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

改 `interface.json`、`tasks/`、`agent/` 后重新 `installDebug` 即可，不必再指外部路径。换了 `requirements.txt` 再跑一遍 `build_agent_bundle.py`。

升外壳：

```bash
git -C Android/MaaFwApp fetch
git -C Android/MaaFwApp checkout origin/main
git add Android/MaaFwApp
```
