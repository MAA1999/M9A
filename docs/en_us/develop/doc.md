---
order: 9
icon: jam:write-f
---
# Documentation Writing

> [!IMPORTANT]
> Documentation writing should comply with MarkdownLint standards. Please refer to [MarkdownLint Rules](https://github.com/markdownlint/markdownlint/blob/master/docs/RULES.md). You can use the [VSCode Plugin](https://github.com/DavidAnson/vscode-markdownlint) to assist in writing.
>

## Block Quote

The following introduces the 5 types of Block Quotes used in GitHub:

> [!NOTE]  
> Highlights information that users should take into account, even when skimming.  

> [!TIP]
> Optional information to help a user be more successful.  

> [!IMPORTANT]  
> Crucial information necessary for users to succeed.  

> [!WARNING]  
> Critical content demanding immediate user attention due to potential risks.  

> [!CAUTION]
> Negative potential consequences of an action.  

However, note that [nested Block Quotes will not be rendered by GitHub](https://github.com/orgs/community/discussions/16925#discussioncomment-10195289). For example:

1. First-level Block Quote
2. Second-level Block Quote
   > [!NOTE]
   > Nested Block Quotes will not be rendered by GitHub.

## Images

To add images to the documentation, follow these steps:

1. Upload the image to the public repository [M9A-WEB](https://github.com/MAA1999/M9A-WEB)
2. Select 'Edit', and you will see the path of the image file in the edit interface. Copy this path for later use.
3. Use the `![name](anonymized URL)` syntax to insert the image into the documentation.

> [!NOTE]
> Images, GIFs, and videos uploaded by non-organization members should be smaller than 10MB.  
> [More details](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)
