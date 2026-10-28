import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const required = ["package.json", "index.html", "src/main.js", "src/embedding.js", "server/store.mjs", "TECHNICAL_NOTE.md", "README.md"];
for (const file of required) if (!fs.existsSync(path.join(root, file))) throw new Error(`缺少 ${file}`);

const embedding = fs.readFileSync(path.join(root, "src/embedding.js"), "utf8");
const store = fs.readFileSync(path.join(root, "server/store.mjs"), "utf8");
const assertions = {
  "INT8 q8": /MODEL_DTYPE\s*=\s*"q8"/.test(embedding),
  "WebGPU 优先": /createExtractor\("webgpu"\)/.test(embedding),
  "WASM 降级": /createExtractor\("wasm"\)/.test(embedding),
  "seekdb-js": /from "seekdb"/.test(store),
  "384 维索引": /DIMENSION\s*=\s*384/.test(store),
  "数据库原生混合检索": /collection\.hybridSearch/.test(store),
  "RRF 排序": /rank:\s*\{\s*rrf:/.test(store),
};
for (const [name, ok] of Object.entries(assertions)) if (!ok) throw new Error(`校验失败：${name}`);
console.log("STEPFUN_SUBMISSION_VALIDATION_PASS");
for (const name of Object.keys(assertions)) console.log(`  PASS ${name}`);
