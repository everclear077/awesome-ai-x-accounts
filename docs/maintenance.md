# 维护说明

## 仓库结构

```text
data/accounts.json          账号和来源的唯一数据源
data/accounts.schema.json   编辑器 JSON Schema
templates/README.md         README 文案和占位符
scripts/catalog.py          校验与静态生成（标准库）
tests/                      有意义的回归测试
assets/banner.svg           原创封面
assets/stats.svg             由真实数据生成的统计图
docs/sources.md              逐账号证据表（生成）
docs/research-backlog.md     不计入正式数量的候选
```

README、来源表、CSV、用户名文本和统计图均由脚本生成。
改变文案用模板，改变条目用 JSON；不要只改生成结果。

## 本地命令

在仓库根目录运行，要求 Python 3.11+：

```sh
python scripts/catalog.py build
python scripts/catalog.py check
python -m unittest discover -s tests -v
git diff --check
```

`build` 校验输入并生成文件；`check` 只读，
检查格式、重复用户名、日期、来源方法、统计、内部文件链接以及生成文件是否过期。
所有路径基于脚本位置解析，换工作目录也可以运行。
CSV 使用 UTF-8 BOM，方便表格工具读取中文；JSON 是供程序处理的主要入口。

## GitHub Actions

推送到 main 和提交 PR 时运行 Catalog CI；也支持手动触发。
CI 没有写入权限、不持久化 checkout 凭据、不需要任何 Secret、
不访问 X、不会自动接受账号推荐。Dependabot 按月提出 Actions 更新 PR。

仓库文件不能自动启用以下 GitHub 设置，维护者可在 Settings 中按需配置：

- 默认分支 main 的保护规则，要求 `Catalog checks` 成功。
- Pull request 审查与 CODEOWNERS review。
- 禁止 force push，合并后自动删除已合并分支。
- Private vulnerability reporting。
- About 描述、topics 和社交分享预览图。

以上是建议，不代表仓库当前已经启用。单维护者仓库可按协作人数调整审查要求。

建议 About 文案：
`Curated AI, LLM, agent & tech accounts on X — organized by topic, with sources. 中英账号精选。`

建议 topics：
`awesome`、`awesome-list`、`artificial-intelligence`、`llm`、
`ai-agents`、`ai-coding`、`twitter`、`x-accounts`。

## 复核与版本

建议每次处理 10–20 个账号，每季度覆盖全部数据。
优先复核身份冲突、迁移提示、用户报错和只有旧帖证据的账号。
只有实际重查时才更新对应来源的 `checked_at`。
版本记录维护在 CHANGELOG.md；README 的统计随数据自动改变。

首次数据建立于 2026-09-13。当前不存在自动化的活跃度评分、
粉丝排名、批量抓取或后台定时身份复核。
