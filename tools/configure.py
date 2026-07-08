import shutil
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent


def configure_ocr_model():
    source = project_root / "MaaCommonAssets" / "OCR" / "ppocr_v4" / "zh_cn"
    target = project_root / "resource" / "base" / "model" / "ocr"
    print(f"Copying OCR models from {source} to {target}")
    shutil.copytree(source, target, dirs_exist_ok=True)
    print("Done")


if __name__ == "__main__":
    configure_ocr_model()
