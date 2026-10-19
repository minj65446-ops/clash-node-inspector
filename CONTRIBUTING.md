# 贡献指南

感谢你愿意改进这个项目！下面是参与方式，都很轻量。

## 你可以帮忙的事

- 🐛 **报告问题**：用 [bug 模板](.github/ISSUE_TEMPLATE/bug_report.md) 开 issue，附上命令、报错、系统信息
- 💡 **提建议**：用 [功能模板](.github/ISSUE_TEMPLATE/feature_request.md) 描述你想要的场景
- 📖 **改文档**：错别字、解释不清、示例过时，欢迎直接 PR
- 🔧 **写代码**：修 bug、加功能，请先开 issue 对齐再提 PR，避免白做
- 🌍 **测兼容**：在别的 Clash 内核 / 系统上跑一下，报告结果

## 开发环境

```bash
git clone https://github.com/minj65446-ops/clash-node-inspector.git
cd clash-node-inspector
python -m unittest discover -s tests -v   # 39 个测试，应该全绿
```

只依赖 Python 3.8+ 标准库，**不要引入第三方依赖**（这是项目的核心约束）。

## 代码约定

- 只用标准库；不新增依赖
- 中文注释 + 英文标识符，命令/参数用英文
- 输出到 stdout/stderr 的错误信息保持中文、可读
- **不要修改 `tests/` 里已有断言**；新增行为请新增测试
- 提交前跑一遍全部测试

## 提 PR 的流程

1. Fork 仓库到自己账号
2. 建分支（例如 `fix/timeout` 或 `feat/csv-export`）
3. 改代码 + 加/改测试
4. 本地跑 `python -m unittest discover -s tests -v`
5. 提 PR，说明：改了什么、为什么改、我怎么验证

## 报告 bug 时请附上

- 运行命令（密钥请打码）
- 完整报错信息
- Python 版本、操作系统
- 使用的 Clash 内核与版本（`/version` 接口返回）

## 行为准则

保持友善、就事论事。对事不对人，欢迎新人提问。
