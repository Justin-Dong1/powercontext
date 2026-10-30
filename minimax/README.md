# 规有所依：SDD 工程上下文模块

本目录是 MiniMax 生态题的实现材料，最终须放进队伍 PowerContext 仓库的 minimax/ 目录，并基于 2026-competition-ecosystem 分支开发。2026-10-30 已通过 MiniMax-M3 真实开发、规格更新、跨进程恢复及离线证据重放；另在不继承原有包的独立 Windows 虚拟环境通过7项接口检查、12项真实数据库/状态检查及真实证据重放。官方判题尚未完成。

## 功能与技术分工

- seekdb：存储规格、业务代码及测试源文件；用实际 SQL 的全文匹配及词项匹配选择任务上下文。原文、相对路径、内容 SHA256 和项目版本随结果返回。
- MiniMax：通过官方 Anthropic 兼容 HTTP 接口接收上述上下文，返回允许修改文件的完整新代码；实际运行固定的功能测试和回归测试。
- PowerContext：通过真实 Memory API 保存任务状态；每个 CLI 进程重新打开独立 SQLite 持久层。SQLite 只用于 PowerContext 自身状态，不代替 seekdb 查询工程资料。
- CLI：index / context / develop / resume。样例为“增加工单状态筛选”。未修改时三个目标断言失败，既有三个回归通过。代码修改后同一组测试必须全部通过，测试和规格不能被模型更改。

数据库表 sdd_sources 中保存 project、path、kind、revision、digest、body。项目重导入以事务替换自己的索引；版本不一致时拒绝使用过期上下文。任务状态按项目和任务隔离。当前检索适用于小型工程，最多100份、每份128KiB、返回最多30份；没有使用外部 SQL 引擎。

## 安装和运行

Python 3.12 或更新版本；一个可以执行 SQL 的 seekdb 实例。推荐独立虚拟环境：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SEEKDB_HOST = '127.0.0.1'
$env:SEEKDB_PORT = '2881'
$env:SEEKDB_USER = 'root'
~~~

PowerContext 固定在 fda256c329c6ea9f6e6bb037354922f0f577ac5e；依赖安装不会修改已获满分的比赛分支。已有 PowerContext 目录内容损坏时，不要用损坏源码替代安装。开发机另有 restore_dependencies.py 可下载固定源码用于诊断，它不是运行所必需的文件。

