# 邮件下载与人工审核

项目目标：下载有关邮件及全部附件，由人工审核决定保留或删除。已审核保留的邮件作为长期资料保存。不再调用本地 AI，不再生成事项或沟通时间线。

本次目标调整、数据清理和验证情况见 [2026-10-08 更新记录](docs/UPDATE_2026-10-08_DOWNLOAD_REVIEW.md)。早期更新记录描述历史行为，以本文及本次更新为准。

## 环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写 `MAIL_IMAP_USER` 和 `MAIL_IMAP_PASSWORD`（邮箱客户端授权码），不要使用网页登录密码。目标配置可以从对应 `.example` 模板复制后填写。

## 使用

Python 3.11+，安装 `requirements.txt`，在本地 `.env` / `common.env` 配置邮箱授权码。筛选和流量保护参数位于 `config.yaml`，目标联系人、关键词和附件名分别读取 `target_email.env`、`target_keyword.env`、`target_file.env`。附件名采用文本包含匹配，不使用 AI。

```powershell
python main.py
python mail_storyline.py check-login
python mail_storyline.py list-folders
python mail_storyline.py preview
python mail_storyline.py download
python mail_storyline.py target-scan
python mail_storyline.py review
python mail_storyline.py purge-reviewed
```

在 GUI 中下载后打开邮件审核页，筛选并阅读正文和附件名。点击“删除条目”暂存删除决定，保存前可以撤销；点击“保存审核结果”后永久删除所选邮件的本地原文、附件和结构化内容，其余邮件保留。新下载内容需人工审核。保存后的删除不能通过撤销恢复。

保持 GUI 运行以保存审核结果。离线审核页的决定只暂存在浏览器，可通过“导入旧版浏览器审核记录”迁移后保存。`purge-reviewed` 删除已经写入审核排除记录的本地邮件内容。

IMAP 始终只读，不删除或修改服务器邮件。删除后的记录 ID 与服务器来源标识保存在 `data/state/review_exclusions.json`，用于阻止再次下载；邮件正文与附件不保存在该记录中。支持 UID 增量断点、跨队列复用、取消和 126 流量冷却保护。

数据位于 `data/raw_mail` 和 `data/records`；审核页面为 `output/mail_review.html`。这些私人内容及真实配置不进入 Git。

2026-10-08 已依据已有人工审核记录确认保留 42 封，清理其余 104 封。旧 AI 与时间线模块仅为历史兼容代码，不属于当前工作流程。

## 验证状态

存储与 IMAP 辅助测试 6 项、邮件解析测试 2 项通过；另外验证了实际本地删除、删除标识持久化和重复保存重试，Python 编译检查通过。

完整旧测试集共 45 项，当前有 6 项失败、4 项错误，涉及旧 AI 分析、时间线输出、GUI 布局、审核恢复与专项扫描结果契约。测试尚需迁移到当前流程，不能视为全量验证通过。详见本次更新记录。
