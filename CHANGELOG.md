# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-10-19

首个公开版本。

### 新增

- `clash_export.py`：从 Clash / mihomo 外部控制器导出节点（JSON / CSV）
  - 支持密钥认证（`--secret` / `CLASH_SECRET`）
  - 并发延迟测试（`--concurrency 1..16`）
  - 失败重试（`--retry 0..5`），401 不重试
  - 28 个地区识别，避免 `Russia` → `US` 这类误判
- `proxy_report.py`：节点 JSON → Markdown 质量报告
  - 存活率、按地区统计、中位延迟、Top3 推荐
  - 中位数取整规则：偶数取中间两值平均，四舍五入（远离零）
- `pipeline.py`：一键串联「导出 → 报告」，支持 `--csv`
- `daily_inspect.py`：每日巡检
  - 按日期归档到 `reports/<日期>/`
  - 维护 `history.jsonl`（同日重跑只保留最新）
  - 生成趋势表 `reports/index.md`
  - 存活率低于阈值（默认 60%）时退出码 3
- 39 个自动化验收测试（标准库 `unittest` + 内置假控制器）
- 文档：`README.md`、`docs/SETUP.md`、`CONTRIBUTING.md`

### 已知限制

- 免费公共节点质量波动大，报告仅反映测试时刻的状态
- 控制器只支持本机访问（`127.0.0.1`），不支持远程
- 地区识别依赖节点名关键字，未命中时显示 `UNKNOWN`

[1.0.0]: https://github.com/minj65446-ops/clash-node-inspector/releases/tag/v1.0.0
