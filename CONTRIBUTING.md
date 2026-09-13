# 参与贡献

欢迎推荐账号、修正用户名、补充来源和改善阅读体验。
请先阅读 [收录标准](docs/curation-policy.md) 和 [行为准则](CODE_OF_CONDUCT.md)。
使用 AI 辅助时，还应阅读 [AGENTS.md](AGENTS.md)。

## 推荐与纠错

通过 [账号推荐表单](https://github.com/everclear077/awesome-ai-x-accounts/issues/new?template=account.yml)
提交名字、X 链接、主题、具体推荐理由和可核对的第一方来源。
自荐可以提交，请说明与账号的关系。收录不收费，也不承诺合并。

来源不充分的候选进入 [待核对清单](docs/research-backlog.md)，不计入正式数量。
更名、停止更新、移除请求使用
[纠错表单](https://github.com/everclear077/awesome-ai-x-accounts/issues/new?template=correction.yml)。

## 提交一个 PR

1. Fork 仓库，从 `main` 创建小范围分支，例如 `data/add-agent-evals`。
2. 修改 `data/accounts.json`，每个账号只放一个主分类，至少提供一条第一方证据。
3. 描述使用原创中文，聚焦读者能看到什么；不要填写动态职务、粉丝数或营销排名。
4. 运行下面的检查，把生成文件一并提交。
5. 使用 PR 模板解释变化和核验方式，披露未解决的疑点。

```sh
python scripts/catalog.py build
python scripts/catalog.py check
python -m unittest discover -s tests -v
git diff --check
```

需要 Python 3.11 或更新版本；无需安装第三方依赖。Windows 可用 `py -3` 替代 `python`。

## Git 约定

- 分支：`data/<topic>`、`fix/<topic>`、`docs/<topic>`、`chore/<topic>`。
- 提交：Conventional Commits，如 `feat(data): add evaluation researchers`、
  `fix(data): update renamed handle`、`docs: improve onboarding`。
- 每个 PR 保持一个清晰目的，不混入无关格式化、工具配置或依赖升级。
- 不直接修改生成文件，不提交本地日志、缓存、凭据。
- 合并前通过 CI，由维护者检查来源与 diff；建议使用 squash merge。
  仓库设置是否强制执行，参见 [维护说明](docs/maintenance.md)。

项目沿用 [MIT 许可证](LICENSE)。贡献者应确保提交的描述和图片有权分发；
被链接网站、姓名、商标和原帖仍属于各自权利人。
