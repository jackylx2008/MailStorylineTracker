# Mail Storyline Tracker

从 126.com 指定邮箱文件夹读取邮件，按发件人、收件人/Cc、主题和正文关键词筛选，将匹配邮件增量归档到本地，再调用已经运行的 OpenAI 兼容 AI 服务生成工作事项和往来时间线。

第一阶段包含：

- 126.com IMAP 登录、客户端 `ID`、只读文件夹枚举与连接检查。
- 多文件夹、日期范围、发件人、收件人/Cc 和关键词筛选。
- `any`（任一组命中）及 `all`（所有已配置组命中）模式。
- 基于 `UIDVALIDITY + UID`、Message-ID、内容 SHA-256 和处理状态的 JSON 增量记录。
- 原始 `.eml`、附件、邮件结构化 JSON/JSONL 与 HTML 审核页。
- 基于邮件回复头、规范化主题、参与人和时间接近度的会话归并。
- 通过现有 OpenAI 兼容服务生成事项、参与人、状态、已完成、待办、责任人、截止日期、风险、来源及时间线。
- 从本地 `target_email.env`、`target_keyword.env`、`target_file.env` 读取专项追踪范围，以联系人、关键词、AI 模糊附件名任一命中的方式扩大召回。
- 将每个目标附件事项独立呈现在同一个可搜索、可展开折叠的思维导图式 HTML 中。
- Tkinter GUI、CLI、共享日志、进度和安全取消。

项目不会删除、移动、标记已读或修改服务器邮件。IMAP 文件夹始终以只读方式打开。

## 环境准备

建议使用 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写 126 邮箱地址和客户端授权码，不要填写网页登录密码：

```dotenv
MAIL_IMAP_USER=your-account@126.com
MAIL_IMAP_PASSWORD=your-126-client-authorization-code
MAIL_IMAP_SUPPORT_EMAIL=support@example.invalid
```

`.env` 与 `common.env` 都受支持；如果两者同时存在，`.env` 中的值优先。已经存在的进程环境变量优先于两个文件。两者都被 Git 忽略。

## 筛选配置

默认设置位于 `config.yaml`，机器差异通过 `.env` 覆盖。数组使用 JSON 格式：

```dotenv
MAIL_FOLDERS_JSON=["INBOX","已发送"]
MAIL_FILTER_SENDERS_JSON=["sender@example.com","example.org"]
MAIL_FILTER_RECIPIENTS_JSON=["team@example.com"]
MAIL_FILTER_KEYWORDS_JSON=["项目名","合同","验收"]
MAIL_FILTER_MATCH_MODE=any
MAIL_SINCE=2024-01-01
MAIL_BEFORE=
```

- `any`：发件人组、收件人组、关键词组中任一已配置条件命中即可。
- `all`：所有已配置条件组都必须命中；组内多个值仍是任一值命中。
- 未配置任何地址或关键词时，日期范围内邮件全部匹配。
- `before` 遵循 IMAP 语义，不包含填写日期当天。

GUI 中的修改只影响当前运行，不会改写配置文件。

## 目标附件沟通链路

复制三个脱敏模板并填写本地业务配置：

```powershell
Copy-Item target_email.env.example target_email.env
Copy-Item target_keyword.env.example target_keyword.env
Copy-Item target_file.env.example target_file.env
```

三个文件均采用“一行一个值”的格式：

- `target_email.env`：需要关注的邮件地址或地址片段，检查 From、To、Cc。
- `target_keyword.env`：在主题、正文和附件名中查找的关键词。
- `target_file.env`：每行是一个必须独立输出的附件事项；实际附件名由本地 AI 进行语义模糊匹配。

专项扫描采用：

```text
目标联系人命中 OR 目标关键词命中 OR 目标附件名命中
```

登录后会枚举并扫描账号下全部可选择的文件夹。附件 AI 只接收文件名，不读取附件正文。目标附件所在邮件作为时间线种子，再通过标准邮件回复头、规范化主题、参与人和时间关系补齐同一沟通链路。

运行：

```powershell
python mail_storyline.py target-scan
```

