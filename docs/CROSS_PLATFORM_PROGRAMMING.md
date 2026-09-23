# AGENTS.md — 通用 AI 编程协作规范

本文档用于指导 AI 编程助手在本仓库中安全、可验证地开展工作。规范重点是跨平台兼容、项目本地环境、云盘同步和 Git 协作，不固化具体业务实现。

## 1. 指令与信息来源

开始工作前按以下顺序获取上下文：

1. 用户当前请求和明确授权。
2. 本文件及当前目录层级中更具体的 `AGENTS.md`。
3. 项目 README、依赖清单、环境示例、测试和源码。
4. Git 当前分支、工作区状态及远端差异。

项目事实必须从当前代码和配置中确认，不要依赖过往对话、文件名猜测或其他机器的状态。

如果文档与实现不一致：

- 先通过代码、测试和版本历史确认真实行为。
- 修复实现时同步更新文档。
- 不确定哪一方正确且选择会改变用户意图时，停止并询问。

## 2. 工作原则

- 先检查、后修改；先验证、后提交。
- 修改范围保持最小，不顺手重构无关代码。
- 保留用户已有改动，不覆盖不属于当前任务的文件。
- 不把诊断请求自动扩大为修复、提交、部署或推送。
- 对可逆的本地操作保持主动；对删除、覆盖、远端写入和凭据操作保持谨慎。
- 不隐藏失败。测试、网络、权限或环境问题要给出具体证据。
- 避免仅为“看起来更整洁”而大范围格式化、重排或改写换行。

## 3. 项目本地虚拟环境

### 基本规则

- 优先在项目根目录创建本地环境，例如 `.conda` 或 `.venv`。
- 环境目录必须加入 `.gitignore`，不得提交或通过云盘在不同操作系统间复用。
- 依赖的可移植来源是环境声明文件，例如 `environment.yml`、`requirements.txt`、`pyproject.toml` 或锁文件。
- Windows、macOS 和 Linux 应分别在本机根据同一依赖声明重建环境。
- 不假设存在全局命名环境、固定用户名、固定磁盘、固定 Python 安装路径或已激活 shell。
- 运行测试和脚本时，优先显式调用项目环境内的解释器，减少误用全局 Python 的风险。

### Conda 前缀环境示例

Windows PowerShell：

```powershell
conda env create --prefix .\.conda -f environment.yml
conda activate .\.conda
.\.conda\python.exe --version
```

macOS/Linux：

```bash
conda env create --prefix ./.conda -f environment.yml
conda activate ./.conda
./.conda/bin/python --version
```

更新环境：

```bash
conda env update --prefix ./.conda -f environment.yml --prune
```

### venv 示例

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

命令只是模式示例。实际环境类型、Python 版本和依赖文件必须以当前仓库为准。

### macOS 本地 VS Code Code Runner 启动桌面 GUI

以下 `settings.json` 配置仅用于 macOS，已在 MacBook Pro 的 VS Code 与 Code Runner 0.12.2 中完成人工界面启动测试。Windows 和 Linux 不应直接复用，应按各自的 shell、Conda 路径和终端行为单独配置。