seekdb 可按[官方仓库部署说明](https://github.com/oceanbase/seekdb)安装。本地 Windows 也可安装官方运行包：

~~~powershell
npm install --prefix runtime @oceanbase/seekdb-node@1.4.0
~~~

Windows 可执行文件位于 runtime/node_modules/@oceanbase/seekdb-node-win32-x64/native/seekdb.exe。传给下面 --binary 即可自动启动有内存上限的独立实验数据库；如已经有外部实例则省略 --binary，使用上述环境变量。提供的本地启动器只适配支持 mysql_port_mode=specified 的运行包；遇到版本不兼容时使用外部已启动的 seekdb，不修改生产配置。

## 资源到位后，一次完成真实开发及状态恢复

先按 .env.example 在当前进程设置 MINIMAX_API_KEY 和 MINIMAX_MODEL。MINIMAX_ENDPOINT 默认 https://api.minimax.cn/anthropic/v1/messages；也支持官方国际端点。模型名称应以账户可调用列表为准，本项目不强行假定某个模型已授权。

~~~powershell
.\.venv\Scripts\python.exe run_live.py --binary runtime/node_modules/@oceanbase/seekdb-node-win32-x64/native/seekdb.exe
~~~

此命令在 runs/UUID/ 创建全新业务工程和空状态，依次导入、检索、更新规格并重导入、调用一次 MiniMax、应用修改、验证测试，再通过另一个 CLI 进程恢复状态。只有全部成功才写 readiness.json。每次运行会生成新的实验目录，不覆盖上一次记录。自动启动的数据库会在流程结束后关闭。

如 PowerShell 环境变量设置不成功，可在上述命令中增加 `--interactive`。脚本会在终端隐藏输入 API Key，无需提前设置 Key 变量，也不将 Key 写入文件。模型优先使用当前进程的 MINIMAX_MODEL，未设置时使用 MiniMax-M3。粘贴 Key 后按回车；空输入或无法隐藏输入时会在联网前退出。

记录包括：context.json、baseline-tests.json、model-record.json、before/、after/、code.diff、verification.json、resumed-context.json、result.json、resume.json 以及每阶段日志。记录不保存请求头、密钥或模型私有思维链。代码与测试版本由内容摘要绑定。首次成功后保存整个 run 目录，不只保存截图。

本目录的 `.gitattributes` 禁止 Git 自动转换换行符，以保留来源摘要、模型响应及代码快照的原始字节。将材料放入参赛仓库时须一并保留这个文件。

## 独立 CLI

~~~powershell
python sdd_context.py --project sample --state data/state.db --out data/evidence index
python sdd_context.py --project sample --state data/state.db --out data/evidence context
python sdd_context.py --project sample --state data/state.db --out data/evidence develop --model YOUR_ENABLED_MODEL
python sdd_context.py --project sample --state data/state.db --out data/evidence resume
~~~

直接 develop 会修改指定业务样例，建议使用 run_live.py 自动创建的干净副本。通过更新任意已导入规格并再次 index/context，可以验证检索结果使用新内容。

## 验证与审阅

~~~powershell
python -m unittest test_contracts -v
python verify_local.py --binary PATH_TO_SEEKDB
python replay_evidence.py PATH_TO_REAL_RUN/evidence --out replay-results
~~~

verify_local.py 使用真实 seekdb、真实 PowerContext 和明确标识的本地协议夹具，无需 MiniMax Token。它验证工程流程，不能证明 MiniMax 实际参与；生成的 actual_minimax=false，不可充作提交开发记录。replay_evidence.py 只接受真实 MiniMax 记录，用提交的原始上下文、模型响应及同一组测试重放修改前后结果，不再次调用模型。

现有本地集成12项通过，接口/来源/记录保护7项通过；原始结果位于项目根 results/minimax/local-integration.json。2026-10-30 的真实 MiniMax-M3 运行编号为 7c28737a619b494c900f85a8dd63fabe：修改前3项目标断言失败，修改后3项目标测试及3项回归均通过，受保护资料未变，规格重导入及跨进程状态恢复通过。真实记录离线重放通过。开发机原始记录在 runs/ 对应目录，交付包中整理为 evidence/；重放命令为 `python replay_evidence.py evidence --out replay-results`。

独立环境验证报告在交付包 `validation/clean-environment.json`：从 Git 候选版本导出材料，创建不继承系统包的新虚拟环境，安装56个兼容依赖，使用空数据库/状态重新执行12项集成检查、7项接口检查及真实证据重放。由于执行环境 DNS 无法访问 GitHub，安装使用下载缓存及按 SHA256 核验的固定 PowerContext 源码归档；其360个 Python 源文件与安装结果逐一校验。归档缺少 Git 版本元数据，构建时显式指定版本为 `0.0.0+git.fda256c329c6e`。本次未验证从公网重新下载依赖，也未在 Linux 或官方判题环境运行。

## 提交边界

准备包是源码交付，不是已经获得20分。补齐真实 MiniMax 记录及重启复用证据后，将本目录和完整真实运行材料放入队伍仓库的 minimax/，在生态分支普通提交并推送，再填写该分支的完整 Commit。不要提交本机 .env、凭据、虚拟环境、数据库缓存或旧满分 PowerContext 分支的修改。

原始项目依赖来自 OceanBase PowerContext 和 seekdb（Apache-2.0），本目录新实现与这些上游依赖分开管理。MiniMax 接口参考：[官方 Anthropic 接口说明](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)。
