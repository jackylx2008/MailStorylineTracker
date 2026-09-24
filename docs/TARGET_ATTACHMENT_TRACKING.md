# 目标附件沟通链路

本功能用于在 126.com 邮箱全部可选择文件夹中查找目标联系人、业务关键词和目标附件，形成以附件事项为中心的邮件沟通链路与时间线。

## 1. 本地目标文件

项目根目录使用三个本地文件：

```text
target_email.env
target_keyword.env
target_file.env
```

它们不是键值型 dotenv，而是 UTF-8 的逐行列表。空行和以 `#` 开头的注释会被忽略，重复行会去重并保持首次出现顺序。

- `target_email.env`：目标邮件地址或地址片段。
- `target_keyword.env`：目标关键词。
- `target_file.env`：目标附件事项；每行独立输出，不自动合并。

真实文件包含业务联系人和项目名称，已由 `.gitignore` 排除。仓库只提交：

```text
target_email.env.example
target_keyword.env.example
target_file.env.example
```

## 2. 扫描范围

登录成功后先执行 IMAP `LIST`，排除带 `\\Noselect` 标志的容器节点，再逐一只读打开全部可选择文件夹。每个文件夹按 `config.yaml` 中的日期范围和最大邮件数搜索。

程序不会删除、移动或修改服务器邮件，也不会主动改变已读状态。

## 3. OR 筛选规则

一封邮件满足下面任一条件即进入本地归档：

```text
From/To/Cc 命中目标联系人
OR 主题/正文/附件名命中目标关键词
OR 附件名被本地 AI 判定为目标事项
```

匹配原因写入邮件结构化记录，便于在输出页面追溯。

## 4. 附件名 AI 匹配

模型输入只有：

- `target_file.env` 中的目标事项名称；
- 邮件附件的原始文件名。

允许识别日期、版本号、更新、回复、确认、审核、序号、扩展名和合理同义表达造成的差异。模型不得读取或推断附件正文，也不能只因为两个文件属于同一专业就判定匹配。

程序校验模型返回的附件名和目标事项必须来自原始输入，并过滤低置信度结果。

## 5. 沟通链路

携带目标附件的邮件是对应事项的种子。程序按以下优先级扩展同一沟通链路：

1. `Message-ID / In-Reply-To / References`；
2. 去除回复、转发等前缀后的规范化主题；
3. 参与人交集；
4. 时间接近度。

不同 `target_file` 条目始终独立输出。同一邮件线程确实涉及多个目标附件时，可以同时出现在多个事项分支中。

当前时间线事件只展示：

- 邮件时间；
- 发件人、收件人和 Cc；
- 沟通动作；
- 邮件主题；
- 命中的附件名称；
- 匹配原因及原始记录 ID。

暂不读取附件正文，不比较附件版本内容，也不分析附件内部修改。

## 6. 输出

执行：

```powershell
python mail_storyline.py check-ai
python mail_storyline.py check-login
python mail_storyline.py target-scan
```

输出：

```text
output/target_storylines.json
output/target_storylines.html
```

HTML 是单文件离线页面，以“目标附件事项总览”为根节点，每个目标事项是独立分支，邮件事件沿分支按时间排列。页面支持全文搜索、展开全部和折叠全部。
