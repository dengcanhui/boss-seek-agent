from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ruyipage.aio import AsyncFirefoxPage, launch


logger = logging.getLogger("uvicorn.error.browser")


class RuyiPageBrowser:
    """项目内使用固定 Firefox runtime 和固定 profile 的 RuyiPage 浏览器。"""

    def __init__(
        self,
        project_root: Path,
        *,
        browsers_dir: str = "runtime/browsers",
        profile_dir: str = "runtime/profile",
        headless: bool = False,
        start_url: str | None = "https://www.zhipin.com/",
    ):
        self.project_root: Path = project_root.resolve()
        self.browsers_dir: Path = self._resolve(browsers_dir)
        self.profile_dir: Path = self._resolve(profile_dir)
        self.headless: bool = headless
        self.start_url: str | None = start_url
        self._page: AsyncFirefoxPage | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def _find_browser(self) -> Path | None:
        executable = "firefox.exe" if os.name == "nt" else "firefox"
        return next(
            (path.resolve() for path in self.browsers_dir.rglob(executable) if path.is_file()),
            None,
        )

    def _install_browser(self) -> Path:
        self.browsers_dir.mkdir(parents=True, exist_ok=True)
        os.environ["RUYIPAGE_BROWSERS_PATH"] = str(self.browsers_dir)

        try:
            from ruyipage._runtime.installer import install
        except ImportError as exc:
            raise RuntimeError("未安装 ruyiPage，请先执行 `pip install -e .`。") from exc

        metadata = install(root=str(self.browsers_dir), force=False)
        browser_path = Path(metadata["executable_path"]).resolve()
        if not browser_path.is_file():
            raise RuntimeError(f"Firefox 安装完成但未找到可执行文件: {browser_path}")
        return browser_path

    async def start(self) -> None:
        """确保当前任务有可用浏览器；已启动时直接复用。"""
        async with self._lock:
            if self._page is not None:
                logger.info("[browser] 浏览器已启动，直接复用当前页面")
                return

            logger.info("[browser] 准备启动浏览器")
            browser_path = self._find_browser()
            if browser_path is None:
                logger.info("[browser] 未找到本地 Firefox runtime，开始安装")
                browser_path = await asyncio.to_thread(self._install_browser)

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "[browser] 启动 Firefox runtime=%s profile=%s headless=%s",
                browser_path,
                self.profile_dir,
                self.headless,
            )

            self._page = await launch(
                browser_path=str(browser_path),
                user_dir=str(self.profile_dir),
                headless=self.headless,
                close_on_exit=True,
            )
            logger.info("[browser] Firefox 启动完成")

            if not self.headless:
                try:
                    logger.info("[browser] 设置 Firefox 全屏")
                    await self._page.window.fullscreen()
                    logger.info("[browser] Firefox 已进入全屏")
                except Exception:
                    logger.exception("[browser] 全屏失败，尝试最大化窗口")
                    await self._page.window.maximize()
                    logger.info("[browser] Firefox 已最大化")

            if self.start_url:
                logger.info("[browser] 打开启动页: %s", self.start_url)
                await self._page.get(self.start_url)
                logger.info("[browser] 启动页加载完成")

    async def stop(self) -> None:
        async with self._lock:
            page = self._page
            self._page = None
            if page is not None:
                logger.info("[browser] 正在关闭浏览器")
                await page.quit()
                logger.info("[browser] 浏览器已关闭")

    async def shutdown(self) -> None:
        try:
            await self.stop()
        except Exception:
            # 用户手工关闭 Firefox 时，应用退出不应因此失败。
            pass

    def _page_required(self) -> AsyncFirefoxPage:
        if self._page is None:
            raise RuntimeError("浏览器未启动。")
        return self._page

    async def navigate(self, url: str) -> None:
        logger.info("[browser] navigate -> %s", url)
        started = time.perf_counter()
        await self._page_required().get(url)
        logger.info("[browser] navigate 完成 %.2fs", time.perf_counter() - started)

    async def open_for_manual_login(self) -> str:
        """启动/复用浏览器并打开配置的 BOSS 页面，供用户手动登录。"""
        await self.start()
        url = self.start_url or "https://www.zhipin.com/"
        await self.navigate(url)
        return url

    async def wait_for_element(self, selector: str, *, timeout: float = 10) -> Any:
        if not selector:
            raise RuntimeError("浏览器选择器尚未配置。")
        logger.info("[browser] 等待元素 selector=%s timeout=%.1fs", selector, timeout)
        element = await self._page_required().ele(selector, timeout=timeout)
        if not element:
            logger.warning("[browser] 等待元素超时 selector=%s", selector)
            raise RuntimeError(f"等待页面元素超时: {selector}")
        logger.info("[browser] 元素已出现 selector=%s", selector)
        return element

    async def elements(self, selector: str, *, timeout: float = 1) -> list[Any]:
        if not selector:
            raise RuntimeError("浏览器选择器尚未配置。")
        elements = list(await self._page_required().eles(selector, timeout=timeout))
        logger.info("[browser] 查询元素 selector=%s count=%s", selector, len(elements))
        return elements

    async def element_text(self, element: Any) -> str:
        return str(await element.get_text() or "").strip()

    async def click_element(self, element: Any) -> None:
        logger.info("[browser] 点击元素对象")
        await element.click_self()  # pyright: ignore[reportCallIssue]
        logger.info("[browser] 点击元素对象完成")

    async def scroll_element_into_view(self, element: Any, *, center: bool = False) -> None:
        logger.info("[browser] 将元素滚动到视野 center=%s", center)
        await element.scroll.to_see(center=center)

    async def viewport_height(self) -> int:
        value = await self._page_required().run_js("return window.innerHeight;")
        return int(value or 0)

    async def element_viewport_box(self, element: Any) -> dict[str, float]:
        result = await element.run_js(
            "function(){"
            "const r=this.getBoundingClientRect();"
            "return {top:r.top,bottom:r.bottom,height:r.height};"
            "}"
        )
        if not isinstance(result, dict):
            return {"top": 0.0, "bottom": 0.0, "height": 0.0}
        return {
            "top": float(result.get("top", 0.0)),
            "bottom": float(result.get("bottom", 0.0)),
            "height": float(result.get("height", 0.0)),
        }

    async def capture_json(
        self,
        target: str,
        action: Callable[[], Awaitable[None]],
        *,
        timeout: float = 10,
    ) -> dict[str, Any] | None:
        """执行页面动作，并返回该动作触发的指定接口 JSON 响应。"""
        page = self._page_required()
        capture = page.capture
        logger.info("[browser][capture] 开始监听 target=%s", target)
        await capture.start(target, collect_bodies=True)
        started = time.perf_counter()
        try:
            logger.info("[browser][capture] 执行触发动作 target=%s", target)
            await action()
            logger.info(
                "[browser][capture] 动作完成，开始等待响应 target=%s timeout=%.1fs",
                target,
                timeout,
            )
            packet = await capture.wait(timeout=timeout)
            elapsed = time.perf_counter() - started
            if packet is None:
                logger.warning(
                    "[browser][capture] 等待响应超时 target=%s elapsed=%.2fs",
                    target,
                    elapsed,
                )
                return None
            logger.info(
                "[browser][capture] 捕获响应 target=%s status=%s failed=%s elapsed=%.2fs url=%s",
                target,
                packet.response_status,
                packet.is_failed,
                elapsed,
                packet.url,
            )
            if packet.is_failed or packet.response_status >= 400:
                logger.warning(
                    "[browser][capture] 响应不可用 target=%s status=%s failed=%s",
                    target,
                    packet.response_status,
                    packet.is_failed,
                )
                return None
            logger.info("[browser][capture] 读取响应体 target=%s", target)
            body = packet.get_response_body(timeout)
            if not body:
                logger.warning("[browser][capture] 响应体为空 target=%s", target)
                return None
            payload = json.loads(body)
            if not isinstance(payload, dict):
                logger.warning("[browser][capture] JSON 顶层不是对象 target=%s", target)
                return None
            logger.info("[browser][capture] JSON 解析完成 target=%s", target)
            return payload
        except Exception:
            logger.exception("[browser][capture] 抓包流程异常 target=%s", target)
            raise
        finally:
            logger.info("[browser][capture] 停止监听 target=%s", target)
            try:
                await capture.stop()
            except Exception:
                logger.exception("[browser][capture] 停止监听失败 target=%s", target)

    async def click(self, selector: str) -> None:
        logger.info("[browser] 点击 selector=%s", selector)
        element = await self._page_required().ele(selector)
        if not element:
            logger.warning("[browser] 未找到可点击元素 selector=%s", selector)
            raise RuntimeError(f"未找到可点击元素: {selector}")
        # ruyiPage 1.2.x 生成的类型信息把 click_self 标成 property，运行时实际是异步方法。
        await element.click_self()  # pyright: ignore[reportCallIssue]
        logger.info("[browser] 点击完成 selector=%s", selector)

    async def click_if_present(self, selector: str, *, timeout: float = 2) -> bool:
        """点击首个真正可见的匹配元素；不存在可见元素时返回 False。

        弹窗类 DOM 经常会同时保留隐藏模板和当前展示节点。``page.ele()`` 只取第一个
        匹配项时可能拿到尺寸为 0 的隐藏节点，随后被 ruyiPage 判定为不可点击。
        """
        logger.info("[browser] 尝试可选点击 selector=%s timeout=%.1fs", selector, timeout)
        deadline = asyncio.get_running_loop().time() + timeout
        page = self._page_required()

        while True:
            elements = list(await page.eles(selector, timeout=0.2))
            logger.info("[browser] 可选点击匹配 selector=%s count=%s", selector, len(elements))

            zero_rect_candidates: list[tuple[int, Any]] = []
            for index, element in enumerate(elements):
                state = await element.run_js(
                    "function(){"
                    "const r=this.getBoundingClientRect();"
                    "const s=window.getComputedStyle(this);"
                    "return {"
                    "connected:this.isConnected,"
                    "width:r.width,height:r.height,top:r.top,left:r.left,"
                    "display:s.display,visibility:s.visibility,opacity:s.opacity"
                    "};"
                    "}"
                )
                if not isinstance(state, dict):
                    continue

                width = float(state.get("width", 0) or 0)
                height = float(state.get("height", 0) or 0)
                rendered = (
                    bool(state.get("connected", True))
                    and state.get("display") != "none"
                    and state.get("visibility") not in {"hidden", "collapse"}
                    and state.get("opacity") != "0"
                )
                visible = rendered and width > 0 and height > 0
                logger.info(
                    "[browser] 可选元素状态 selector=%s index=%s visible=%s "
                    "rect=(%.1f,%.1f %.1fx%.1f) display=%s visibility=%s opacity=%s",
                    selector,
                    index,
                    visible,
                    float(state.get("left", 0) or 0),
                    float(state.get("top", 0) or 0),
                    width,
                    height,
                    state.get("display"),
                    state.get("visibility"),
                    state.get("opacity"),
                )
                if rendered and not visible:
                    zero_rect_candidates.append((index, element))
                    continue
                if not visible:
                    continue

                try:
                    await element.click_self()  # pyright: ignore[reportCallIssue]
                except Exception as exc:
                    # 已确认是当前可见节点后再使用 JS 点击，避免隐藏模板被误触发。
                    logger.warning(
                        "[browser] 坐标点击失败，改用 JS 点击 selector=%s index=%s error=%s",
                        selector,
                        index,
                        exc,
                    )
                    await element.click_self(by_js=True)  # pyright: ignore[reportCallIssue]

                logger.info("[browser] 可选点击完成 selector=%s index=%s", selector, index)
                return True

            # 某些纯图标节点（例如 <i class="icon-close">）自身没有布局尺寸，
            # 实际图标由 ::before 或父节点渲染。只有唯一一个“已渲染但 0 尺寸”的
            # 匹配项时才用 JS 点击，避免在存在多个隐藏模板时误点。
            if len(zero_rect_candidates) == 1:
                index, element = zero_rect_candidates[0]
                logger.info(
                    "[browser] 唯一匹配元素无可点击矩形，使用 JS 点击 selector=%s index=%s",
                    selector,
                    index,
                )
                await element.click_self(by_js=True)  # pyright: ignore[reportCallIssue]
                logger.info("[browser] 可选 JS 点击完成 selector=%s index=%s", selector, index)
                return True

            if asyncio.get_running_loop().time() >= deadline:
                logger.info("[browser] 未发现可见的可选元素 selector=%s", selector)
                return False
            await asyncio.sleep(0.05)

    async def fill(self, selector: str, value: str) -> None:
        element = await self._page_required().ele(selector)
        # 同上，input 的运行时签名是 async input(text, clear=True, by_js=False)。
        await element.input(value, clear=True)  # pyright: ignore[reportCallIssue]

    async def evaluate(self, script: str) -> Any:
        return await self._page_required().run_js(script)

    async def scroll(self, delta_y: int) -> None:
        """按“手势方向”滚动页面。

        负数表示向上滑（继续向下浏览页面），正数表示向下滑（向上返回页面）。
        ``window.scrollBy`` 使用的是页面位移方向，因此这里需要取反。
        """
        logger.info("[browser] scroll gesture_delta_y=%s", int(delta_y))
        position = await self._page_required().run_js(
            f"window.scrollBy(0, {-int(delta_y)}); return window.scrollY;",
            as_expr=False,
        )
        logger.info("[browser] scroll 完成 scrollY=%s", position)

    async def scroll_page(self, delta_y: int) -> None:
        """按页面位移方向滚动；正数向下，负数向上。"""
        logger.info("[browser] scroll_page delta_y=%s", int(delta_y))
        position = await self._page_required().run_js(
            f"window.scrollBy(0, {int(delta_y)}); return window.scrollY;",
            as_expr=False,
        )
        logger.info("[browser] scroll_page 完成 scrollY=%s", position)
