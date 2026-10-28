# EdgeSeek：浏览器端 embedding + seekdb 原生混合检索

StepFun 赛题“端侧 AI 推理性能优化与 seekdb 混合检索”的完整提交。应用覆盖：导入文本 → 浏览器本地 INT8 embedding → seekdb 增量写入 → seekdb 原生全文/向量混合检索 → RRF 排序展示。

## 快速启动

要求：Node.js 22+，Chrome 或 Edge 最新版。

```bash
cd stepfun/edge-rag
pnpm install
pnpm dev
```

打开 <http://127.0.0.1:5173>。第一次点击“本地向量化并写入”会从 Hugging Face 下载公开模型；推理始终发生在浏览器本地。生产模式：

```bash
pnpm build
pnpm start
# http://127.0.0.1:8787
```

默认无需单独部署数据库：seekdb-js 嵌入式运行时将数据库保存在 `.seekdb/edge-rag`。也可以通过 `.env.example` 切换到 seekdb/OceanBase server 模式。

Windows 上若嵌入式原生运行时初始化受本机环境限制，可使用官方测试镜像：

```bash
docker run -d --name edgeseek-db -p 28881:2881 -e SEEKDB_DATABASE=edge_rag oceanbase/seekdb:latest
$env:SEEKDB_HOST="127.0.0.1"
$env:SEEKDB_PORT="28881"
pnpm dev
```

## 演示步骤

1. 点击“载入示例”，或选择多个 `.txt/.md/.csv/.json` 文件。
2. 点击“本地向量化并写入”。观察 WebGPU/WASM、INT8、进度和耗时提示。
3. 输入“为什么要优先使用 WebGPU？”并检索。
4. 再导入一份文档后立即重复检索，验证增量写入与索引可见性。
5. 在不支持 WebGPU的浏览器配置中重复操作，界面应提示 WASM，完整流程仍可运行。

## 验证

```bash
pnpm validate
pnpm test
pnpm build
```

`pnpm validate` 会检查 INT8、WebGPU 优先/WASM 降级、seekdb-js、向量维度、原生 `hybridSearch` 和 RRF。数据库服务已启动时可执行 `pnpm smoke` 做真实写入与混合检索。浏览器性能结果应按 `evidence/benchmark-template.csv` 在目标设备实测填写；不把开发机静态检查冒充真实 WebGPU 基准。

## 关键实现

- `src/embedding.js`：Transformers.js 浏览器端模型加载、q8、WebGPU → WASM 降级、批处理。
- `server/store.mjs`：seekdb-js collection、全文/HNSW 索引、增量 upsert、read-after-write、数据库原生混合检索。
- `src/main.js`：文件导入、分块、会话隔离、进度、性能分阶段计时和结果展示。
- `TECHNICAL_NOTE.md`：模型、量化、后端、seekdb、状态管理与复测口径的一页说明。

## 数据与隐私边界

浏览器只访问 Hugging Face 获取公开模型文件；文档与查询不会发送给任何云端推理 API。它们只发送到本机 `127.0.0.1` 的 seekdb 服务进行持久化与数据库检索。生产部署时应维持同源或受控内网访问，不要将未加认证的本地 API 暴露到公网。
