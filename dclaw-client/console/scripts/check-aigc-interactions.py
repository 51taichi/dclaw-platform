"""Read-only UI regression check. Run inside local DClaw with Playwright installed.

Uses the seeded demo conversation; all POST requests are blocked. Long content is
injected into the browser DOM only, never persisted to the user's task.
"""
import asyncio
import json

from playwright.async_api import async_playwright
from qwenpaw.app.auth import create_token, revoke_token
from qwenpaw.app.storage.repos.user_repo import get_user_repository

TASK = "f2294f76-4e08-4d83-8bb4-aad52344488e"
MATERIAL = "material-workflow-live-accc7cc68f"


async def main():
    token = create_token(get_user_repository().get_user_by_id(1)["username"], expiry_seconds=300)
    failures = []
    def check(condition, message):
        print(("PASS " if condition else "FAIL ") + message, flush=True)
        if not condition:
            failures.append(message)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await page.add_init_script('localStorage.setItem("qwenpaw_auth_token",' + json.dumps(token) + ');localStorage.setItem("dclaw:aigc-card-shelf:expanded","false");')
            posts = []
            async def read_only(route):
                if route.request.method not in ("GET", "HEAD", "OPTIONS"):
                    posts.append(route.request.method)
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/api/**", read_only)
            await page.goto("http://127.0.0.1:8088/task/" + TASK)
            card = page.locator('[data-card-id="' + MATERIAL + '"]')
            await card.wait_for(timeout=20000)
            for mode in ("compact", "expanded"):
                if mode == "expanded":
                    await page.get_by_role("button", name="展开素材任务", exact=True).click()
                await card.scroll_into_view_if_needed()
                await page.mouse.move(20, 20)
                await page.wait_for_timeout(200)
                style = "e=>{const s=getComputedStyle(e);return [s.backgroundColor,s.borderColor,s.boxShadow]}"
                before = await card.evaluate(style)
                rect = await card.bounding_box()
                await card.hover()
                await page.wait_for_timeout(250)
                after = await card.evaluate(style)
                check(all(a != b for a, b in zip(before, after)), mode + " hover changes background, border and shadow")
                check(rect == await card.bounding_box(), mode + " hover does not shift layout")
                await page.screenshot(path="/tmp/aigc-hover-" + mode + ".png")
                # Browser-only status fixture; never changes persisted task state.
                original_status = await card.get_attribute("data-task-status")
                await card.evaluate('e=>e.setAttribute("data-task-status","ACCEPTED")')
                await page.wait_for_timeout(200)
                check(await card.evaluate('e=>getComputedStyle(e).borderTopColor') == "rgb(22, 163, 74)", mode + " accepted hover retains green")
                await card.evaluate('(e,s)=>e.setAttribute("data-task-status",s)', original_status)
            await page.emulate_media(reduced_motion="reduce")
            check(await card.evaluate('e=>getComputedStyle(e).transitionDuration') == "0s", "reduced motion disables card transitions")
            await page.emulate_media(reduced_motion="no-preference")
            await card.get_by_role("button", name="继续制作", exact=True).click()
            await page.wait_for_url("**/aigc-studio?task=" + MATERIAL)
            panel = page.get_by_role("complementary", name="AIGC 执行向导", exact=True)
            await panel.wait_for(timeout=20000)
            footer = panel.locator("footer")
            back = footer.get_by_role("button", name="返回任务会话", exact=True)
            check(await back.locator("svg").count() == 1, "return action has an icon")
            # Extend real parameters locally to exercise the actual overflow layout.
            await panel.locator("details").evaluate('e=>{e.open=true;const p=document.createElement("p");p.textContent="长内容滚动验证。".repeat(600);e.appendChild(p)}')
            for height in (1000, 640):
                await page.set_viewport_size({"width": 1440, "height": height})
                await page.wait_for_timeout(200)
                bounds = await panel.bounding_box()
                initial = await footer.bounding_box()
                check(initial["y"] + initial["height"] <= bounds["y"] + bounds["height"] and initial["y"] > bounds["y"] + bounds["height"] - initial["height"] - 40, "footer stays at panel bottom at height " + str(height))
                # Scroll the container holding instructions, supporting old and new DOM.
                scrolled = await panel.locator("details").evaluate('e=>{for(let n=e.parentElement;n;n=n.parentElement){if(n.scrollHeight>n.clientHeight&&/auto|scroll/.test(getComputedStyle(n).overflowY)){n.scrollTop=n.scrollHeight;return n.scrollTop}}return 0}')
                await page.wait_for_timeout(200)
                check(scrolled > 0, "long content scrolls at height " + str(height))
                check(initial == await footer.bounding_box(), "scroll does not move footer at height " + str(height))
                await page.screenshot(path="/tmp/aigc-footer-" + str(height) + ".png")
            await back.click()
            await page.wait_for_url("**/task/" + TASK)
            check(
                page.url.endswith("/task/" + TASK),
                "return action restores the original conversation route",
            )
            check(not posts, "no generation or submission requests")
            await browser.close()
    finally:
        revoke_token(token)
    assert not failures, failures


asyncio.run(main())