详细规则见 [docs/TARGET_ATTACHMENT_TRACKING.md](docs/TARGET_ATTACHMENT_TRACKING.md)。

## AI 服务

本项目只连接已经运行的 OpenAI 兼容服务，不负责启动或关闭 `llama-server`：

```dotenv
AI_BASE_URL=http://127.0.0.1:8080/v1
AI_MODEL=local-model
AI_API_KEY=
AI_REMOTE_ENABLED=false
```

默认只允许 `127.0.0.1`、`localhost` 或 `::1`，防止邮件内容被意外发送到远端。确实要使用远端服务时，必须在本地 `.env` 中显式设置 `AI_REMOTE_ENABLED=true`。

## 使用方法

启动桌面界面：

```powershell
.\.venv\Scripts\python.exe main.py
```

命令行检查与运行：

```powershell
python mail_storyline.py check-login
python mail_storyline.py check-mail
python mail_storyline.py list-folders
python mail_storyline.py preview --senders example.com --keywords 项目,验收 --match-mode any
python mail_storyline.py download
python mail_storyline.py target-scan
python mail_storyline.py check-ai
python mail_storyline.py analyze
python mail_storyline.py all
```

其中 `check-login` 只建立 TLS 连接、提交账号授权码并完成 126 客户端 `ID` 握手，随后立即登出。它不会列出或选择文件夹，也不会搜索、读取或下载邮件。`check-mail` 会在登录后列出服务器文件夹，但同样不会读取邮件正文。

### 126 登录排错

若服务器返回 `LOGIN Login error or password error`：

1. 确认填写的是 126 的客户端授权码，不是网页登录密码。
2. 确认邮箱设置中已启用 IMAP/SMTP 服务。
3. 确认授权码属于 `MAIL_IMAP_USER` 指定的同一账号。
4. 确认 `.env` 或 `common.env` 中没有重复的 `MAIL_IMAP_USER`、`MAIL_IMAP_PASSWORD`。
5. 修改配置后重新启动命令，不要把真实账号或授权码复制到日志、问题单或 Git。

详细配置与安全验证步骤见 [docs/MAIL_CONFIGURATION.md](docs/MAIL_CONFIGURATION.md)。

## 输出目录

```text
data/
  raw_mail/<folder>/eml/                 原始邮件
  raw_mail/<folder>/attachments/         原始附件
  records/mail_records.json              去重后的结构化邮件
  records/mail_records.jsonl
  state/mail_sync_state.json             本地增量状态
output/
  mail_review.html                       邮件审核页
  storyline.json                         AI 结构化结果
  storyline.html                         可搜索的事项时间线
  target_storylines.json                 目标附件沟通链路结构化数据
  target_storylines.html                 思维导图式目标附件时间线
logs/
  main.log
  mail_storyline.log
```

这些目录包含私人邮件或运行信息，均不进入 Git。真实 `target_*.env` 同样被忽略，仓库只跟踪脱敏的 `.example` 模板。

## 架构

```text
main.py                                  GUI 入口
mail_storyline.py                        CLI 入口
logging_config.py                        统一日志
src/mail_storyline_tracker/modules/      IMAP、解析、存储、会话、AI、HTML
src/mail_storyline_tracker/flows/        工作流编排
src/mail_storyline_tracker/gui/          Tkinter 界面
tests/                                   隔离测试
docs/                                    项目规范和运行说明
```

## 验证

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m compileall -q -f -x '.venv|data|output|logs|__pycache__' .
python -m flake8 .
git diff --check
```

测试使用临时目录和模拟邮件，不连接真实邮箱、不会调用真实 AI 服务。

## Git 同步

仓库使用 `main` 分支，远端为 `git@github.com:jackylx2008/MailStorylineTracker.git`。真实 `.env`、`common.env`、邮件、附件、输出、日志和本地虚拟环境已在 `.gitignore` 中排除。推荐使用 SSH：

```powershell
git remote add origin git@github.com:jackylx2008/MailStorylineTracker.git
git status -sb
git add -A
git commit -m "Implement initial mail storyline tracker"
git push -u origin main
```

推送前务必执行 `git status --short --ignored`，确认没有真实邮件、授权码或 AI Key 被暂存。
