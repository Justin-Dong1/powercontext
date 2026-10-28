import "./style.css";
import { api } from "./api.js";
import { embedTexts, loadEmbeddingModel, modelStatus } from "./embedding.js";
import { chunkDocument, stableId } from "./text.js";

const kbId = localStorage.getItem("edgeseek-kb") || crypto.randomUUID();
localStorage.setItem("edgeseek-kb", kbId);

document.querySelector("#app").innerHTML = `
  <main class="shell">
    <header>
      <div><span class="eyebrow">STEPFUN × SEEKDB</span><h1>EdgeSeek</h1><p>所有 embedding 都在你的浏览器里生成，原文与向量交给 seekdb 原生混合检索。</p></div>
      <div class="status-stack"><span id="backend" class="pill neutral">模型未加载</span><span id="db" class="pill neutral">seekdb 检查中</span></div>
    </header>
    <section class="flow" aria-label="处理流程">
      <span>01 导入文本</span><i></i><span>02 浏览器向量化</span><i></i><span>03 seekdb 写入</span><i></i><span>04 RRF 混合检索</span>
    </section>
    <section class="grid">
      <article class="card import-card">
        <div class="card-title"><div><small>INGEST</small><h2>导入知识</h2></div><strong id="chunkCount">0 chunks</strong></div>
        <label class="drop" for="files"><input id="files" type="file" accept=".txt,.md,.csv,.json" multiple /><b>选择文本文件</b><span>支持 TXT / Markdown / CSV / JSON，可连续增量导入</span></label>
        <textarea id="paste" placeholder="也可以直接粘贴文本，然后点击导入…"></textarea>
        <div class="row"><button id="loadDemo" class="ghost">载入示例</button><button id="ingest" class="primary">本地向量化并写入</button></div>
        <div class="progress"><div id="bar"></div></div><p id="message" class="message">准备就绪</p>
      </article>
      <article class="card search-card">
        <div class="card-title"><div><small>RETRIEVE</small><h2>检索知识</h2></div><strong>Vector + FTS</strong></div>
        <form id="searchForm"><input id="query" autocomplete="off" placeholder="例如：为什么要优先使用 WebGPU？" /><button class="primary">混合检索</button></form>
        <div id="metrics" class="metrics"></div><div id="results" class="results"><div class="empty">导入内容后开始搜索</div></div>
      </article>
    </section>
    <footer><span>模型：Xenova/all-MiniLM-L6-v2 · INT8 · 384d</span><span>知识库会话：${kbId.slice(0, 8)}</span></footer>
  </main>`;

const $ = (selector) => document.querySelector(selector);
let pendingDocs = [];

function setMessage(text, progress = null) {
  $("#message").textContent = text;
  if (progress !== null) $("#bar").style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function updateBackend(status) {
  const element = $("#backend");
  element.textContent = `${status.backend.toUpperCase()} · INT8`;
  element.className = `pill ${status.backend === "webgpu" ? "good" : "warn"}`;
}

async function readFiles(files) {
  const docs = [];
  for (const file of files) docs.push({ name: file.name, text: await file.text() });
  return docs;
}

function prepareDocs(docs) {
  pendingDocs = docs.flatMap(({ name, text }) => chunkDocument(text).map((content, index) => ({
    id: `${stableId(name)}-${index}-${stableId(content)}`,
    content,
    metadata: { source: name, chunk: index, importedAt: new Date().toISOString() },
  })));
  $("#chunkCount").textContent = `${pendingDocs.length} chunks`;
  setMessage(`已准备 ${pendingDocs.length} 个文本块`, 5);
}

$("#files").addEventListener("change", async (event) => prepareDocs(await readFiles(event.target.files)));
$("#loadDemo").addEventListener("click", async () => {
  const demo = await fetch("/demo.json").then((response) => response.json());
  prepareDocs(demo.documents);
});

$("#ingest").addEventListener("click", async () => {
  try {
    const pasted = $("#paste").value.trim();
    if (pasted) prepareDocs([...pendingDocs.map((item) => ({ name: item.metadata.source, text: item.content })), { name: "粘贴文本.txt", text: pasted }]);
    if (!pendingDocs.length) throw new Error("请先选择文件、粘贴文本或载入示例");
    setMessage("正在加载端侧模型…", 10);
    const status = await loadEmbeddingModel((text) => setMessage(text, 20));
    updateBackend(status);
    const embedded = await embedTexts(pendingDocs.map((item) => item.content), {
      batchSize: 8,
      onProgress: (text) => setMessage(text, 25 + (pendingDocs.length ? 50 : 0)),
    });
    setMessage("向量已在浏览器生成，正在写入 seekdb…", 82);
    const result = await api.upsert({ kbId, items: pendingDocs.map((item, index) => ({ ...item, embedding: embedded.vectors[index] })) });
    setMessage(`写入完成：${result.written} chunks；向量化 ${embedded.elapsedMs.toFixed(0)} ms`, 100);
    $("#chunkCount").textContent = `${result.total} chunks`;
  } catch (error) { setMessage(`失败：${error.message}`, 0); }
});

$("#searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  try {
    $("#results").innerHTML = '<div class="empty">查询向量正在浏览器本地生成…</div>';
    const started = performance.now();
    const embedded = await embedTexts([query]);
    const response = await api.search({ kbId, query, embedding: embedded.vectors[0], limit: 6 });
    const totalMs = performance.now() - started;
    $("#metrics").innerHTML = `<span>本地向量 ${embedded.elapsedMs.toFixed(1)} ms</span><span>seekdb ${response.searchMs.toFixed(1)} ms</span><span>端到端 ${totalMs.toFixed(1)} ms</span>`;
    $("#results").innerHTML = response.results.length ? response.results.map((item, index) => `
      <article class="result"><div><b>#${index + 1}</b><span>${item.metadata?.source || "unknown"}</span><em>RRF</em></div><p>${item.document}</p></article>`).join("") : '<div class="empty">没有匹配结果</div>';
  } catch (error) { $("#results").innerHTML = `<div class="empty error">检索失败：${error.message}</div>`; }
});

api.status().then((status) => { $("#db").textContent = `${status.engine} · 已连接`; $("#db").className = "pill good"; }).catch((error) => { $("#db").textContent = `seekdb：${error.message}`; $("#db").className = "pill bad"; });
if (modelStatus().backend !== "未加载") updateBackend(modelStatus());
