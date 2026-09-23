# 126 邮箱配置与安全验证

本文档说明如何在不访问邮件内容的前提下配置并验证 126.com IMAP 登录，以及如何逐步启用文件夹查看、筛选预览和增量下载。

## 1. 本地配置文件

项目依次读取：

1. 当前进程已有的环境变量；
2. 项目根目录 `.env`；
3. 项目根目录 `common.env`。

`.env` 和 `common.env` 均被 Git 忽略。推荐从一个示例文件复制，不要重命名或删除仓库中的示例：

```powershell
Copy-Item common.env.example common.env
```

填写：

```dotenv
MAIL_IMAP_HOST=imap.126.com
MAIL_IMAP_PORT=993
MAIL_IMAP_USER=your-account@126.com
MAIL_IMAP_PASSWORD=your-126-client-authorization-code
```

`MAIL_IMAP_PASSWORD` 必须是邮箱设置中生成的客户端授权码，而不是网页登录密码。配置文件中同一个变量只保留一行，尤其不要重复定义账号或授权码。

## 2. 分级验证

### 只验证登录

```powershell
python mail_storyline.py check-login
```

该命令只执行：

1. 与 `imap.126.com:993` 建立 TLS 连接；
2. 提交账号和客户端授权码；
3. 发送 126 所需的 IMAP `ID` 客户端身份；
4. 立即登出。

它不会发送 `LIST`、`SELECT`、`SEARCH` 或 `FETCH`，因此不会查看文件夹或访问邮件。

### 查看文件夹

```powershell
python mail_storyline.py check-mail
python mail_storyline.py list-folders
```

此阶段会读取文件夹名称，但不会选择文件夹或读取邮件内容。

### 筛选预览

```powershell
python mail_storyline.py preview
```

预览会只读选择配置的文件夹并下载搜索范围内的邮件到内存以完成正文关键词判断，但不会保存 EML、附件或增量状态。

### 增量归档

```powershell
python mail_storyline.py download
```

归档会保存命中邮件，并将处理状态写入本地 `data/`。服务器文件夹始终以只读方式打开，程序不会删除、移动邮件或改变已读状态。

## 3. 登录错误排查

服务器返回 `LOGIN Login error or password error` 时，依次确认：

- 账号以 `@126.com` 结尾且没有拼写错误。
- 使用客户端授权码，而非网页登录密码。
- 126 邮箱设置中已经开启 IMAP/SMTP 服务。
- 授权码由当前配置账号生成；重置授权码后同步更新本地文件。
- `.env` 与 `common.env` 没有相互冲突，单个文件中也没有重复键。
- 值的首尾没有多余空格；通常不需要引号。

诊断输出只能显示脱敏账号、配置项是否存在和长度等非秘密信息，不得输出授权码。

## 4. 配置优先级提醒

项目不会用本地文件覆盖启动进程中已经存在的同名环境变量。如果终端或 IDE 已经注入旧的 `MAIL_IMAP_USER` 或 `MAIL_IMAP_PASSWORD`，应先清除旧进程变量或重新打开终端，再运行检查。

`.env` 优先于 `common.env`。建议实际使用时只在其中一个文件维护邮箱凭据，减少歧义。
