# AMD 与 MiniMax：资源获取及提测指南

核对时间：2026-10-30。范围仅这两道生态题；PowerContext 满分比赛代码不再修改。本地代码与资源准备材料在 ecosystem/amd 和 ecosystem/minimax，压缩准备包在本目录。准备包不代表已通过官方判题。

## 当前成果与缺口

| 赛题 | 本地已完成 | 还没完成 |
| --- | --- | --- |
| MiniMax，20分 | SDD CLI、真实seekdb索引/检索、规格更新、PowerContext状态保存及跨进程恢复、真实MiniMax-M3修改、同组功能/回归测试、真实证据离线重放、独立Windows环境复现（缓存依赖） | 修复换行保护后的提交发布及正式判题；Linux未验证 |
| AMD，20分 | 固定数据与真值、三轮原生seekdb CPU基线、Recall/ID验证、环境采集、hipVS CAGRA→HNSW构建原型、对照结果检查工具 | 实际GPU编译/运行、seekdb原生HNSW构建接入及格式适配、GPU构建证据、同机CPU/GPU实测、实现PR及正式判题 |

AMD 仍有实质性的内核接入工作；拿到云机器后需要继续实现并验证，不能只填一个 Token 或 UUID 就提测。MiniMax 本地模型夹具明确标记为模拟，不算 MiniMax 实际参与。

## 一、MiniMax 需要哪些资源

必须：
1. MiniMax 开放平台账号、该账号可用的模型调用额度。
2. 能调用文本模型的 API Key 或 M Plan 订阅 Key，以及账户实际支持的模型名称。
3. 队伍 PowerContext 仓库中生态分支的写权限和大赛平台提测权限。

已有或可本地安装：
- Python3.12+、seekdb 和 PowerContext。本项目已验证它们可以本地运行，不需要另租云服务器。
- 不需要额外的 Embedding Token；本实现用数据库全文与词项检索。
- 不要求安装 MiniMax Code CLI；题面允许 HTTP API，本实现走该入口。
- AMD Token Factory 的模型密钥不能代替 MiniMax Key。

### 领取比赛赠送权益

