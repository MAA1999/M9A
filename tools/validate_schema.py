#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path
from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import ValidationError

try:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012, DRAFT7

    HAS_REFERENCING = True
except ImportError:
    # 如果没有 referencing 库，回退到旧的 RefResolver
    from jsonschema import RefResolver

    HAS_REFERENCING = False


def strip_jsonc_comments(text):
    """
    移除 JSONC 注释，保持 JSON 结构完整
    """
    # 状态机：0=正常, 1=字符串中, 2=转义字符
    result = []
    state = 0
    i = 0

    while i < len(text):
        char = text[i]

        if state == 0:  # 正常状态
            if char == '"':
                result.append(char)
                state = 1
                i += 1
            elif i + 1 < len(text) and text[i : i + 2] == "//":
                # 单行注释，跳到行尾
                while i < len(text) and text[i] != "\n":
                    i += 1
                if i < len(text):
                    result.append("\n")  # 保留换行
                    i += 1
            elif i + 1 < len(text) and text[i : i + 2] == "/*":
                # 多行注释，跳到 */
                i += 2
                while i + 1 < len(text) and text[i : i + 2] != "*/":
                    if text[i] == "\n":
                        result.append("\n")  # 保留换行以维持行号
                    i += 1
                i += 2  # 跳过 */
            else:
                result.append(char)
                i += 1
        elif state == 1:  # 字符串中
            result.append(char)
            if char == "\\":
                state = 2
            elif char == '"':
                state = 0
            i += 1
        elif state == 2:  # 转义字符
            result.append(char)
            state = 1
            i += 1

    return "".join(result)


def load_jsonc(file_path):
    """加载 JSONC 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 移除注释
    clean_content = strip_jsonc_comments(content)

    try:
        return json.loads(clean_content)
    except json.JSONDecodeError as e:
        print(f"JSON decode error in {file_path}: {e}")
        # 调试：保存清理后的内容
        debug_file = Path(tempfile.gettempdir()) / f"debug_{Path(file_path).name}"
        with open(debug_file, "w") as f:
            f.write(clean_content)
        print(f"Cleaned content saved to {debug_file}")
        raise


def get_validator_class(schema):
    """根据 schema 的 $schema 字段选择合适的验证器"""
    schema_uri = schema.get("$schema", "")

    if "draft-07" in schema_uri or "draft/07" in schema_uri:
        return Draft7Validator
    elif "2020-12" in schema_uri:
        return Draft202012Validator
    else:
        # 默认使用 2020-12
        return Draft202012Validator


def validate_file(file_path, validator):
    """验证单个文件"""
    try:
        data = load_jsonc(file_path)
        errors = list(validator.iter_errors(data))

        if errors:
            print(f"\n❌ Validation failed for {file_path}:")
            print(f"   Found {len(errors)} error(s):")
            for idx, error in enumerate(errors[:10], 1):
                path = "/" + "/".join(str(p) for p in error.path) if error.path else "/"
                print(f"   {idx}. {path}: {error.message}")
            return False

        print(f"✓ {file_path}")
        return True
    except Exception as e:
        print(f"\n❌ Error validating {file_path}: {e}")
        return False


def create_validator(schema, schema_store, base_uri=None):
    """创建 validator，使用新的 referencing API 或回退到 RefResolver"""
    ValidatorClass = get_validator_class(schema)

    if HAS_REFERENCING:
        # 使用新的 referencing API
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012, DRAFT7
        import referencing.retrieval

        # 根据 schema 类型选择规范
        spec = DRAFT202012 if ValidatorClass == Draft202012Validator else DRAFT7

        # 创建一个函数来检索 schema - 用于解析相对引用
        @referencing.retrieval.to_cached_resource()
        def retrieve(uri):
            if uri in schema_store:
                return schema_store[uri]
            raise referencing.exceptions.NoSuchResource(ref=uri)

        # 构建 registry
        registry = Registry(retrieve=retrieve)

        # 为每个 schema 添加资源，使用其 file URI 作为标识
        for uri, schema_content in schema_store.items():
            resource = Resource.from_contents(
                schema_content, default_specification=spec
            )
            registry = registry.with_resource(uri, resource)

        # 如果提供了 base_uri，我们需要将其作为主 schema 的标识
        if base_uri:
            main_resource = Resource.from_contents(schema, default_specification=spec)
            registry = registry.with_resource(base_uri, main_resource)

        return ValidatorClass(schema, registry=registry)
    else:
        # 回退到旧的 RefResolver
        schema_uri = base_uri
        if schema_uri is None:
            for uri, content in schema_store.items():
                if content == schema:
                    schema_uri = uri
                    break

        if schema_uri is None:
            schema_uri = "file:///schema.json"

        resolver = RefResolver(base_uri=schema_uri, referrer=schema, store=schema_store)
        return ValidatorClass(schema, resolver=resolver)


def main():
    all_valid = True

    # 加载所有 schema 文件
    schema_dir = Path("deps/tools").resolve()
    schema_store = {}
    base_uri = schema_dir.as_uri() + "/"

    print("Loading schemas...")
    for schema_file in schema_dir.glob("*.json"):
        try:
            schema = load_jsonc(schema_file)
            # 使用完整的 file URI 作为 key（用于解析相对引用）
            file_uri = schema_file.as_uri()
            # 也保存相对路径格式（RefResolver 会将 ./file.json 解析为完整 URI）
            resolved_relative_uri = base_uri + schema_file.name

            schema_store[file_uri] = schema
            schema_store[resolved_relative_uri] = schema
        except Exception as e:
            print(f"Warning: Failed to load schema {schema_file}: {e}")

    # 加载并创建 pipeline validator
    pipeline_schema = load_jsonc("deps/tools/pipeline.schema.json")
    pipeline_schema_uri = (schema_dir / "pipeline.schema.json").as_uri()
    schema_store[pipeline_schema_uri] = pipeline_schema

    pipeline_validator = create_validator(
        pipeline_schema, schema_store, base_uri=pipeline_schema_uri
    )

    print("Validating pipeline resources...")
    # 验证 pipeline 资源文件
    for file_path in Path("assets/resource/base").rglob("*.json"):
        if not validate_file(file_path, pipeline_validator):
            all_valid = False

    for file_path in Path("assets/resource/base").rglob("*.jsonc"):
        if not validate_file(file_path, pipeline_validator):
            all_valid = False

    print("\nValidating interface files...")
    # 验证 interface 文件
    if Path("assets/interface.json").exists():
        interface_schema = load_jsonc("deps/tools/interface.schema.json")
        interface_schema_uri = (schema_dir / "interface.schema.json").as_uri()
        schema_store[interface_schema_uri] = interface_schema

        interface_validator = create_validator(
            interface_schema, schema_store, base_uri=interface_schema_uri
        )
        if not validate_file("assets/interface.json", interface_validator):
            all_valid = False

    if all_valid:
        print("\n✅ All validations passed!")
        sys.exit(0)
    else:
        print("\n❌ Some validations failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
