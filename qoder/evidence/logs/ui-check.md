# ResearchTrail 浏览器验证

- 时间：2026-10-30T14:34:35+08:00
- 地址：http://127.0.0.1:8000（Chrome headless，1440×1000 / 390×844）
- 结论：全部通过

| 检查项 | 结果 | 细节 |
| --- | --- | --- |
| 页面加载并显示 PowerContext 连接状态 | PASS | PowerContext 1.4.1 已连接 |
| 通过 UI 创建项目并导入 3 份演示资料 | PASS | title=演示项目 · 注意力机制复习 docs=3 |
| 检索结果展示原文、来源与高亮 | PASS | results=2 highlight=缩放点积注意力 |
| 收藏证据并显示个人备注 | PASS | 备注：用于组会引言，需与论文原文核对。 |
| UI 导出 Markdown 且包含原文/来源/备注 | PASS | filename=研途-演示项目 · 注意力机制复习-证据清单.md bytes=319 |
| 保存进度并显示 Memory 记录标识 | PASS | memory_id=art_ae1d403a423a450b930107b927b545bd |
| 刷新页面后进度从 PowerContext 恢复 | PASS | progress=已完成缩放点积注意力与多头注意力的笔记整理，收藏… |
| 窄屏 390px 下无横向溢出 | PASS | {"width": 390, "sidebarWidth": 390, "workspaceWidth": 362, "overflow": 0} |
| UI 空检索词提示 | PASS | 请输入检索关键词。 |
| UI 无匹配提示 | PASS | 未找到匹配段落，请尝试其他关键词。 |
| PowerContext 不可用时显示错误横幅和重试动作 | PASS | PowerContext 未连接（http://127.0.0.1:8765）。进度与证据将无法保存，请检查服务后重试。 |
| 恢复后重新连接成功 | PASS | PowerContext 1.4.1 已连接 |
| 浏览器控制台无错误 | PASS | 无 |
