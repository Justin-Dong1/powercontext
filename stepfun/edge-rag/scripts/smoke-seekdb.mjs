const baseUrl = process.env.EDGESEEK_URL || "http://127.0.0.1:8787";
const dimension = 384;

function vector(seed) {
  const values = Array.from({ length: dimension }, (_, index) => Math.sin(seed * 17 + index * 0.37));
  const norm = Math.sqrt(values.reduce((sum, value) => sum + value * value, 0));
  return values.map((value) => value / norm);
}

async function post(path, payload) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  return result;
}

const kbId = "stepfun-smoke";
const first = vector(1);
const upsert = await post("/api/upsert", {
  kbId,
  items: [
    { id: "webgpu", content: "WebGPU 适合浏览器端批量 AI 推理，失败时应降级 WASM。", embedding: first, metadata: { source: "smoke.md" } },
    { id: "seekdb", content: "seekdb 在数据库内部执行向量与全文混合检索，并使用 RRF 排序。", embedding: vector(2), metadata: { source: "smoke.md" } },
  ],
});
if (upsert.written !== 2) throw new Error(`写入数量异常：${upsert.written}`);

const search = await post("/api/search", { kbId, query: "WebGPU", embedding: first, limit: 2 });
if (!search.results.some((item) => item.id === "webgpu")) throw new Error("原生混合检索未返回预期记录");
console.log("STEPFUN_SEEKDB_SMOKE_PASS");
console.log(JSON.stringify({ upsert, resultIds: search.results.map((item) => item.id), searchMs: search.searchMs }, null, 2));