macOS 使用 VS Code 的 Code Runner 启动 Tkinter 等桌面 GUI 时，可让工作区配置直接引用项目根目录下的 Conda 前缀环境，并显式传入当前文件：

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.conda",
  "python.terminal.activateEnvironment": true,
  "code-runner.executorMap": {
    "python": "conda run --no-capture-output --prefix \"$workspaceRoot/.conda\" python -u $fullFileName"
  },
  "code-runner.fileDirectoryAsCwd": true,
  "code-runner.ignoreSelection": true,
  "code-runner.runInTerminal": false,
  "code-runner.clearPreviousOutput": true
}
```

这类 `.vscode/settings.json` 属于本机 IDE 配置：

- 不需要 Git 跟踪，不推送到 GitHub，也不应依靠 Git 在不同操作系统间同步。
- 项目应在 `.gitignore` 中忽略整个 `.vscode/` 目录。
- 需要在另一台 Mac 上使用时，应根据本文档在该机器本地创建；Windows 和 Linux 应维护各自的本地配置。
- 如果文件此前已被 Git 跟踪，使用 `git rm --cached -r .vscode` 仅从索引移除，保留磁盘上的本地文件。

配置时还要注意：

- 执行器只要包含 `$workspaceRoot` 等占位符，部分 Code Runner 版本就不会再自动把当前文件追加到命令末尾，因此必须显式加入 `$fullFileName`。否则命令只会启动 Python，终端显示 `>>>`，而不会运行入口脚本。
- GUI 程序应使用 `--no-capture-output`，避免 Conda 缓冲或捕获子进程输出影响长期运行的界面进程。
- `code-runner.ignoreSelection` 应设为 `true`，避免编辑器中存在选区时只运行临时代码片段。
- 推荐使用独立进程模式 `code-runner.runInTerminal: false`。Code Runner 的集成终端会被复用；如果旧终端仍停留在 Python `>>>` 中，后续 Run Code 命令可能被当作 Python 输入，而不是交给 shell 执行。
- 如果此前使用过终端模式，先退出或关闭停留在 `>>>` 的 `Code` 终端，再重新运行。
- 修改 `.vscode/settings.json` 后配置没有生效时，执行 `Developer: Reload Window`。
- `$workspaceRoot` 和 `${workspaceFolder}` 都由 VS Code 在运行时解析，不应替换为个人用户名或本机绝对路径。

诊断时先查看 Code Runner 展示的最终命令。正确命令必须同时包含项目 `.conda` 前缀和实际入口文件，例如：

```text
conda run --no-capture-output --prefix "<workspace>/.conda" python -u "<workspace>/main.py"
```

如果只看到 `python -u` 而没有入口文件，说明文件占位符缺失；如果看到 `>>>`，说明启动了 Python REPL，或命令被发送到了尚未退出的 REPL 终端。

## 4. 跨平台兼容性

### 路径

- 使用标准路径库，不用字符串拼接路径。
- 业务逻辑不要硬编码用户目录、盘符、路径分隔符或桌面位置。
- 用户路径优先来自参数、配置或环境变量，并提供清晰的默认值和错误信息。
- 处理其他操作系统的路径字符串时，使用纯路径类型；只有访问当前文件系统时才使用实体路径类型。
- 测试至少覆盖 Windows 风格路径、POSIX 风格路径、相对路径、绝对路径、用户目录展开和 Unicode 文件名。
- 不默认文件系统区分大小写，也不默认所有平台允许相同的文件名字符。

### 系统能力

- 优先使用 Python 标准库和有明确跨平台支持的依赖。
- 引入依赖本地动态库、系统包、GUI 框架或外部命令的功能时，必须记录各平台安装要求。
- 平台分支集中管理，不要让操作系统判断散落在业务代码中。
- 对不支持的平台给出明确错误，不能静默采用可能破坏数据的替代行为。

### 编码与换行

- 文本文件默认使用 UTF-8。
- 不因 CRLF/LF 提示而批量改写整个仓库。
- 修改中文、Unicode 路径或配置后，验证读写编码和 Git diff。
- 使用 `git diff --check` 检查尾随空格及补丁格式问题。

## 5. GUI、后台任务与并发

适用于 Tkinter、Qt、Web UI 或其他事件驱动界面：

- 耗时 I/O、网络、解码和批处理不能阻塞 UI 主线程。
- 后台线程或进程不直接修改 UI 控件；通过队列、事件或框架调度机制回到主线程。
- 界面需要显示可理解的状态：准备、扫描、处理中、完成、失败。
- 长任务至少提供总数、当前进度、当前对象和错误摘要。
- 任务执行期间应防止重复启动；关闭窗口或取消任务时避免留下半写文件。
- UI 和 CLI 应复用同一业务服务层，不复制核心逻辑。
- GUI 测试不应自动弹出长期驻留窗口；优先使用隐藏窗口、组件构建测试或 mock。

## 6. 配置与敏感信息

- 密钥、令牌、账号、真实路径和个人数据放在本地环境变量或被忽略的配置文件中。
- 提交可公开的示例文件，如 `.env.example`，但只使用占位值。
- 新增配置项时同步更新：读取逻辑、示例配置、README 和测试。
- 日志不得输出密钥、令牌、完整凭据、原始敏感数据或不必要的个人路径。
- 默认配置应安全、可预测，并允许用户覆盖。

## 7. 云盘同步目录中的 Git 安全

OneDrive、Synology Drive、CloudStation、Dropbox 等工具可能：

- 先同步工作树，后同步或不正确同步 `.git`。
- 只改变时间戳或文件属性，造成 Git 伪修改。
- 产生冲突副本、临时文件和缓存。
- 在另一台机器尚未提交时同步半成品代码。

因此开始工作前执行：

```bash
git status -sb
git branch -vv
git remote -v
git fetch --all --prune
```

比较原则：

- 分别检查工作树、`HEAD` 和远端分支，不把“云盘已同步”视为“Git 已同步”。
- 状态显示修改但 `git diff` 为空时，先比较文件内容哈希和 Git blob，再判断是否只是时间戳变化。
- 未确认内容相同前，不使用 reset、checkout、clean 或删除命令消除状态。
- 本地有真实改动且需要更新分支时，先提交到合适分支，或建立带说明且包含未跟踪文件的 stash 备份。
- stash 是备份；未经用户确认，不删除可能包含唯一改动的 stash。
- 发现冲突副本或两端独立修改时，逐文件合并并测试，不以文件较新时间戳作为唯一依据。

内容哈希比较示例：

```bash
git hash-object -- path/to/file
git rev-parse HEAD:path/to/file
git rev-parse origin/main:path/to/file
```

## 8. Git 分支、提交与推送

- 修改前确认当前分支、上游分支和用户指定目标。
- 拉取前确保工作区状态已理解，避免覆盖本地同步内容。
- 合并前获取最新远端引用并检查分支关系；能安全快进时优先快进。
- 提交只包含当前任务文件，不夹带缓存、环境、日志或无关用户改动。
- 提交信息简洁描述结果，不描述执行过程。
- 用户只要求检查、比较或诊断时，不自动提交或推送。
- 只有用户明确要求远端写入时才推送；推送前说明目标仓库和分支。
- 推送后确认本地分支、上游分支和远端提交一致。
- 禁止使用破坏性 Git 命令绕过冲突或测试失败。

提交前检查：

```bash
git diff --check
git status -sb
git diff --stat
git diff --cached --stat
```

## 9. 代码修改流程

### 修改前

1. 读取相关入口、配置、测试和调用链。
2. 确认工作区是否已有用户改动。
3. 明确行为边界、兼容性和验证方式。
4. 对高风险操作先解析精确目标。

### 修改中

- 优先复用现有抽象和工具函数。
- 函数保持单一职责，复杂流程拆成可测试单元。
- 公共行为变化应添加或更新测试。
- 错误信息应包含可操作上下文，但不泄露敏感数据。
- 不吞掉异常；可恢复错误记录后继续，不可恢复错误清晰上报。
- 避免静默改变公共接口、配置含义或输出目录结构。

### 修改后

1. 运行与改动直接相关的测试。
2. 运行完整快速测试集和语法/类型检查（如果项目提供）。
3. 检查 Git diff，确认没有编码、换行或无关改动。
4. 更新 README、示例配置和依赖声明。
5. 报告已验证内容、未验证风险和 Git 状态。

## 10. 测试策略

- 使用项目本地解释器运行测试。
- 测试应隔离外部资源，使用临时目录、fixture、mock 或小型样本。
- 默认不处理真实生产目录、不批量写入用户输出目录、不调用真实付费或有副作用的服务。
- 文件处理测试覆盖成功、空输入、无匹配、格式错误、权限错误和单文件失败后继续。
- 路径测试应能在任意宿主系统模拟不同目标系统。
- GUI 测试验证组件构建、输入校验、状态变化和线程消息，不依赖人工点击。
- 修复 bug 时先构造能复现问题的测试，再验证修复。

常见 Python 检查模式：

```bash
python -m unittest discover -s tests -v
python -m py_compile path/to/modules.py
git diff --check
```

实际测试框架和命令以仓库配置为准。

## 11. 依赖与文档同步

依赖变化时：

- 更新项目实际使用的依赖声明和锁文件。
- 区分运行依赖、开发依赖和平台专用依赖。
- 删除依赖前确认源码、脚本和文档不再引用。
- 在至少一个干净或可重建环境中验证安装。

行为变化时：

- README 说明用户如何安装、配置、运行和验证。
- 示例配置与代码默认值一致。
- 平台限制和额外系统依赖明确记录。
- 不把短期机器状态、个人绝对路径或临时排障步骤写成永久规范。

## 12. 默认禁止提交的内容

除非仓库明确另有约定，否则不得提交：

- 本地虚拟环境目录。
- `.env`、凭据、令牌和私钥。
- 缓存、编译产物和临时目录。
- 日志、输出文件和大体积生成物。
- IDE 的个人绝对路径和机器专用配置。
- 真实用户数据、输入样本或处理结果。

若发现这些文件未被忽略，应先评估，再以最小范围更新 `.gitignore`。

## 13. 完成标准

任务完成前确认：

1. 实现满足用户请求，没有扩大授权范围。
2. 用户已有改动得到保留。
3. 代码在目标平台可运行，或已明确说明限制。
4. 项目本地环境、依赖声明和运行命令一致。
5. 相关测试、快速完整测试和静态检查通过。
6. Git diff 只包含任务相关内容，且无格式错误。
7. 文档、示例配置和实现保持同步。
8. 没有提交环境、缓存、日志、凭据或个人路径。
9. 若用户要求推送，目标远端和分支已核对且推送结果已验证。
