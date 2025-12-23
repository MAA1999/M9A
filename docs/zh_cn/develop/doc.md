---
order: 8
icon: jam:write-f
---
# 文档编写

::: important
文档编写应符合 MarkdownLint 规范，请参考 [MarkdownLint 规则](https://github.com/markdownlint/markdownlint/blob/master/docs/RULES.md)，可通过[VSCode插件](https://github.com/DavidAnson/vscode-markdownlint)辅助编写。
:::

## 提示容器

M9A 文档使用 [VuePress Theme Plume](https://theme-plume.vuejs.press) 构建，支持丰富的 Markdown 扩展语法。

使用容器语法（`::: type` 格式）创建提示框：

::: note
这是一个注释框
:::

::: info
这是一个信息框
:::

::: tip
这是一个提示框
:::

::: warning
这是一个警告框
:::

::: caution
这是一个危险警告框
:::

::: details
这是一个详情折叠框
:::

### 自定义标题

可以在容器类型后添加自定义标题：

```markdown
::: tip 小提示
这里是提示内容
:::

::: warning 注意事项
请注意这个重要的警告
:::
```

::: tip
嵌套的容器可能无法正确渲染，建议避免使用多层嵌套。
:::

## 图片

为了向文档中添加图片，我们采取以下步骤：

1. 上传图片到公共仓库 [M9A-WEB](https://github.com/MAA1999/M9A-WEB/tree/main/docs/.vuepress/public/images)
   - 将图片放置在对应的子目录中（如 `docs/.vuepress/public/images/develop/`）
   - 图片命名应清晰描述内容，使用小写字母和连字符（如 `pipeline-flow.png`）

2. 构建图片的 URL 路径
   - 公式：`/images/[子目录]/[文件名]`
   - 示例：上传到 `public/images/zh-cn/newbie-init-script-step2.webp`，URL 为 `/images/zh-cn/newbie-init-script-step2.webp`

3. 在文档中使用 Markdown 语法插入图片

```markdown
![新手初始化脚本步骤2](/images/zh-cn/newbie-init-script-step2.webp)
```

::: tip

- 推荐使用 PNG 或 WebP 格式以获得更好的显示效果
- 图片大小建议控制在 500KB 以内
- 为图片添加有意义的 alt 文本（描述）以提升可访问性

:::

## 代码块

### 基础代码块

使用三个反引号包裹代码，并指定语言：

````markdown
```python
def hello():
    print("Hello, World!")
```
````

### 代码块特性

支持以下增强功能：

- **行号显示**：默认启用
- **行高亮**：在语言标识后添加 `{行号}` 或 `{行号范围}`
- **文件名显示**：在语言标识后添加 `:文件名`

示例：

````markdown
```python:example.py {2,4-6}
def hello():
    name = "World"  # 高亮
    message = f"Hello, {name}!"
    print(message)  # 高亮
    print("Done")  # 高亮
    return message  # 高亮
```
````

## 选项卡（Tabs）

使用选项卡组织多种方案或代码示例：

::: tabs
@tab 方案一
这是方案一的内容

@tab 方案二
这是方案二的内容

@tab 代码示例

```python
print("示例代码")
```

:::

如上所示，可以在选项卡内嵌套代码块、图片和其他 Markdown 元素。

## 文件树

展示项目目录结构：

```markdown
::: file-tree
- docs/
  - zh_cn/
    - develop/
      - pipeline.md
      - custom.md
  - en_us/
    - develop/
      - pipeline.md
      - custom.md
- assets/
  - resource/
:::
```

## 更多功能

VuePress Theme Plume 还支持：

- **数学公式**：使用 KaTeX 渲染数学公式
- **图表**：支持 Mermaid、Chart.js、ECharts
- **卡片组件**：链接卡片、图片卡片、仓库卡片
- **步骤容器**：展示操作步骤
- **时间线**：展示时间序列

详细使用方法请参考 [VuePress Theme Plume 官方文档](https://theme-plume.vuejs.press/)
