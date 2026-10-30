(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);

  const state = {
    projects: [],
    projectId: null,
    project: null,
    stats: { documents: 0, paragraphs: 0, evidence: 0 },
    documents: [],
    evidence: [],
    progress: null,
    activeTab: "documents",
    searchQuery: "",
    health: null,
  };

  const dom = {
    projectList: $("#projectList"),
    welcome: $("#welcome"),
    workspace: $("#workspace"),
    projectTitle: $("#projectTitle"),
    projectGoal: $("#projectGoal"),
    projectStats: $("#projectStats"),
    pcStatus: $("#pcStatus"),
    pcStatusText: $("#pcStatusText"),
    banner: $("#globalBanner"),
    bannerText: $("#globalBannerText"),
    bannerAction: $("#bannerAction"),
    documentList: $("#documentList"),
    importFeedback: $("#importFeedback"),
    fileInput: $("#fileInput"),
    folderInput: $("#folderInput"),
    demoBtn: $("#demoBtn"),
    searchForm: $("#searchForm"),
    searchInput: $("#searchInput"),
    searchFeedback: $("#searchFeedback"),
    searchResults: $("#searchResults"),
    evidenceList: $("#evidenceList"),
    evidenceFeedback: $("#evidenceFeedback"),
    evidenceTabCount: $("#evidenceTabCount"),
    exportBtn: $("#exportBtn"),
    progressForm: $("#progressForm"),
    goalInput: $("#goalInput"),
    progressInput: $("#progressInput"),
    nextInput: $("#nextInput"),
    saveState: $("#saveState"),
    progressMemoryBadge: $("#progressMemoryBadge"),
    progressMemoryId: $("#progressMemoryId"),
    projectDialog: $("#projectDialog"),
    projectForm: $("#projectForm"),
    newTitle: $("#newTitle"),
    newGoal: $("#newGoal"),
    toast: $("#toast"),
  };

  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function formatDate(value) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  }

  function safeFilename(value) {
    return String(value || "研究项目").replace(/[\\/:*?"<>|]+/g, "-").slice(0, 80);
  }

  function toast(message, isError = false) {
    dom.toast.textContent = message;
    dom.toast.classList.toggle("error", isError);
    dom.toast.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => dom.toast.classList.remove("show"), 3200);
  }

  async function api(path, options = {}) {
    const init = { ...options };
    const isForm = init.body instanceof FormData;
    init.headers = {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(init.headers || {}),
    };
    let response;
    try {
      response = await fetch(path, init);
    } catch (error) {
      throw new Error("无法连接研途服务，请确认应用仍在运行。");
    }
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const message = (payload && (payload.detail || payload.message)) || `请求失败（HTTP ${response.status}）`;
      const error = new Error(message);
      error.status = response.status;
      error.data = payload;
      throw error;
    }
    return payload;
  }

  function setBanner(message, action) {
    if (!message) {
      dom.banner.classList.add("hidden");
      return;
    }
    dom.bannerText.textContent = message;
    dom.banner.classList.remove("hidden");
    dom.bannerAction.hidden = !action;
    dom.bannerAction.onclick = action || null;
  }

  function showFeedback(element, message, details = [], isError = false) {
    element.replaceChildren();
    if (!message && details.length === 0) {
      element.classList.add("hidden");
      return;
    }
    element.classList.remove("hidden");
    element.classList.toggle("error", isError);
    if (message) element.append(h("div", { text: message }));
    if (details.length) {
      const list = h("ul", {});
      for (const item of details) list.append(h("li", { text: item }));
      element.append(list);
    }
  }

  function hideFeedback(element) {
    element.classList.add("hidden");
    element.replaceChildren();
  }

  function renderStats() {
    const stats = state.stats || {};
    dom.projectStats.replaceChildren(
      h("div", { class: "stat" }, h("strong", { text: String(stats.documents ?? 0) }), h("span", { text: "资料" })),
      h("div", { class: "stat" }, h("strong", { text: String(stats.paragraphs ?? 0) }), h("span", { text: "段落" })),
      h("div", { class: "stat" }, h("strong", { text: String(stats.evidence ?? 0) }), h("span", { text: "证据" })),
    );
    dom.evidenceTabCount.textContent = stats.evidence ? String(stats.evidence) : "";
  }

  function renderProjectList() {
    dom.projectList.replaceChildren();
    if (state.projects.length === 0) {
      dom.projectList.append(h("div", { class: "project-empty", text: "还没有项目，先创建一个研究目标。" }));
      return;
    }
    for (const project of state.projects) {
      const button = h(
        "button",
        {
          class: `project-item${project.id === state.projectId ? " active" : ""}`,
          type: "button",
          title: project.goal,
        },
        h("strong", { text: project.title }),
        h("span", { text: project.goal }),
      );
      button.addEventListener("click", () => selectProject(project.id));
      dom.projectList.append(button);
    }
  }

  function showWelcome() {
    dom.welcome.classList.remove("hidden");
    dom.workspace.classList.add("hidden");
  }

  function showWorkspace() {
    dom.welcome.classList.add("hidden");
    dom.workspace.classList.remove("hidden");
  }

  function setActiveTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tabs button").forEach((button) => {
      const active = button.dataset.tab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".panel").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.panel === tab);
    });
  }

  async function refreshHealth() {
    try {
      const health = await api("/api/health");
      state.health = health;
      const ok = Boolean(health.ok);
      dom.pcStatus.classList.toggle("ok", ok);
      dom.pcStatus.classList.toggle("bad", !ok);
      const version = health.powercontext && health.powercontext.version;
      dom.pcStatusText.textContent = ok
        ? `PowerContext ${version || ""} 已连接`
        : "PowerContext 未连接";
      if (!ok) {
        setBanner(
          `PowerContext 未连接（${(health.powercontext && health.powercontext.url) || "未知地址"}）。进度与证据将无法保存，请检查服务后重试。`,
          async () => {
            await refreshHealth();
            if (state.health && state.health.ok) {
              setBanner("");
              await loadProjects(true);
            }
          },
        );
      } else {
        setBanner("");
      }
    } catch (error) {
      dom.pcStatus.classList.remove("ok");
      dom.pcStatus.classList.add("bad");
      dom.pcStatusText.textContent = "研途服务未连接";
      setBanner(error.message, () => boot());
    }
  }

  let projectsRequestId = 0;

  async function loadProjects(preserveSelection = true) {
    const requestId = ++projectsRequestId;
    const data = await api("/api/projects");
    if (requestId !== projectsRequestId) return;
    state.projects = data.projects || [];
    if (preserveSelection && state.projectId && state.projects.some((item) => item.id === state.projectId)) {
      renderProjectList();
      return;
    }
    const stored = localStorage.getItem("researchtrail.project");
    const next = state.projects.find((item) => item.id === stored) || state.projects[0];
    if (next) {
      await selectProject(next.id);
    } else {
      state.projectId = null;
      state.project = null;
      renderProjectList();
      showWelcome();
    }
  }

  async function selectProject(projectId) {
    state.projectId = projectId;
    localStorage.setItem("researchtrail.project", projectId);
    renderProjectList();
    hideFeedback(dom.importFeedback);
    hideFeedback(dom.searchFeedback);
    hideFeedback(dom.evidenceFeedback);
    dom.searchInput.value = "";
    dom.searchResults.replaceChildren();
    state.searchQuery = "";
    try {
      const [detail, documents, evidence, progress] = await Promise.all([
        api(`/api/projects/${encodeURIComponent(projectId)}`),
        api(`/api/projects/${encodeURIComponent(projectId)}/documents`),
        api(`/api/projects/${encodeURIComponent(projectId)}/evidence`),
        api(`/api/projects/${encodeURIComponent(projectId)}/progress`),
      ]);
      if (state.projectId !== projectId) return;
      state.project = detail.project;
      state.stats = detail.stats;
      state.documents = documents.documents || [];
      state.evidence = evidence.evidence || [];
      state.progress = progress.progress;
      dom.projectTitle.textContent = state.project.title;
      dom.projectGoal.textContent = state.project.goal;
      renderStats();
      renderDocuments();
      renderEvidence();
      renderProgress();
      showWorkspace();
      setActiveTab(state.activeTab || "documents");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      toast(error.message, true);
      if (error.status === 503) setBanner(error.message, () => selectProject(projectId));
    }
  }

  function docCard(document_) {
    return h(
      "article",
      { class: "card" },
      h(
        "div",
        { class: "card-head" },
        h(
          "div",
          {},
          h("h3", { class: "card-title", text: document_.name }),
          h(
            "p",
            { class: "source-line" },
            h("code", { text: document_.relative_source }),
          ),
        ),
      ),
      h("p", { class: "summary", text: document_.summary }),
      h(
        "div",
        { class: "card-meta" },
        h("span", { text: `${document_.paragraph_count} 段` }),
        h("span", { text: `导入于 ${formatDate(document_.created_at)}` }),
      ),
    );
  }

  function renderDocuments() {
    dom.documentList.replaceChildren();
    if (state.documents.length === 0) {
      const button = h("button", { class: "secondary-button", type: "button", text: "载入演示资料" });
      button.addEventListener("click", importDemo);
      dom.documentList.append(
        h(
          "div",
          { class: "empty" },
          h("h3", { text: "还没有导入研究资料" }),
          h("p", { text: "选择 UTF-8 编码的 Markdown 或 TXT 文件，也可以直接载入内置的合成演示笔记。" }),
          button,
        ),
      );
      return;
    }
    for (const document_ of state.documents) dom.documentList.append(docCard(document_));
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlighted(text, query) {
    const fragment = document.createDocumentFragment();
    if (!query) {
      fragment.append(document.createTextNode(text));
      return fragment;
    }
    const pattern = new RegExp(escapeRegExp(query), "gi");
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > last) fragment.append(document.createTextNode(text.slice(last, match.index)));
      const mark = h("mark", { text: match[0] });
      fragment.append(mark);
      last = match.index + match[0].length;
    }
    if (last < text.length) fragment.append(document.createTextNode(text.slice(last)));
    return fragment;
  }

  function searchCard(result) {
    const article = h(
      "article",
      { class: "card" },
      h(
        "div",
        { class: "card-head" },
        h(
          "div",
          {},
          h("h3", { class: "card-title", text: result.document_name }),
          h(
            "p",
            { class: "source-line" },
            h("code", { text: result.relative_source }),
            ` · 第 ${result.ordinal} 段`,
          ),
        ),
        h(
          "div",
          { class: "card-actions" },
          h("button", { class: "secondary-button", type: "button", text: "收藏证据" }),
        ),
      ),
      h("blockquote", { class: "quote" }, highlighted(result.text, state.searchQuery)),
    );
    const favorite = article.querySelector("button");
    favorite.addEventListener("click", () => openNoteEditor(article, result, favorite));
    return article;
  }

  function openNoteEditor(article, result, favorite) {
    if (article.querySelector(".note-editor")) return;
    const textarea = h("textarea", {
      maxlength: "500",
      placeholder: "写下这条证据的用途、疑问或引用位置（可选，最多 500 字）",
      "aria-label": "证据备注",
    });
    const save = h("button", { class: "primary-button", type: "button", text: "保存证据" });
    const cancel = h("button", { class: "ghost-button", type: "button", text: "取消" });
    const editor = h(
      "div",
      { class: "note-editor" },
      textarea,
      h("div", { class: "note-actions" }, cancel, save),
    );
    cancel.addEventListener("click", () => editor.remove());
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(state.projectId)}/evidence`, {
          method: "POST",
          body: JSON.stringify({ paragraph_id: result.paragraph_id, note: textarea.value }),
        });
        editor.remove();
        favorite.textContent = "已收藏";
        favorite.disabled = true;
        toast("证据已写入 PowerContext Memory");
        await refreshEvidence();
      } catch (error) {
        toast(error.message, true);
        save.disabled = false;
      }
    });
    article.append(editor);
    textarea.focus();
  }

  async function refreshEvidence() {
    if (!state.projectId) return;
    const [detail, evidence] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(state.projectId)}`),
      api(`/api/projects/${encodeURIComponent(state.projectId)}/evidence`),
    ]);
    state.stats = detail.stats;
    state.evidence = evidence.evidence || [];
    renderStats();
    renderEvidence();
  }

  function renderEvidence() {
    dom.evidenceList.replaceChildren();
    if (state.evidence.length === 0) {
      const goSearch = h("button", { class: "secondary-button", type: "button", text: "去检索原文" });
      goSearch.addEventListener("click", () => setActiveTab("search"));
      dom.evidenceList.append(
        h(
          "div",
          { class: "empty" },
          h("h3", { text: "证据清单还是空的" }),
          h("p", { text: "在检索结果中收藏关键段落，原文、来源和备注会一起保存，并可导出 Markdown。" }),
          goSearch,
        ),
      );
      return;
    }
    for (const item of state.evidence) {
      const remove = h("button", { class: "ghost-button", type: "button", text: "取消收藏" });
      remove.addEventListener("click", () => deleteEvidence(item, remove));
      dom.evidenceList.append(
        h(
          "article",
          { class: "card" },
          h(
            "div",
            { class: "card-head" },
            h(
              "div",
              {},
              h("h3", { class: "card-title", text: item.document_name }),
              h(
                "p",
                { class: "source-line" },
                h("code", { text: item.relative_source }),
                ` · 第 ${item.paragraph_ordinal} 段`,
              ),
            ),
            h("div", { class: "card-actions" }, remove),
          ),
          h("blockquote", { class: "quote", text: item.quote }),
          item.note ? h("p", { class: "note-view" }, h("span", { text: "备注：" }), item.note) : null,
          h(
            "div",
            { class: "card-meta" },
            h("span", { text: `收藏于 ${formatDate(item.created_at)}` }),
            h("span", { text: `Memory ${item.evidence_id}` }),
          ),
        ),
      );
    }
  }

  async function deleteEvidence(item, button) {
    if (!window.confirm(`取消收藏“${item.document_name}”第 ${item.paragraph_ordinal} 段？`)) return;
    button.disabled = true;
    try {
      await api(`/api/projects/${encodeURIComponent(state.projectId)}/evidence/${encodeURIComponent(item.evidence_id)}`, {
        method: "DELETE",
      });
      toast("已取消收藏");
      await refreshEvidence();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
    }
  }

  function renderProgress() {
    const progress = state.progress || {};
    dom.goalInput.value = progress.goal || (state.project && state.project.goal) || "";
    dom.progressInput.value = progress.progress || "";
    dom.nextInput.value = progress.next_steps || "";
    if (progress.memory_id) {
      dom.progressMemoryBadge.hidden = false;
      dom.progressMemoryId.textContent = progress.memory_id;
    } else {
      dom.progressMemoryBadge.hidden = true;
      dom.progressMemoryId.textContent = "";
    }
    const source = progress.source === "powercontext" ? "PowerContext Memory" : "项目目标（尚未写入 Memory）";
    const savedAt = progress.updated_at ? formatDate(progress.updated_at) : "尚未保存";
    dom.saveState.textContent = `已从 ${source} 恢复 · ${savedAt}`;
    dom.saveState.classList.add("ok");
  }

  async function importFiles(files) {
    if (!files.length) return;
    const form = new FormData();
    for (const file of files) {
      form.append("files", file, file.name);
      form.append("relative_paths", file.webkitRelativePath || file.name);
    }
    await runImport(form);
    dom.fileInput.value = "";
    dom.folderInput.value = "";
  }

  async function runImport(form) {
    hideFeedback(dom.importFeedback);
    const buttons = [dom.fileInput, dom.folderInput, dom.demoBtn];
    buttons.forEach((button) => { if (button) button.disabled = true; });
    try {
      const data = await api(`/api/projects/${encodeURIComponent(state.projectId)}/documents`, {
        method: "POST",
        body: form,
      });
      showImportResult(data);
    } catch (error) {
      if (error.data && (error.data.imported || error.data.errors)) {
        showImportResult(error.data, true);
      } else {
        toast(error.message, true);
      }
    } finally {
      buttons.forEach((button) => { if (button) button.disabled = false; });
      await refreshDocuments();
    }
  }

  function showImportResult(data, isError = false) {
    const imported = data.imported || [];
    const errors = data.errors || [];
    const parts = [];
    if (imported.length) parts.push(`已导入 ${imported.length} 份资料。`);
    if (errors.length) parts.push(`${errors.length} 份未能导入。`);
    showFeedback(
      dom.importFeedback,
      parts.join(" ") || "没有可导入的资料。",
      errors.map((item) => `${item.name}：${item.message}`),
      isError || imported.length === 0,
    );
    if (imported.length) toast(`已导入 ${imported.length} 份资料`);
  }

  async function importDemo() {
    hideFeedback(dom.importFeedback);
    dom.demoBtn.disabled = true;
    try {
      const data = await api(`/api/projects/${encodeURIComponent(state.projectId)}/demo`, { method: "POST" });
      showImportResult(data);
    } catch (error) {
      toast(error.message, true);
    } finally {
      dom.demoBtn.disabled = false;
      await refreshDocuments();
    }
  }

  async function refreshDocuments() {
    if (!state.projectId) return;
    const [detail, documents] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(state.projectId)}`),
      api(`/api/projects/${encodeURIComponent(state.projectId)}/documents`),
    ]);
    state.stats = detail.stats;
    state.documents = documents.documents || [];
    renderStats();
    renderDocuments();
  }

  async function runSearch(event) {
    event.preventDefault();
    const query = dom.searchInput.value.trim();
    if (!query) {
      showFeedback(dom.searchFeedback, "请输入检索关键词。", [], true);
      dom.searchInput.focus();
      return;
    }
    state.searchQuery = query;
    dom.searchResults.replaceChildren(h("p", { class: "skeleton", text: "正在检索原文段落…" }));
    hideFeedback(dom.searchFeedback);
    try {
      const data = await api(
        `/api/projects/${encodeURIComponent(state.projectId)}/search?q=${encodeURIComponent(query)}`,
      );
      dom.searchResults.replaceChildren();
      if (!data.results.length) {
        showFeedback(dom.searchFeedback, data.message || "未找到匹配段落，请尝试其他关键词。");
        return;
      }
      showFeedback(dom.searchFeedback, `找到 ${data.count} 个匹配段落。`);
      for (const result of data.results) dom.searchResults.append(searchCard(result));
    } catch (error) {
      dom.searchResults.replaceChildren();
      showFeedback(dom.searchFeedback, error.message, [], true);
    }
  }

  async function exportEvidence() {
    if (!state.projectId) return;
    dom.exportBtn.disabled = true;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(state.projectId)}/evidence/export`);
      if (!response.ok) {
        let message = `导出失败（HTTP ${response.status}）`;
        try {
          const data = await response.json();
          message = data.detail || message;
        } catch (_) { /* keep default */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `研途-${safeFilename(state.project && state.project.title)}-证据清单.md`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("证据清单已导出");
    } catch (error) {
      toast(error.message, true);
    } finally {
      dom.exportBtn.disabled = false;
    }
  }

  async function saveProgress(event) {
    event.preventDefault();
    const goal = dom.goalInput.value.trim();
    if (!goal) {
      toast("研究目标不能为空", true);
      dom.goalInput.focus();
      return;
    }
    const submit = dom.progressForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    dom.saveState.textContent = "正在写入 PowerContext Memory…";
    try {
      const data = await api(`/api/projects/${encodeURIComponent(state.projectId)}/progress`, {
        method: "PUT",
        body: JSON.stringify({
          goal,
          progress: dom.progressInput.value,
          next_steps: dom.nextInput.value,
        }),
      });
      state.progress = data.progress;
      if (state.project) state.project.goal = goal;
      dom.projectGoal.textContent = goal;
      renderProgress();
      const archived = data.archived_progress_records || 0;
      toast(archived ? `进度已保存，并归档 ${archived} 条旧版本` : "进度已保存到 PowerContext Memory");
      await loadProjects(true);
      await refreshProjectListGoals();
    } catch (error) {
      dom.saveState.textContent = "保存失败，请重试";
      dom.saveState.classList.remove("ok");
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  async function refreshProjectListGoals() {
    try {
      const data = await api("/api/projects");
      state.projects = data.projects || [];
      renderProjectList();
    } catch (_) { /* sidebar refresh is best-effort */ }
  }

  function markDirty() {
    dom.saveState.textContent = "有未保存的修改";
    dom.saveState.classList.remove("ok");
  }

  function openProjectDialog() {
    dom.projectForm.reset();
    dom.projectDialog.showModal();
    window.requestAnimationFrame(() => dom.newTitle.focus());
  }

  function closeProjectDialog() {
    dom.projectDialog.close();
  }

  async function createProject(event) {
    event.preventDefault();
    const title = dom.newTitle.value.trim();
    const goal = dom.newGoal.value.trim();
    if (!title || !goal) {
      toast("请填写项目名称和研究目标", true);
      return;
    }
    const submit = dom.projectForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const data = await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({ title, goal }),
      });
      closeProjectDialog();
      toast("项目已创建");
      state.projectId = data.project.id;
      localStorage.setItem("researchtrail.project", data.project.id);
      await loadProjects(false);
    } catch (error) {
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  function bindEvents() {
    $("#newProjectBtn").addEventListener("click", openProjectDialog);
    $("#welcomeCreateBtn").addEventListener("click", openProjectDialog);
    $("#closeProjectDialog").addEventListener("click", closeProjectDialog);
    $("#cancelProjectDialog").addEventListener("click", closeProjectDialog);
    dom.projectForm.addEventListener("submit", createProject);

    document.querySelectorAll(".tabs button").forEach((button) => {
      button.addEventListener("click", () => {
        setActiveTab(button.dataset.tab);
        if (button.dataset.tab === "evidence") refreshEvidence().catch((error) => toast(error.message, true));
      });
    });

    dom.fileInput.addEventListener("change", () => importFiles(Array.from(dom.fileInput.files || [])));
    dom.folderInput.addEventListener("change", () => importFiles(Array.from(dom.folderInput.files || [])));
    dom.demoBtn.addEventListener("click", importDemo);
    dom.searchForm.addEventListener("submit", runSearch);
    dom.exportBtn.addEventListener("click", exportEvidence);
    dom.progressForm.addEventListener("submit", saveProgress);
    [dom.goalInput, dom.progressInput, dom.nextInput].forEach((input) => input.addEventListener("input", markDirty));

    dom.projectDialog.addEventListener("click", (event) => {
      if (event.target === dom.projectDialog) closeProjectDialog();
    });
  }

  async function boot() {
    bindEvents();
    setActiveTab("documents");
    await refreshHealth();
    try {
      await loadProjects(true);
    } catch (error) {
      toast(error.message, true);
    }
    window.setInterval(refreshHealth, 30000);
  }

  boot();
})();
