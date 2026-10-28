# 回声迷宫 · Echo Maze

一个会记住玩家选择的 Dify 文字迷宫。玩家第一次选择一扇门时，迷宫记录回声；以后继续使用同一个
PowerContext Scope 进入，剧情会区分“重复选择”“改变选择”和“首次进入”，形成跨运行彩蛋。

## 技术分工

| 组件 | 实际作用 |
| --- | --- |
| Dify Workflow | 收集玩家与选择，按顺序执行回忆、剧情计算、写入和输出；不是只做界面壳。 |
| PowerContext 1.2.0 | 用稳定 Scope 隔离玩家数据，通过 `/v1/memory/search` 召回旧选择，通过 `/v1/memory/remember` 保存新回合。 |

工作流不依赖 LLM、Embedding 或第三方插件，导入后只需可访问的 PowerContext Server，因此评审不需要准备模型 API Key。

## 文件

- `echo-maze.yml`：完整 Dify DSL，导入顺序第 1 且唯一。
- `scripts/powercontext_demo.py`：创建 Scope、写入一条选择并搜索验证。
- `scripts/validate_submission.py`：校验 DSL 结构、端点、连线和两次运行的剧情差异。
- `samples/validation.md`：三组可重复的验收样例。
- `evidence/`：本次提交实际执行产生的脱敏证据。

## 运行环境

- Dify Cloud 或自托管 Dify，支持 DSL `version: 0.3.0` 的 Workflow 导入。
- PowerContext `1.2.0`，Python 3.11+。
- Dify Worker 必须能访问 PowerContext Server。自托管 Dify 与 PowerContext 放在同一私有 Docker 网络时，
  DSL 默认地址 `http://powercontext:8000` 可直接使用；其他部署在导入后修改环境变量 `powercontext_base_url`。

本地演示可以使用 `http://127.0.0.1:8000`；Dify 运行在容器中时不要把 `127.0.0.1` 当作宿主机地址。

## 1. 启动 PowerContext

安装并启动官方版本：

```bash
uv tool install --force "powercontext[cli,server]==1.2.0"
powercontext server run
```

默认监听 `127.0.0.1:8000`，适合本机脚本验证。生产或共享环境应启用认证，并通过可信网关或私有网络让
Dify Worker 访问；不要把未认证的 PowerContext Server 暴露到公网。

## 2. 初始化并验证 PowerContext

```bash
python scripts/powercontext_demo.py --base-url http://127.0.0.1:8000 --player 阿澈 --choice 红门
```

输出中的 `scope_id` 是 Dify 运行时输入。再次执行并加上 `--scope-id <返回值>` 可验证同一 Scope 的连续记忆。
如果 Server 启用了认证，通过环境变量 `POWERCONTEXT_TOKEN` 提供 Token；脚本不会打印 Token。

## 3. 导入 Dify

1. 在 Dify 工作区选择“创建应用”→“导入 DSL 文件”，导入 `echo-maze.yml`。
2. 打开环境变量，把 `powercontext_base_url` 改成 Dify Worker 可访问的 PowerContext 地址，末尾不要带 `/`。
3. 若 PowerContext 启用 Bearer Token，在两个 HTTP Request 节点中选择 Bearer 认证并从 Dify Secret 配置读取；
   不要把真实 Token 写入 DSL 或 Git。
4. 发布应用。输入上一步返回的 `scope_id`、昵称和门的选择。

## 4. 验证主要玩法

按 `samples/validation.md` 依次执行样例 A、B、C。样例 A 与 B 必须使用同一个 `scope_id`：

- 第一次运行召回 0 条，PowerContext 写入新选择；
- 第二次运行先从 PowerContext 召回旧选择，再触发“回头客暗道”；
- 更换选择会保留旧回声，但进入不同房间。

工作流的 `powercontext_write_status` 应为 `200`。需要审计原始记录时，执行：

```bash
python scripts/powercontext_demo.py --scope-id <scope_id> --player 阿澈 --choice 红门 --search-only
```

## 5. 本地静态验证

安装 PyYAML 后运行：

```bash
python scripts/validate_submission.py
```

该检查会解析 DSL、确认唯一完整路径 `start → recall → narrate → remember → end`，并执行 DSL 内嵌 Python，
证明无历史与重复选择产生不同剧情。它不替代 Dify 导入和真实 PowerContext HTTP 验证。

## 已知限制

- Scope 必须由可信初始化脚本或管理员创建；工作流不会根据用户文本自行选择或创建其他 Scope。
- 当前玩法使用 PowerContext 的全文 Memory 检索，不要求模型或向量服务。
- 同一个 Scope 可供多人共玩，但为了避免昵称冲突，正式体验建议每位玩家使用独立 Scope。
- HTTP 节点失败时 Dify 会显示节点错误，不会伪造“记忆成功”。
