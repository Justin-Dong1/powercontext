# EdgeSeek 一页技术说明

## 模型与量化

- 模型：`Xenova/all-MiniLM-L6-v2`，对应 Sentence Transformers `all-MiniLM-L6-v2`，Apache-2.0，384 维。
- 运行时：Transformers.js 4.3.2。前端显式请求 `dtype: "q8"`，文档与查询 embedding 都在浏览器生成，不存在云端推理接口。
- 体积口径：同一模型仓库的 FP32 ONNX 约 90.4 MB，Q8 ONNX 约 23.2 MB，压缩比约 3.90×。首次加载会下载模型，后续由浏览器 Cache API 复用。
- 质量方法：用相同语料、相同 20 条查询比较 FP32 与 Q8 的 Recall@5。仓库不伪造未在当前机器完成的浏览器基准；`evidence/benchmark-template.csv` 给出了固定记录格式，评审可按 README 一键复测。

## 端侧运行

`src/embedding.js` 首先尝试 `device: "webgpu"`；初始化或推理后端不可用时捕获错误并重新创建 `device: "wasm"` 的 pipeline。界面一直显示当前后端、INT8 精度、模型加载和每次向量化耗时。文档批处理大小为 8，查询使用单条低延迟路径。

## seekdb 使用

Node 22 服务通过 seekdb-js 1.4.0 的嵌入式模式打开本地数据库。每个浏览器知识库 ID 映射为独立 collection，schema 同时创建全文索引与 384 维 cosine HNSW 索引。浏览器把真实 embedding 发送给本地服务，写入 `ids/documents/embeddings/metadatas`；服务 read-after-write 验证刷新可见性。

检索只调用一次 `collection.hybridSearch()`：全文候选与向量候选由 seekdb 生成，数据库内部使用 RRF 排序。浏览器仅渲染数据库返回的最终结果，不在客户端拼接两路结果。

## 状态与优化

- 知识库 ID 持久化在 `localStorage`，collection 隔离避免切换串库；重复导入使用稳定 ID 和 `upsert`，支持增量更新。
- 520 字符分块、80 字符重叠，文档 embedding 批量执行；模型与 collection 均缓存复用。
- UI 分别显示本地查询向量、seekdb 检索和端到端延迟。首次模型下载/加载与预热查询必须分开记录。
- WebGPU、WASM、FP32、Q8 应在同一设备与浏览器版本下测试；固定语料、查询集、批大小和 seekdb 配置，至少重复 5 次并报告中位数。
