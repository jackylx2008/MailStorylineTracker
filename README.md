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
- 将每个目标附件事项独立呈现在同一个可搜索、可展开折叠的节点连线式 HTML 中，从右侧最新结果向左回溯；点击节点简介可查看完整邮件正文。
- Tkinter GUI、CLI、共享日志、进度和安全取消。

项目不会删除、移动、标记已读或修改服务器邮件。IMAP 文件夹始终以只读方式打开。

近期的人工审核排除、筛选界面合并和安全取消改动见 [更新记录](docs/UPDATE_2026-09-28_REVIEW_GUI.md)。

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
MAIL_MAX_MESSAGES_PER_FOLDER=50
MAIL_MAX_MESSAGES_PER_RUN=50
MAIL_FETCH_INTERVAL_SECONDS=1.5
MAIL_FETCH_BATCH_SIZE=10
MAIL_FETCH_BATCH_PAUSE_SECONDS=20
MAIL_VOLUME_LIMIT_COOLDOWN_HOURS=24
```

- `any`：发件人组、收件人组、关键词组中任一已配置条件命中即可。
- `all`：所有已配置条件组都必须命中；组内多个值仍是任一值命中。
- 未配置任何地址或关键词时，日期范围内邮件全部匹配。
- `before` 遵循 IMAP 语义，不包含填写日期当天。
- “每文件夹最多候选数”限制每个文件夹按 UID 从新到旧检查的数量。首次运行建议保持 `50`。
- `MAIL_MAX_MESSAGES_PER_RUN` 是所有文件夹共用的单次运行总上限，默认 `50`；达到后正常停止，再次运行会从持久化断点继续。

GUI 中的修改只影响当前运行，不会改写配置文件。

### GUI 筛选字段怎么填

- 邮箱文件夹：必须使用“列出文件夹”返回的精确名称，多个值用英文逗号分隔，例如 `INBOX,声学`。
- 发件人地址/片段：可留空；多个值用英文逗号分隔，例如 `person@example.com,@supplier.com`。
- 收件人/Cc 地址/片段：可留空；格式与发件人相同，同时检查 To 和 Cc。
- 主题/正文关键词：多个关键词用英文逗号分隔，不需要引号，例如 `声学,浮筑,减震,噪声,振动`。
- 起始日期：包含当天，格式必须为 `YYYY-MM-DD`。
- 结束日期：不包含当天；留空表示直到当前邮件。分批扫描 2024 年时可填起始 `2024-01-01`、结束 `2025-01-01`。
- 每文件夹最多候选数：首次建议 `50`；该值不是最终命中数，而是每个文件夹最多检查的最新候选邮件数。
- 匹配方式 `any`：发件人、收件人/Cc、关键词任一组命中即可，适合扩大范围。
- 匹配方式 `all`：所有填写过的条件组都必须命中；同一组中的多个值仍是任一值命中。

“筛选预览”先在 126 服务器端筛日期、地址和主题，再只读取候选邮件开头 `16 KB` 检查正文，不下载附件，也不写入增量状态。“开始增量下载”才会对最终命中的邮件读取完整内容并归档。

点击 GUI 的“取消任务”后，当前网络请求结束即安全停止；状态显示“已取消”，日志不再把主动取消记为邮件处理失败或输出异常堆栈。此前已完整保存的邮件和增量检查点保留，下次运行可继续。

如果日志出现 `FETCH volume limit exceed`，表示 126 服务器已经对当前账号实施阶段性下载限制。程序会在第一次拒绝时立即停止并保存已有状态；客户端无法清除服务器额度，应等待额度恢复后从较小日期范围和候选数继续。不要在限流期间反复点击预览或下载。

### 126 流量保护策略

网易官方说明流量超限通常最迟在 24 小时后自动解除，并建议间隔 24 小时后再操作；第三方客户端的流量上限不能通过开通会员提高：

- [邮箱为什么会有流量限制呢？](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac272bbf40591ec5574)
- [邮箱流量超过限制怎么办](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac232e9189757b1aebe)

项目据此执行以下保护：

- 检测到 `FETCH volume limit exceed` 后，将账号写入本地 24 小时冷却状态；冷却结束前，预览、下载和目标扫描不会再发出 FETCH 请求。
- 默认每次 FETCH 至少间隔 1.5 秒；每 10 次请求暂停 20 秒。
- 默认每个文件夹、且所有文件夹合计每轮最多处理 50 封尚未处理的候选邮件。
- 每处理完一封普通归档邮件就原子写入进度；遇到断网、超时或 IMAP 会话中断时立即停止，不在当次运行内重发不确定的 FETCH，下次运行从 UID 断点续传。
- 预览和目标附件初筛使用部分读取；普通归档或专项扫描最终命中后，才读取并保存完整 `.eml` 及全部附件。
- 无关键词的整文件夹归档和纯地址候选归档直接执行一次完整 FETCH，避免同一封邮件先预览、再完整下载的重复请求。
- 已有完整本地邮件可由其他筛选队列复用，不会因为队列或筛选签名不同而重复 FETCH。
- CloudStation、OneDrive 等同步目录短暂占用状态文件时，原子写入会进行有限次数退避重试。

网易没有公开具体的第三方客户端请求频率、单次运行字节数或累计流量阈值。因此 1.5 秒、10 封、20 秒和 50 封是本项目的保守默认值，不是网易公布的硬性限额。

根目录的 `test_imap_fetch_limit.py` 可检查限流状态。默认会尊重本地24小时冷却，不发送 FETCH；冷却结束后会读取最新邮件前1 KB。确需在冷却期内实测一次时可显式运行 `python test_imap_fetch_limit.py --force`，不建议频繁使用。

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

GUI 的“邮箱连接与筛选”页下半部会在启动时把三个文件的内容分别载入三个多行输入框作为默认值。上方常规发件人、收件人和关键词配置为空时，会自动以目标联系人和目标关键词作为默认值。可以在界面中临时增删内容后运行；界面修改只影响本次任务，不会覆盖本地 `target_*.env`。点击“从文件重新载入”可恢复文件中的当前内容。专项扫描按钮也在同一页，使用上方日期和每文件夹候选数，但始终枚举账号下全部可选择文件夹。点击“应用目标条件到常规筛选”可把当前目标联系人同时加入 From 和 To/Cc，把目标关键词加入主题/正文关键词；目标附件事项的 AI 模糊匹配仍由专项扫描处理。

专项扫描采用：

```text
目标联系人命中 OR 目标关键词命中 OR 目标附件名命中
```

登录后会枚举并扫描账号下全部可选择的文件夹。附件 AI 只接收文件名，不读取附件正文。目标附件所在邮件作为时间线种子，再通过标准邮件回复头、规范化主题、参与人和时间关系补齐同一沟通链路。

运行：

```powershell
python mail_storyline.py target-scan
python mail_storyline.py target-local-classify
```

`target-scan` 会先部分读取候选邮件进行判断，最终命中后保存完整 `.eml` 和全部附件；以前只保存部分内容的命中记录会在后续扫描时自动升级为完整归档。`target-local-classify` 不连接 IMAP、不产生 FETCH，只使用已经完整下载到本地的邮件、附件文件名、`target_*.env` 和本地 AI 重新判定目标并生成报告。

查看节点连线式故事线时，打开 `output/target_storylines.html`。每个事项可独立展开；页面默认定位到有事件的事项及最右侧的最新节点，向左滚动可回溯。蓝色节点表示普通往来，紫色节点表示分支，绿色节点表示当前最新结果。曲线实线来自邮件回复头，虚线仅表示同一会话中的时间顺序。点击节点上的简介链接，可在弹窗查看完整解析正文、发件人、收件人、附件名和原始 `.eml` 的本地路径。

已有本地归档时，可只重新生成 JSON 和 HTML，无需连接邮箱或调用 AI：

```powershell
python mail_storyline.py target-report
```

需要限制专项扫描文件夹时，可传入精确文件夹名，例如：

```powershell
python mail_storyline.py target-scan --folders INBOX,声学
```

详细规则见 [docs/TARGET_ATTACHMENT_TRACKING.md](docs/TARGET_ATTACHMENT_TRACKING.md)。

## 完整邮件与附件归档队列

根目录的 `download_priority_mail.py` 为长时间、小批量归档提供三个独立断点队列：

- `acoustics`：完整归档“声学”文件夹内的邮件和附件。
- `sent`：完整归档“已发送”文件夹内的邮件和附件。
- `target-email`：在全部可选择文件夹中，完整归档 From、To 或 Cc 命中 `target_email.env` 的邮件和附件。

```powershell
python download_priority_mail.py acoustics --batch 5
python download_priority_mail.py sent --batch 5
python download_priority_mail.py target-email --batch 5
```

`--batch` 允许 `1` 至 `50`，建议从 `5` 或 `10` 开始。三个队列有意清除普通筛选的日期范围，以便完成历史邮件追溯；每次成功落盘后立即记录断点，再次运行只处理尚未完成的 UID。无关键词队列对每封新邮件只做一次完整 FETCH，其他队列若已归档同一 `UIDVALIDITY + UID`，会直接复用本地完整记录。

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
python mail_storyline.py preview --senders example.com --keywords 项目,验收 --match-mode any --max-messages-per-folder 50
python mail_storyline.py download
python mail_storyline.py target-scan
python mail_storyline.py target-local-classify
python mail_storyline.py target-report
python mail_storyline.py check-ai
python mail_storyline.py analyze
python mail_storyline.py all
```

