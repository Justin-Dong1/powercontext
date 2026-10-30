# ResearchTrail 验收结果（20261030-143539）

- 执行时间：20261030-143539 → 2026-10-30T14:36:07+08:00
- 独立数据目录：`data\acceptance\20261030-143539`
- PowerContext：http://127.0.0.1:18765（独立实例，role=all，SQLite）
- 应用：http://127.0.0.1:18000
- 结论：全部通过

| # | 检查项 | 结果 | 实测细节 |
| --- | --- | --- | --- |
| 1 | 健康检查：应用 / SQLite / PowerContext 均可用 | PASS | HTTP 200 {"ok": true, "app": {"ok": true, "data_dir": "G:\\scientific_research\\OB\\ecosystem\\qoder\\data\\acceptance\\20261030-143539\\app"}, "database": {"ok": true}, "powercontext": {"ok": true, "url": "http://127.0.0.1:18765", "version": "1.4.1"}} |
| 2 | 创建两个隔离的研究项目 | PASS | A=scp_0fqche7z40a292vrxqs4jbx53k B=scp_78cjbnzkjg8wdwxhqyfbz90tgh |
| 3 | 导入固定演示资料（3 份合成笔记） | PASS | HTTP 200 imported=3 errors=[] |
| 4 | 资料保留文件名、相对来源、摘要与段落数 | PASS | documents=3 paragraphs=40 names=['01-注意力机制课程笔记.md', '02-论文摘录-检索增强生成.txt', '03-对照实验记录.md'] |
| 5 | 关键词检索返回原文段落与准确来源 | PASS | q=缩放点积注意力 count=2 命中段=par_6a64ae4f2cc24be184af12313cde6635 |
| 6 | 无匹配时明确提示 | PASS | count=0 message=未找到匹配段落，请尝试其他关键词。 |
| 7 | 空检索词被拒绝 | PASS | HTTP 400 detail=请输入检索关键词。 |
| 8 | 重复导入同一资料被拒绝 | PASS | HTTP 400 detail=未能导入任何资料：资料来源“演示资料/01-注意力机制课程笔记.md”与内容已导入过。 |
| 9 | 收藏证据并保存备注（PowerContext Memory） | PASS | HTTP 201 evidence_id=art_af4e578e4ed5435f9a51b652b9f04c7e source=演示资料/01-注意力机制课程笔记.md |
| 10 | 同一段落重复收藏被拒绝 | PASS | HTTP 409 detail=该段落已经收藏。 |
| 11 | 导出 Markdown 证据清单，原文/来源/备注一致 | PASS | HTTP 200 bytes=712 content_type=text/markdown; charset=utf-8 disposition=attachment; filename="researchtrail-evidence.md"; filename*=UTF-8''%E7%A0%94%E9%80%94-%E6%BC%94%E7%A4%BA%E9%A1%B9%E7%9B%AE%20A%20%C2%B7%20%E6%B3%A8%E6%84%8F%E5%8A%9B%E6%9C%BA%E5%88%B6%E5%A4%8D%E4%B9%A0-%E8%AF%81%E6%8D%AE%E6%B8%85%E5%8D%95.md |
| 12 | 保存项目 A 的研究目标、进度与下一步 | PASS | HTTP 200 source=powercontext memory_id=art_07cb2dfafca84d958d4752e510992752 archived=1 |
| 13 | 保存项目 B 的不同进度 | PASS | HTTP 200 memory_id=art_c56d1978f7db49a2acd5f4814495283e |
| 14 | 项目隔离：B 无法看到 A 的资料/证据，也不能收藏 A 的段落 | PASS | B 检索=0 证据=0 资料=0 跨项目收藏 HTTP=400 |
| 15 | 非法项目标识/不存在项目/非法证据标识被合理处理 | PASS | bad_id=400 missing=404 bad_evidence=400 |
| 16 | PowerContext 中真实存在项目 Scope 与 Memory 记录 | PASS | 项目 Scope=2（总计 3） A证据=1 A进度=1 B进度=1 |
| 17 | 结束进程并重启后，应用与 PowerContext 再次就绪 | PASS | HTTP 200 |
| 18 | 重启后资料仍在且项目间不串数据 | PASS | A 资料=3 B 资料=0 |
| 19 | 重启后两份项目的进度分别准确恢复 | PASS | A.progress='已完成缩放点积与多头注意力的笔记整理，收藏 1 条证据。' B.progress='已完成三组对照实验记录初稿。' |
| 20 | 重启后证据收藏、备注与来源保持一致 | PASS | A 证据=1 B 证据=0 evidence_id=art_af4e578e4ed5435f9a51b652b9f04c7e |
| 21 | 重启后导出的原文/来源/备注仍一致 | PASS | HTTP 200 bytes=709 |
| 22 | 重启后 PowerContext 记录仍为活跃状态（真实持久化） | PASS | A证据=1 A进度=1 B进度=1 |

原始 JSON：`evidence/logs/acceptance.json`；服务日志：`evidence/logs/servers.log`。
