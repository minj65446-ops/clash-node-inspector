# 常见问题（FAQ）

## 1. 报 `HTTP 401 Unauthorized` / `invalid secret`

密钥不对。检查：

- 在 Clash Verge 里打开 `设置 → 外部控制`，重新复制密钥
- 密钥不要带引号、空格、换行
- 控制器端口是否与 `--controller` 一致（默认 `127.0.0.1:9097`）
- 如果之前改过 Clash 配置，密钥可能已变化，重新读取

## 2. 报 `Could not reach Clash controller`

说明工具连不上控制器，不是密钥问题：

- 「外部控制」开关是否打开
- 端口是否被占用/修改（`clash-verge.yaml` 里的 `external-controller`）
- 是否在 Docker/WSL 里跑 Clash，地址不是 `127.0.0.1`
- 防火墙是否拦截

验证方法：

```bash
curl -H "Authorization: Bearer <secret>" http://127.0.0.1:9097/version
# 期望返回 {"meta":true,"version":"v1.19.32"}
```

## 3. 节点列表为空

- 当前配置里可能只有策略组（proxy groups），没有真实节点
- 切换到一个有节点的配置再试
- 也可以先在 Clash 界面里确认节点列表是否为空

## 4. 所有节点延迟都失败 / 存活率 0%

- 节点确实挂了（免费公共节点很常见）
- 加 `--retry 1` 重试一次
- 换一个订阅或节点源
- 注意：延迟测试成功 **不等于** 能上网，最终以实际访问结果为准

## 5. 地区显示 `UNKNOWN`

地区识别依赖节点名里的关键字（如 `HK`、`香港`、`Singapore`）。

- 节点名没有地区信息时会显示 `UNKNOWN`
- 可以在 `clash_export.py` 的 `REGION_RULES` 里补充关键字
- 注意：**节点名可能撒谎**（名字写香港、实际出口在芬兰），报告只是按名称推断

## 6. 中文输出乱码 / `UnicodeEncodeError: 'gbk' codec`

Windows 控制台默认 GBK 编码。设置环境变量：

```powershell
$env:PYTHONIOENCODING = "utf-8"
# 或者
chcp 65001
```

`daily_inspect.py` 已经内置处理：调用子进程时会自动设置 UTF-8 环境变量。

## 7. `daily_inspect.py` 退出码 3

表示存活率低于阈值（默认 60%）。这是**告警**，不是崩溃：

- 阈值可调：`--threshold 0.8`
- 退出码：`0` 正常 / `2` 失败 / `3` 低于阈值

## 8. 报告显示节点存活，但实际连不上

延迟测试只测了响应时间，**不保证真实流量能通**。典型情况：

- TCP 握手成功但 TLS 被重置
- 节点限速/限流
- 出口 IP 被目标网站封禁

建议手工验证：

```bash
curl -x http://127.0.0.1:7897 https://www.cloudflare.com/cdn-cgi/trace
```

看 `loc=` 和 `ip=` 是否符合预期。

## 9. 密钥会被上传到仓库吗？

不会。`.clash_secret` 已在 `.gitignore` 中排除；`clash_export.py` 只接收命令行参数或环境变量，不落盘。

## 10. 如何定时自动巡检？

**Windows（任务计划程序）**

- 程序：`python`
- 参数：`daily_inspect.py`
- 起始于：本项目目录

**Linux / macOS（cron）**

```
0 9 * * * cd /path/to/clash-node-inspector && /usr/bin/python3 daily_inspect.py >> reports/cron.log 2>&1
```

## 11. 支持 Clash for Windows / ClashX 吗？

只要内核暴露 **external-controller**（mihomo / Clash Premium 等）就能用：

- Clash Verge Rev：设置 → 外部控制
- ClashX / ClashX Pro：配置里 `external-controller` 与 `secret`
- 原版 Clash：`config.yaml` 里同名配置

---

还有问题？[开一个 Issue](https://github.com/minj65446-ops/clash-node-inspector/issues/new/choose)，附上命令、报错与系统信息。
