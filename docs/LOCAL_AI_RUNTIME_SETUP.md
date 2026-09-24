# OpenAI 兼容 AI 服务接入

Mail Storyline Tracker 只连接已经运行的 OpenAI 兼容服务，不安装模型、不启动或关闭 `llama-server`，也不管理 CUDA DLL 或显存生命周期。

## 1. 接口要求

服务至少提供：

```text
GET  /v1/models
POST /v1/chat/completions
```

默认配置：

```yaml
ai:
  base_url: ${AI_BASE_URL:-http://127.0.0.1:8080/v1}
  model: ${AI_MODEL:-local-model}
  api_key: ${AI_API_KEY:-}
  remote_enabled: ${AI_REMOTE_ENABLED:-false}
  timeout_seconds: ${AI_TIMEOUT_SECONDS:-300}
  max_tokens: ${AI_MAX_TOKENS:-4096}
  temperature: ${AI_TEMPERATURE:-0}
```

本机私有值写入被 Git 忽略的 `.env`：

```dotenv
AI_BASE_URL=http://127.0.0.1:8080/v1
AI_MODEL=local-model
AI_API_KEY=
AI_REMOTE_ENABLED=false
```

如果 `/v1/models` 返回 401，在 `.env` 中填写服务启动时配置的 API Key。

## 2. 隐私边界

邮件正文可能包含敏感业务信息，因此默认 `AI_REMOTE_ENABLED=false`。此时程序只允许访问：

- `127.0.0.1`
- `localhost`
- `::1`

连接其他主机时会在发送邮件内容前拒绝执行。只有用户明确决定使用远端服务后，才可在本地 `.env` 设置：

```dotenv
AI_REMOTE_ENABLED=true
```

API Key 不得写入 `config.yaml`、日志、HTML、JSON 输出或 Git。

## 3. 模型检查

命令行：

```powershell
python mail_storyline.py check-ai
```

GUI：“AI 梳理与时间线” → “检查 AI 服务”。

检查会读取 `/v1/models`：

- 配置模型存在时直接使用。
- 配置为 `local-model` 且服务只加载一个模型时，自动采用唯一模型 ID。
- 服务返回多个模型且没有配置匹配项时停止并报告可用模型。

## 4. 工作事项请求

执行：

```powershell
python mail_storyline.py analyze
```

程序先在本地按回复头、主题、参与人和时间归并邮件会话，再将以下必要字段发送给模型：

- 本地 `record_id`
- 时间、From、To、Cc 和主题
- 限长后的纯文本正文
- 附件文件名

不会发送本地 `.eml` 路径、邮箱授权码或 API Key。正文单封长度和总输入长度由配置限制。

模型必须返回 JSON，包含事项名称、会话 ID、参与人、首末时间、状态、已完成事项、待办、责任人、截止日期、风险、时间线、来源记录 ID 和总结。无明确证据的责任人、日期或状态必须标记为“待确认”。

输出：

```text
output/storyline.json
output/storyline.html
```

## 5. 附件名称模糊匹配

`python mail_storyline.py target-scan` 会把邮件附件的原始文件名和 `target_file.env` 中的目标事项名称发送给本地模型。模型只判断名称之间是否存在明确对应关系，并返回目标事项、置信度和简短理由。

此步骤不会读取或发送附件正文。低于程序置信度门槛、引用不存在目标或改变原始文件名的结果会被丢弃。每个目标事项保持独立，一个附件可以在确有依据时关联多个目标。

## 6. 常见问题

- `AI 服务要求鉴权`：设置本地 `AI_API_KEY`。
- `无法连接 AI 服务`：确认 `llama-server` 已由其专用运行环境启动，并核对端口。
- `配置模型不可用`：用检查命令查看模型 ID，更新 `AI_MODEL`。
- `远端 AI 默认关闭`：目标不是回环地址；仅在明确接受远端发送邮件内容后启用远端模式。
- `AI 未返回有效 JSON`：降低温度，确认模型遵循 JSON 指令，或适当提高最大输出 Token。