其中 `check-login` 只建立 TLS 连接、提交账号授权码并完成 126 客户端 `ID` 握手，随后立即登出。它不会列出或选择文件夹，也不会搜索、读取或下载邮件。`check-mail` 会在登录后列出服务器文件夹，但同样不会读取邮件正文。

“下载与归档”中的“打开邮件审核页”会先从当前本地归档重建 `mail_review.html`。页面上方可分别按 From/To/Cc 邮箱地址和主题、完整正文、附件名关键词筛选；同一输入框内多个值用逗号分隔，组内任一命中，两组同时填写时需分别命中。

通过 GUI 打开的审核页会连接仅监听本机 `127.0.0.1` 的临时审核接口。“删除条目”会把邮件 ID 写入 `data/state/review_exclusions.json`；原始 `.eml`、附件、本地增量记录和服务器邮件仍保留。被排除的邮件不再显示于重新生成的审核页或目标附件故事线，之后运行 AI 分析时也不会作为输入。后续常规预览、增量下载和目标扫描会在 FETCH 前跳过这些邮件的已知账号/文件夹/UID 来源，且不再对其本地归档重新做目标分类；即使筛选条件变化也不会重新下载。若同一封邮件以新的 UID 出现，程序需要读取一次预览才能根据 Message-ID 识别并阻止完整下载。服务器端的文件夹/UID SEARCH 仍会执行，以发现其他新邮件。点击“撤销上次删除”可恢复该条目。已有浏览器本地存储中的删除决定会在**重启 GUI 后、通过原来审核所用的同一浏览器再次打开审核页时自动导入**；请确认页面显示“审核决定已与本地项目同步，共排除 N 封邮件”。直接打开 HTML 文件时，删除按钮不会保存项目级审核决定。

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
  state/review_exclusions.json           审核排除记录（仅在发生排除后创建）
output/
  mail_review.html                       邮件审核页
  storyline.json                         AI 结构化结果
  storyline.html                         可搜索的事项时间线
  target_storylines.json                 目标附件沟通链路结构化数据
  target_storylines.html                 节点连线式目标附件故事线
logs/
  main.log
  mail_storyline.log
```

这些目录包含私人邮件或运行信息，均不进入 Git。真实 `target_*.env` 同样被忽略，仓库只跟踪脱敏的 `.example` 模板。

## 架构

```text
main.py                                  GUI 入口
mail_storyline.py                        CLI 入口
download_priority_mail.py                完整归档断点队列入口
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
