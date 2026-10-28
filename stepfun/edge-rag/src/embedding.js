import { env, pipeline } from "@huggingface/transformers";

export const MODEL_ID = "Xenova/all-MiniLM-L6-v2";
export const MODEL_DTYPE = "q8";
export const DIMENSION = 384;

env.allowRemoteModels = true;
env.useBrowserCache = true;

let extractor;
let activeBackend = "未加载";
let loadMs = 0;

async function createExtractor(device) {
  const started = performance.now();
  const instance = await pipeline("feature-extraction", MODEL_ID, {
    dtype: MODEL_DTYPE,
    device,
  });
  loadMs = performance.now() - started;
  activeBackend = device;
  return instance;
}

export async function loadEmbeddingModel(onStatus = () => {}) {
  if (extractor) return modelStatus();
  if (navigator.gpu) {
    try {
      onStatus("检测到 WebGPU，正在加载 INT8 模型…");
      extractor = await createExtractor("webgpu");
      return modelStatus();
    } catch (error) {
      console.warn("WebGPU 初始化失败，降级到 WASM", error);
      onStatus("WebGPU 初始化失败，已自动降级到 WASM…");
    }
  } else {
    onStatus("当前浏览器不支持 WebGPU，使用 WASM…");
  }
  extractor = await createExtractor("wasm");
  return modelStatus();
}

export function modelStatus() {
  return { model: MODEL_ID, dtype: MODEL_DTYPE, backend: activeBackend, loadMs };
}

export async function embedTexts(texts, { batchSize = 8, onProgress = () => {} } = {}) {
  if (!extractor) await loadEmbeddingModel(onProgress);
  const vectors = [];
  const started = performance.now();
  for (let offset = 0; offset < texts.length; offset += batchSize) {
    const batch = texts.slice(offset, offset + batchSize);
    const output = await extractor(batch, { pooling: "mean", normalize: true });
    const rows = output.tolist();
    vectors.push(...(batch.length === 1 && typeof rows[0] === "number" ? [rows] : rows));
    onProgress(`本地向量化 ${Math.min(offset + batch.length, texts.length)} / ${texts.length}`);
  }
  return { vectors, elapsedMs: performance.now() - started };
}
