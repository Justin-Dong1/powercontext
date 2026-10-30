"""Browser-level UI verification with real screenshots.

Requires the dev server at http://127.0.0.1:8000 and system Chrome.
Run:
    .venv/Scripts/python.exe scripts/ui_check.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
SHOT_DIR = APP_ROOT / "evidence" / "screenshots"
LOG_DIR = APP_ROOT / "evidence" / "logs"
TITLE = "演示项目 · 注意力机制复习"
GOAL = "梳理注意力机制的核心概念，并整理可引用的课程证据。"
NOTE = "用于组会引言，需与论文原文核对。"
PROGRESS = "已完成缩放点积注意力与多头注意力的笔记整理，收藏了一条课程证据。"
NEXT = "补充显存占用实验，并核对课程小实验的结论边界。"

SHOT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

results: list[dict[str, object]] = []
console_errors: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}", flush=True)


def shot(page: Page, name: str) -> None:
    page.wait_for_timeout(350)
    page.screenshot(path=str(SHOT_DIR / name), full_page=True)
    print(f"[shot] {name}", flush=True)


def open_project(page: Page) -> None:
    if page.locator("#welcome").is_visible():
        shot(page, "01-empty-state.png")
        page.locator("#welcomeCreateBtn").click()
    else:
        existing = page.locator(".project-item", has_text=TITLE)
        if existing.count():
            existing.first.click()
            return
        page.locator("#newProjectBtn").click()
    expect(page.locator("#projectDialog")).to_be_visible()
    page.locator("#newTitle").fill(TITLE)
    page.locator("#newGoal").fill(GOAL)
    page.locator("#projectForm button[type='submit']").click()
    expect(page.locator("#projectTitle")).to_have_text(TITLE, timeout=20000)


def ensure_documents(page: Page) -> None:
    expect(page.locator("#workspace")).to_be_visible()
    if page.locator("#documentList .card").count() >= 3:
        return
    page.locator("#demoBtn").click()
    expect(page.locator("#documentList .card")).to_have_count(3, timeout=20000)
    expect(page.locator("#importFeedback")).to_contain_text("已导入 3 份资料")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        page.goto(BASE_URL, wait_until="networkidle")
        expect(page.locator("#pcStatusText")).to_contain_text("已连接", timeout=20000)
        check("页面加载并显示 PowerContext 连接状态", True, page.locator("#pcStatusText").inner_text())

        open_project(page)
        ensure_documents(page)
        shot(page, "02-documents.png")
        check(
            "通过 UI 创建项目并导入 3 份演示资料",
            page.locator("#projectTitle").inner_text() == TITLE and page.locator("#documentList .card").count() == 3,
            f"title={page.locator('#projectTitle').inner_text()} docs={page.locator('#documentList .card').count()}",
        )

        page.locator(".tabs button[data-tab='search']").click()
        page.locator("#searchInput").fill("缩放点积注意力")
        page.locator("#searchForm button[type='submit']").click()
        expect(page.locator("#searchResults .card").first).to_be_visible(timeout=15000)
        expect(page.locator("#searchResults mark").first).to_be_visible()
        cards = page.locator("#searchResults .card")
        quotes = cards.locator(".quote").all_inner_texts()
        target_index = next((index for index, text in enumerate(quotes) if "缩放点积注意力先计算" in text), -1)
        shot(page, "03-search.png")
        check(
            "检索结果展示原文、来源与高亮",
            target_index >= 0 and "缩放点积注意力" in quotes[target_index],
            f"results={cards.count()} highlight={page.locator('#searchResults mark').first.inner_text()}",
        )

        target_card = cards.nth(target_index)
        first_button = target_card.locator("button").first
        existing_evidence = page.evaluate(
            """async () => {
                const id = localStorage.getItem('researchtrail.project');
                const response = await fetch(`/api/projects/${encodeURIComponent(id)}/evidence`);
                return (await response.json()).evidence.length;
            }"""
        )
        if existing_evidence == 0:
            first_button.click()
            page.locator(".note-editor textarea").fill(NOTE)
            page.locator(".note-editor .primary-button").click()
            expect(first_button).to_have_text("已收藏", timeout=15000)
        page.locator(".tabs button[data-tab='evidence']").click()
        expect(page.locator("#evidenceList .card")).to_have_count(1, timeout=15000)
        expect(page.locator("#evidenceList .note-view")).to_be_visible()
        shot(page, "04-evidence.png")
        evidence_note = page.locator("#evidenceList .note-view").inner_text()
        check(
            "收藏证据并显示个人备注",
            "备注：" in evidence_note,
            evidence_note,
        )

        with page.expect_download(timeout=15000) as download_info:
            page.locator("#exportBtn").click()
        download = download_info.value
        export_path = LOG_DIR / "ui-evidence-export.md"
        download.save_as(str(export_path))
        exported = export_path.read_text(encoding="utf-8")
        check(
            "UI 导出 Markdown 且包含原文/来源/备注",
            "缩放点积注意力先计算" in exported and "演示资料/01-注意力机制课程笔记.md" in exported and "我的备注：" in exported,
            f"filename={download.suggested_filename} bytes={len(exported)}",
        )

        page.locator(".tabs button[data-tab='progress']").click()
        page.locator("#goalInput").fill(GOAL)
        page.locator("#progressInput").fill(PROGRESS)
        page.locator("#nextInput").fill(NEXT)
        page.locator("#progressForm button[type='submit']").click()
        expect(page.locator("#saveState")).to_contain_text("已从 PowerContext Memory 恢复", timeout=20000)
        expect(page.locator("#progressMemoryBadge")).to_be_visible()
        shot(page, "05-progress.png")
        check(
            "保存进度并显示 Memory 记录标识",
            page.locator("#progressMemoryId").inner_text().startswith("art_"),
            f"memory_id={page.locator('#progressMemoryId').inner_text()}",
        )

        page.reload(wait_until="networkidle")
        expect(page.locator("#workspace")).to_be_visible(timeout=20000)
        page.locator(".tabs button[data-tab='progress']").click()
        expect(page.locator("#progressInput")).to_have_value(PROGRESS)
        expect(page.locator("#nextInput")).to_have_value(NEXT)
        shot(page, "06-reload-restored.png")
        check("刷新页面后进度从 PowerContext 恢复", True, f"progress={page.locator('#progressInput').input_value()[:24]}…")

        page.locator(".tabs button[data-tab='documents']").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        shot(page, "07-narrow-390.png")
        layout_ok = page.evaluate(
            """() => {
                const sidebar = document.querySelector('.sidebar').getBoundingClientRect();
                const workspace = document.querySelector('#workspace').getBoundingClientRect();
                return {width: window.innerWidth, sidebarWidth: sidebar.width, workspaceWidth: workspace.width,
                        overflow: document.documentElement.scrollWidth - window.innerWidth};
            }"""
        )
        check(
            "窄屏 390px 下无横向溢出",
            layout_ok["overflow"] <= 1,
            json.dumps(layout_ok, ensure_ascii=False),
        )
        page.set_viewport_size({"width": 1440, "height": 1000})

        page.locator(".tabs button[data-tab='search']").click()
        page.locator("#searchInput").fill("")
        page.locator("#searchForm button[type='submit']").click()
        expect(page.locator("#searchFeedback")).to_contain_text("请输入检索关键词", timeout=10000)
        shot(page, "08-empty-search.png")
        check("UI 空检索词提示", True, page.locator("#searchFeedback").inner_text())

        page.locator("#searchInput").fill("量子纠缠冷聚变")
        page.locator("#searchForm button[type='submit']").click()
        expect(page.locator("#searchFeedback")).to_contain_text("未找到匹配段落", timeout=15000)
        shot(page, "09-no-match.png")
        check("UI 无匹配提示", True, page.locator("#searchFeedback").inner_text())

        page.route(
            "**/api/health",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {"ok": False, "powercontext": {"ok": False, "url": "http://127.0.0.1:8765", "version": "1.4.1"}}
                ),
            ),
        )
        page.reload(wait_until="networkidle")
        expect(page.locator("#globalBanner")).to_be_visible(timeout=15000)
        expect(page.locator("#globalBannerText")).to_contain_text("PowerContext 未连接")
        shot(page, "10-powercontext-offline.png")
        check("PowerContext 不可用时显示错误横幅和重试动作", page.locator("#bannerAction").is_visible(), page.locator("#globalBannerText").inner_text())

        page.unroute("**/api/health")
        page.reload(wait_until="networkidle")
        expect(page.locator("#pcStatusText")).to_contain_text("已连接", timeout=20000)
        check("恢复后重新连接成功", True, page.locator("#pcStatusText").inner_text())

        check(
            "浏览器控制台无错误",
            not console_errors,
            "; ".join(console_errors[:5]) if console_errors else "无",
        )
        context.close()
        browser.close()

    report = {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": BASE_URL,
        "checks": results,
        "failed": sum(1 for item in results if not item["ok"]),
        "console_errors": console_errors,
        "screenshots": sorted(path.name for path in SHOT_DIR.glob("*.png")),
    }
    (LOG_DIR / "ui-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    conclusion = "全部通过" if report["failed"] == 0 else f"{report['failed']} 项失败"
    lines = [
        "# ResearchTrail 浏览器验证",
        "",
        f"- 时间：{report['run_at']}",
        f"- 地址：{BASE_URL}（Chrome headless，1440×1000 / 390×844）",
        f"- 结论：{conclusion}",
        "",
        "| 检查项 | 结果 | 细节 |",
        "| --- | --- | --- |",
    ]
    for item in results:
        lines.append(f"| {item['name']} | {'PASS' if item['ok'] else 'FAIL'} | {str(item['detail']).replace('|', '\\|')} |")
    lines.append("")
    (LOG_DIR / "ui-check.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[ui] {len(results) - report['failed']}/{len(results)} 项通过", flush=True)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
