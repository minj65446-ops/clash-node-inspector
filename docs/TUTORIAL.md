# 中文使用教程（v1.1）

面向第一次用的人，按顺序做就能跑通。全程不需要改代码。

## 0. 你会得到什么

一条命令看清手上那批 Clash / mihomo 节点今天哪些还能用，并且能把坏掉的节点从配置文件里摘掉。

## 1. 准备两样东西

**① Python 3.8+**

```bash
python --version
```

没有的话去 https://www.python.org/downloads/ 装，安装时勾上 `Add python.exe to PATH`。

**② Clash 的外部控制器地址和密钥**

Clash Verge Rev：`设置 → 外部控制`，能看到端口（默认 `9097`）和一串密钥。
或者直接看配置文件里的两行：

```yaml
external-controller: 127.0.0.1:9097
secret: 你的密钥
```

> 密钥等价于内核的管理密码，不要提交到仓库、不要贴到聊天里。本项目的 `.gitignore` 已经排除 `.clash_secret`。

## 2. 拿到代码

```bash
git clone https://github.com/minj65446-ops/clash-node-inspector.git
cd clash-node-inspector
python -m unittest discover -s tests      # 可选：确认环境没问题，应当 59 个测试全绿
```

不想装 git 就下载 ZIP 解压，效果一样。

## 3. 第一跑：只看报告，不改任何东西

```bash
python pipeline.py --secret <你的密钥> --test-delay --concurrency 8 --retry 1 --csv --output-dir out
```

输出：

```
导出 20 个节点（存活 15），报告: out/report.md
```

打开 `out/report.md`，看三块：

| 看什么 | 说明 |
| --- | --- |
| 存活率 | 低于 60% 说明这批节点整体不行了，该换订阅 |
| 按地区统计 | 某个地区全灭（0%）通常是整批机器被墙 |
| 推荐节点 | 当前延迟最低的 3 个，可直接手动选 |

## 4. 把密钥存起来，后面不用每次输

```bash
echo <你的密钥> > .clash_secret
```

优先级：`--secret` > 环境变量 `CLASH_SECRET` > `.clash_secret`。

## 5. 每天自动跑一次

Windows 双击 `一键巡检.cmd` 即可；要定时就用「任务计划程序」新建任务：

```
程序：python
参数：daily_inspect.py
起始于：<本项目目录>
```

每天 9 点执行一次即可。它会归档到 `reports/<日期>/`，并更新 `reports/index.md` 趋势表；存活率低于 60% 时退出码为 3。

**建议只让它报告、不让它改配置**——半夜自动改配置，一旦判断失误就是全网断。

## 6. 真正要清理节点时，分两步走

**第一步：先看会删谁，不动手**

```bash
python clash_export.py --test-delay --concurrency 8 --retry 1 \
  --dedupe --profile profiles/free_nodes.yaml --only-alive --max-delay 600 \
  --stats --output nodes.json

python clash_prune.py --profile profiles/free_nodes.yaml --nodes nodes.json --dry-run
```

`--stats` 会把每条节点的剔除原因打到 stderr，`--dry-run` 只打印“删几个节点、删几个组”，不写文件。

**第二步：确认没问题再落地**

```bash
python clash_prune.py --profile profiles/free_nodes.yaml --nodes nodes.json --in-place
```

它会先备份成 `<配置文件>.bak-<时间戳>`，再原地改写。

或者一条命令走完：

```bash
python pipeline.py --test-delay --concurrency 8 --dedupe --only-alive --max-delay 600 \
  --prune-profile profiles/free_nodes.yaml --prune-in-place
```

## 7. 让改动生效

Clash Verge 不会自动重载本地配置文件，两种方式二选一：

- 界面上对这份配置点一次「保存 / 应用」；
- 或者重启 Clash Verge（内核跑在服务里，重启 UI 不断网）。

## 8. 参数速查

| 参数 | 作用 |
| --- | --- |
| `--dedupe` | 归并重复节点：`X` 与 `X (2)`；加 `--profile` 时按 `server:port` 判断 |
| `--only-alive` | 只保留测速成功的 |
| `--max-delay 600` | 延迟上限，超过就剔除（同时剔除不可用节点） |
| `--keep-region HK,JP` | 只留指定地区 |
| `--exclude-region RU` | 排除指定地区 |
| `--stats` | 输出剔除原因 |
| `--dry-run` | 只报告不写文件 |

## 9. 常见问题

- **HTTP 401**：密钥错或内核重启后密钥变了，重新从设置里复制。
- **连不上控制器**：Clash 没启动，或端口被改；`netstat -ano | findstr 9097` 看有没有在监听。
- **地区显示 UNKNOWN**：节点名里没有可识别的地区关键字，只影响统计，不影响测速。
- **退出码 3**：存活率低于阈值，属于“这次结果很差”的告警，不是程序错误。
- 更多见 [FAQ.md](FAQ.md)。
