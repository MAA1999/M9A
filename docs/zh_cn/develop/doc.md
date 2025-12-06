---
order: 9
icon: jam:write-f
---
# 文档编写

> [!IMPORTANT]
> 文档编写应符合 MarkdownLint 规范，请参考 [MarkdownLint 规则](https://github.com/markdownlint/markdownlint/blob/master/docs/RULES.md)，可通过[VSCode插件](https://github.com/DavidAnson/vscode-markdownlint)辅助编写。
>

## Block Quote

接下来介绍 Github 5种 Block Quote 的用法：

> [!NOTE]  
> Highlights information that users should take into account, even when skimming.  
> 突出显示用户应考虑的信息，即使在浏览时也是如此。

> [!TIP]
> Optional information to help a user be more successful.  
> 帮助用户取得更大成功的可选信息。

> [!IMPORTANT]  
> Crucial information necessary for users to succeed.  
> 用户成功所需的重要信息。

> [!WARNING]  
> Critical content demanding immediate user attention due to potential risks.  
> 由于存在潜在风险，需要用户立即关注的关键内容。

> [!CAUTION]
> Negative potential consequences of an action.  
> 操作的潜在负面后果。

不过需要注意，[嵌套的 Block Quote 不会被 github 渲染](https://github.com/orgs/community/discussions/16925#discussioncomment-10195289)。像下面这样：

1. 第一层 Block Quote
2. 第二层 Block Quote
   > [!NOTE]
   > 嵌套的 Block Quote 不会被 github 渲染。

## 图片

为了向文档中添加图片，我们采取以下步骤：

1. 上传图片到公共仓库 [M9A-WEB](https://github.com/MAA1999/M9A-WEB)  
2. 选择'Edit'，在编辑界面中看到图片文件的路径，将该路径复制备用
3. 在文档中使用 `![name](anonymized URL)` 语法插入图片

> [!NOTE]
> 非组织成员上传的图片、GIF、视频应小于10MB  
> [更多详细信息](https://docs.github.com/zh/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)
