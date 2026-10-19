# 获取 Clash 控制器地址与密钥

本工具通过 Clash 的 **外部控制器（external controller）REST API** 读取节点，
需要知道控制器的地址（默认 `127.0.0.1:9097`）与密钥（secret）。

## Clash Verge Rev

1. 打开 Clash Verge → **设置** → **外部控制**
2. 确认「外部控制」已开启，记下端口（默认 `9097`）
3. 复制密钥（secret）

也可以直接看配置文件：

- Windows：`%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml`
- macOS：`~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`
- Linux：`~/.config/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`

搜索 `external-controller` 与 `secret`：

```yaml
external-controller: 127.0.0.1:9097
secret: your-secret-here
```

## 原版 Clash / 其他 mihomo 内核

在 `config.yaml` 中确认：

```yaml
external-controller: 127.0.0.1:9097
secret: your-secret-here
```

## 验证连通性

```bash
curl -H "Authorization: Bearer <secret>" http://127.0.0.1:9097/version
# {"meta":true,"version":"v1.19.32"}
```

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `HTTP 401` | 密钥错误 | 重新复制 secret；注意不要带引号或空格 |
| `Could not reach Clash controller` | 控制器没开 / 端口不同 | 检查「外部控制」开关与端口 |
| 节点列表为空 | 当前订阅没有真实节点，只有策略组 | 在 Clash 里切换到有节点的配置 |
| 延迟全部失败 | 节点确实挂了 / DNS 解析失败 | 用 `--retry 1` 重试；或换订阅 |
| 地区显示 `UNKNOWN` | 节点名没有地区关键字 | 可在 `clash_export.py` 的 `REGION_RULES` 里补充关键字 |

## 安全提示

- 控制器只监听 `127.0.0.1`，不要改成 `0.0.0.0` 暴露到局域网
- `.clash_secret` 不要提交到公开仓库（已在 `.gitignore` 中排除）
- 密钥泄露时，在 Clash Verge 里重新生成并更新本地文件