1. 先到 [MiniMax 中国开放平台](https://platform.minimax.cn/) 注册并登录。
2. 在账号资料中找到自己的“开放平台 ID”，保存这个 ID。
3. 打开[大赛 Token 领取指南](https://ask.oceanbase.com/t/topic/35653137)，扫描 MiniMax 对应二维码，按表单要求填写参赛信息和开放平台 ID。
4. 指南当前写明 MiniMax 初赛权益为 M Plan 一个月 Explore。填写的是开放平台 ID，不是比赛队名。
5. 发放完成后进入[订阅控制台](https://platform.minimax.cn/console/plan)查看权益并获取该权益对应的订阅 Key。若没有活动资格或未到账，可按官方当前账户计费方式自行准备额度；这里不代购、不保证发放时间。

来源：[赛事领取指南](https://ask.oceanbase.com/t/topic/35653137)、[官方订阅接入说明](https://platform.minimax.cn/docs/m-plan/other-tools)。接口域名现为 api.minimax.cn；旧 minimaxi 链接会跳转到新版官方文档。

### 获取 Key 后执行

详细安装步骤见 ecosystem/minimax/README.md。先安装 requirements.txt，启动或指定 seekdb。密钥只在本机环境变量设置，不发到聊天，不提交到 Git。

~~~powershell
# 在 minimax 目录；将模型名设为控制台明确允许调用的型号
$env:MINIMAX_MODEL = 'YOUR_ENABLED_MODEL'
$env:MINIMAX_ENDPOINT = 'https://api.minimax.cn/anthropic/v1/messages'
# 在本机安全设置 MINIMAX_API_KEY 后运行
python run_live.py --binary PATH_TO_SEEKDB
~~~

脚本会创建全新业务工程和空状态：导入→检索→规格更新及重导入→实际调用MiniMax→改代码→运行相同测试→新进程恢复状态。成功后保存 runs/UUID/readiness.json 和整个实验目录。仅把 Key 填入示例文件、测试一次接口连接或运行模拟模式，都不能满足题目要求。

### MiniMax 最终提交

- 基于队伍仓库的 2026-competition-ecosystem 分支，把交付资产放入 minimax/。不改已满分的 2026-competition。
- 包含模块源码、依赖配置、样例、更新后的规格、修改前后代码、同一组测试、差异、原始日志、真实 MiniMax 开发记录、数据库查询记录、PowerContext写入/新进程恢复记录及一页技术说明。
- 先按 replay_evidence.py 重放真实开发记录；按官方说明从干净环境复现。评审不要求模型重新生成完全相同的补丁。
- 普通提交并推送，填对应完整 Commit 与生态分支。真实密钥、.env、虚拟环境和本机数据库缓存不入仓库。

## 二、AMD 需要哪些资源

必须：
1. 可登录的 Linux AMD GPU 实例，而非只提供模型 HTTP 接口的 Token Factory。需要能编译并运行自己的程序。
2. 足够覆盖编译、调试和CPU/GPU各三轮测量的算力时长、磁盘与内存。具体时长受构建缓存和评测规模影响，当前不能保证固定小时数。
3. 与GPU、驱动匹配的ROCm、HIP编译器、hipVS，以及模板桥接库与对应源码/ABI资料。
4. 实例SSH主机、端口、用户名、本机登录私钥路径；如只使用Notebook，也要能上传代码、打开终端和保存完整日志。
5. 队伍/官方seekdb仓库提交PR的GitHub账号权限。
6. 正式评测的向量规模、维度、距离类型、可比参数、加速倍数和Recall门槛。当前题面未写死目标倍数，需要以组织方实际公布配置为准。

无需：
- Token Factory 模型API密钥、MiniMax Token或聊天模型额度。
- 把部署题的UUID当成GPU构建加速证据。部署10分与AMD20分是不同任务。

### 获取 AMD 云算力

依据恢复的赛题教程：[AMD Radeon使用和部署seekdb](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lcuknwgl955v8ou7)。

1. 在[AMD开发者平台](https://developer.amd.com.cn/)注册并登录。
2. 按账号中的 AI 开发者计划/积分兑换活动取得 Radeon Cloud 算力券。教程示例中积分可兑换算力小时；兑换比例、资格和可用机器以当时页面为准，不照搬旧截图余额。
3. 从开发者平台进入 AMD 开发者云，按页面提示使用 GitHub 或魔搭账号登录/绑定，把券兑换到 Radeon Cloud 余额。
4. 进入“模板库/Gallery”，搜索 seekdb，优先使用 seekdb-hipvs 模板并 Launch。若当前没有该模板，需要选择符合官方支持矩阵的Linux AMD GPU环境，按[hipVS安装文档](https://rocm.docs.amd.com/projects/hipVS/en/latest/)部署工具链。
5. 保存实例详情页的SSH连接信息；按平台配置自己的SSH公钥，私钥只保留在本机。也可打开Notebook运行 collect_environment.py。
6. 核对实际GPU型号、ROCm、hipcc、hipVS/CuPy接口、seekdb版本与二进制摘要。GPU桥接库存在只说明安装状态，不能证明索引构建已走GPU。

注意：AMD 当前通用 hipVS 支持矩阵列的是 Instinct MI 系列和指定 ROCm/Ubuntu 组合；Radeon 的 seekdb-hipvs 比赛模板可能包含单独适配。若使用 Radeon，优先保留该模板的匹配环境并实际验证，不能据通用安装文档保证任意 Radeon 均可运行。
7. 完成实验后先下载源码、全部日志、索引/数据摘要与报告，再按平台方式释放实例，避免继续消耗额度。

[AMD官方系统要求](https://rocm.docs.amd.com/projects/hipVS/en/latest/install/system-requirements.html)用于确认GPU/ROCm支持；不要安装只适用于NVIDIA的CUDA轮子来替代AMD环境。

### 有机器后，按这个顺序接续

1. 环境采集；确认源码、桥接库和格式接口。
2. 完成GPU构建路径与seekdb原生索引接入，保留CPU基线；这部分尚未完成。
3. 固定数据种子与哈希，同机导入相同数据。
4. CPU/GPU每组至少3轮重新构建，统一计入传输、同步、图转换、持久化和首次查询就绪。
5. 核对ID、查询可用性和Recall；记录GPU kernel证据以及是否发生CPU回退。
6. 用正式门槛计算加速比、判定达标，再提交实现PR及报告。

完整命令见 ecosystem/amd/README.md。现有 gpu-prototype 命令只验证上游构图和转换API，不能替代第2步。两台不同机器测得的CPU/GPU时间不能直接作为统一环境加速比。

## 本地复核与文件位置

从项目根执行：

~~~powershell
.\.venv\Scripts\python.exe scripts\verify_amd_minimax_delivery.py
~~~

该命令核对源码语法、MiniMax 7 项接口检查、AMD 8 项指标检查、缺少 Key 时禁止实跑、缺少真实记录时禁止按真实证据打包，以及源码包摘要。它不调用收费模型，不启动云机器，也不执行正式提测。真实数据库集成的12项检查和CPU三轮构建报告另行保存于 results/minimax 和 results/amd。

源码包：submission/minimax-prepared.zip、submission/amd-prepared.zip。MiniMax 包的顶层目录已是 minimax/，便于复制到生态分支。AMD 包包含实验工具与原型，后续原生实现需进入 seekdb 仓库。

## 三、最后需要提供给我的信息

MiniMax：Key所用的本机环境变量名、允许调用的模型名、生态分支写权限是否可用。不要发送Key内容。

AMD：实例SSH命令/别名、私钥在本机的路径、GPU型号/镜像、可用算力时长；若选择Notebook方式，提供环境采集输出。还需要正式性能评测参数。

这些信息到位后，MiniMax可执行真实开发与证据补齐；AMD还要继续原生适配、编译、同机测量和PR，不能承诺拿到机器后立即满分。
