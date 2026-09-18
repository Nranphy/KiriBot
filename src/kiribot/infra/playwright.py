"""HTML 截图与无头浏览器运行环境检查"""

import asyncio

from playwright.async_api import Error, async_playwright


async def screenshot_html(html: str, timeout: float = 30.0) -> bytes:
    """将 HTML 渲染为 PNG 字节，超时以秒计，结束时关闭浏览器"""
    if timeout <= 0:
        raise ValueError("截图超时必须大于零")
    async with asyncio.timeout(timeout):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=timeout * 1000
            )
            try:
                page = await browser.new_page()
                await page.set_content(html, timeout=timeout * 1000)
                return await page.screenshot(type="png", timeout=timeout * 1000)
            finally:
                await browser.close()


async def check_playwright(timeout: float) -> None:
    """实际启动浏览器并截图，失败时阻止启动，不自动下载"""
    try:
        await screenshot_html("<html><body>KiriBot</body></html>", timeout)
    except (Error, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "Playwright 检查失败，请执行 uv run playwright install chromium "
            "--only-shell；Linux 还需准备系统依赖。"
        ) from exc
