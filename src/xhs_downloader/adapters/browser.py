from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from ..config import AppConfig
from ..domain.errors import (
    AuthExpiredError,
    DependencyMissingError,
    DownloadError,
    ParseError,
    RateLimitedError,
)
from ..domain.models import DownloadTask, NoteRecord, NoteSummary
from ..infra.logging import get_logger
from ..infra.utils import ensure_directory, first_non_empty_line, normalize_count, published_at_from_text


class PlaywrightBrowserSession:
    def __init__(
        self,
        playwright: Any,
        browser: Any,
        context: Any,
        config: AppConfig,
    ) -> None:
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._config = config
        self._logger = get_logger(self.__class__.__name__)
        self._main_page = self._create_page()
        self._worker_page: Optional[Any] = None
        self._last_search_url = ""
        self._focus_main_page()

    def close(self) -> None:
        for page in (self._worker_page, self._main_page):
            if page is None:
                continue
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                self._logger.debug("关闭页面时发生异常，继续回收浏览器上下文", exc_info=True)
        self._context.close()
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> "PlaywrightBrowserSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def search_notes(self, keyword: str, pages: int, sort: str) -> List[NoteSummary]:
        page = self._ensure_main_page_available()
        self._focus_main_page()
        results: List[NoteSummary] = []
        seen_ids = set()
        try:
            url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_explore_feed"
            self._last_search_url = url
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(self._config.search_page_wait_ms)
            self._ensure_page_available(page)
            self._apply_sort(page, sort)

            rank = 1
            for _ in range(pages):
                page.wait_for_timeout(self._config.crawl_delay_ms)
                raw_cards = page.evaluate(
                    """
                    () => {
                      const anchors = Array.from(
                        document.querySelectorAll("a[href*='/explore/'], a[href*='/discovery/item/']")
                      );
                      return anchors.map((anchor) => {
                        const container = anchor.closest("section") || anchor.closest("div") || anchor;
                        const titleNode = container.querySelector("img[alt], a[title], h3, h4");
                        return {
                          href: anchor.href || "",
                          title: (
                            anchor.getAttribute("title") ||
                            (titleNode && (titleNode.getAttribute("alt") || titleNode.textContent)) ||
                            ""
                          ).trim(),
                          text: (container.innerText || anchor.innerText || "").trim()
                        };
                      }).filter(item => item.href);
                    }
                    """
                )
                for raw in raw_cards:
                    summary = self._build_summary(raw, rank)
                    if summary is None or summary.note_id in seen_ids:
                        continue
                    seen_ids.add(summary.note_id)
                    results.append(summary)
                    rank += 1

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(self._config.search_page_wait_ms)
                self._ensure_page_available(page)

            return results
        except (AuthExpiredError, RateLimitedError):
            raise
        except Exception as exc:
            raise ParseError(f"搜索结果解析失败: {exc}") from exc

    def fetch_note_detail(self, summary: NoteSummary) -> NoteRecord:
        page = self._ensure_main_page_available()
        try:
            self.wait_with_jitter("detail")
            detail_url = self._open_note_detail_from_search(page, summary)
            self._ensure_page_available(page)
            payload = page.evaluate(
                """
                () => {
                  const textOf = (selectors) => {
                    for (const selector of selectors) {
                      const el = document.querySelector(selector);
                      if (el && el.innerText && el.innerText.trim()) {
                        return el.innerText.trim();
                      }
                    }
                    return "";
                  };

                  return {
                    title: textOf(["h1", "main h1", "[class*='title']"]),
                    description: textOf(["article", "[class*='desc']", "[class*='content']"]),
                    author: textOf(["[class*='author'] a", "[class*='author'] span", "a[href*='/user/profile/']"]),
                    bodyText: document.body ? document.body.innerText : "",
                    tags: Array.from(document.querySelectorAll("a[href*='search_result'], [class*='tag']")).map(
                      (el) => (el.innerText || "").trim()
                    ).filter(Boolean),
                    noteImages: Array.from(document.querySelectorAll("img")).filter((img) => {
                      return Boolean(img.closest(".img-container")) && Boolean(img.closest(".swiper-slide"));
                    }).map((img) => ({
                      src: img.currentSrc || img.src || "",
                      width: img.naturalWidth || img.width || 0,
                      height: img.naturalHeight || img.height || 0,
                      alt: img.alt || ""
                    })).filter((img) => img.src),
                    images: Array.from(document.querySelectorAll("img")).map((img) => ({
                      src: img.currentSrc || img.src || "",
                      width: img.naturalWidth || img.width || 0,
                      height: img.naturalHeight || img.height || 0,
                      alt: img.alt || ""
                    })).filter((img) => img.src)
                  };
                }
                """
            )
            payload["pageUrl"] = detail_url
            return self._build_note_record(summary, payload)
        except (AuthExpiredError, RateLimitedError):
            raise
        except Exception as exc:
            raise ParseError(f"笔记详情解析失败: note_id={summary.note_id}, error={exc}") from exc
        finally:
            self._restore_search_page(page)
            self._focus_main_page()

    def download_image(self, task: DownloadTask, referer_url: str) -> Path:
        output_dir = ensure_directory(Path(task.output_dir))
        target_path = output_dir / task.filename
        if target_path.exists() and target_path.stat().st_size > 0:
            self._logger.debug("文件已存在，跳过下载: %s", target_path)
            return target_path

        self.wait_with_jitter("download")
        temp_path = Path(f"{target_path}.part")
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": referer_url or "https://www.xiaohongshu.com/",
            "User-Agent": self._config.user_agent,
        }
        try:
            response = self._context.request.get(
                task.source_url,
                headers=headers,
                timeout=self._config.download_timeout * 1000,
            )
            content = response.body()
            risk_reason = self.detect_risk_from_response(response, content)
            if risk_reason:
                raise RateLimitedError(
                    f"图片下载触发风控: task_id={task.task_id}, status={getattr(response, 'status', 0)}, "
                    f"content_type={self._content_type_of(response) or 'unknown'}, reason={risk_reason}, "
                    f"url={task.source_url}"
                )

            status = int(getattr(response, "status", 0) or 0)
            content_type = self._content_type_of(response)
            if status >= 400:
                raise DownloadError(f"图片资源不可用: task_id={task.task_id}, status={status}, url={task.source_url}")
            if not content:
                raise RateLimitedError(f"图片下载响应为空: task_id={task.task_id}, url={task.source_url}")
            if not content_type.startswith("image/"):
                raise DownloadError(
                    f"图片资源不可用: task_id={task.task_id}, content_type={content_type or 'unknown'}, url={task.source_url}"
                )

            temp_path.write_bytes(content)
            temp_path.replace(target_path)
            return target_path
        except RateLimitedError:
            raise
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(f"浏览器会话下载失败: task_id={task.task_id}, url={task.source_url}, error={exc}") from exc
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    self._logger.debug("临时文件清理失败: %s", temp_path, exc_info=True)

    def wait_with_jitter(self, kind: str) -> None:
        delays = {
            "detail": self._config.detail_delay_ms,
            "download": self._config.download_delay_ms,
            "search": self._config.crawl_delay_ms,
        }
        base_ms = delays.get(kind, self._config.crawl_delay_ms)
        jitter_ms = self._config.request_jitter_ms if kind in {"detail", "download"} else 0
        delta = random.randint(-jitter_ms, jitter_ms) if jitter_ms > 0 else 0
        wait_ms = max(0, base_ms + delta)
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)

    def detect_risk_from_response(self, response: Any, content: Optional[bytes] = None) -> Optional[str]:
        status = int(getattr(response, "status", 0) or 0)
        if status in {403, 429}:
            return f"响应状态码 {status}"

        body = content if content is not None else response.body()
        if not body:
            return "响应内容为空"

        content_type = self._content_type_of(response)
        if "text/html" in content_type:
            html_text = body[:4096].decode("utf-8", errors="ignore")
            signal = self._risk_signal_from_text(html_text)
            return f"HTML 验证页: {signal}" if signal else "返回 HTML 页面"

        if content_type and not content_type.startswith("image/"):
            text = body[:2048].decode("utf-8", errors="ignore")
            signal = self._risk_signal_from_text(text)
            if signal:
                return f"非图片响应命中风控文案: {signal}"
        return None

    def capture_diagnostics(self, artifact_root: Path, prefix: str) -> List[str]:
        if not self._config.screenshot_on_failure:
            return []

        artifact_dir = ensure_directory(artifact_root)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        captures: List[str] = []
        for label, page in (("main", self._main_page), ("worker", self._worker_page)):
            if page is None:
                continue
            try:
                if page.is_closed():
                    continue
                target = artifact_dir / f"{prefix}_{label}_{stamp}.png"
                page.screenshot(path=str(target), full_page=True)
                captures.append(str(target))
            except Exception:
                self._logger.debug("截图保存失败: prefix=%s, label=%s", prefix, label, exc_info=True)
        return captures

    def _ensure_page_available(self, page: Any) -> None:
        body_text = page.text_content("body") or ""
        auth_signal = self._auth_signal_from_text(body_text)
        if auth_signal:
            raise AuthExpiredError(f"当前登录态无效，请重新执行 xhs login: {auth_signal}")

        risk_signal = self._risk_signal_from_text(body_text)
        if risk_signal:
            raise RateLimitedError(f"触发风控验证，请稍后重试: {risk_signal}")

    def _apply_sort(self, page: Any, sort: str) -> None:
        normalized = (sort or "comprehensive").strip().lower()
        label_map = {
            "latest": "最新",
            "newest": "最新",
            "hot": "最热",
            "hottest": "最热",
            "comprehensive": "综合",
            "default": "综合",
            "综合": "综合",
            "最新": "最新",
            "最热": "最热",
        }
        label = label_map.get(normalized, "综合")
        if label == "综合":
            return
        try:
            page.get_by_text(label, exact=True).click(timeout=2500)
            page.wait_for_timeout(self._config.search_page_wait_ms)
        except Exception:
            self._logger.debug("未能切换排序，继续使用默认排序: %s", label)

    def _build_summary(self, raw: Dict[str, Any], rank: int) -> Optional[NoteSummary]:
        href = raw.get("href", "").strip()
        note_id = self._extract_note_id(href)
        if not note_id:
            return None

        text = raw.get("text", "")
        title = raw.get("title") or first_non_empty_line(text) or note_id
        like_count = self._metric_from_text(text, ("点赞", "赞"))
        comment_count = self._metric_from_text(text, ("评论",))
        author_name = self._author_from_text(text, title)

        return NoteSummary(
            note_id=note_id,
            title=title,
            author_name=author_name,
            like_count=like_count,
            comment_count=comment_count,
            note_url=href,
            search_rank=rank,
            raw_payload=raw,
        )

    def _build_note_record(self, summary: NoteSummary, payload: Dict[str, Any]) -> NoteRecord:
        body_text = payload.get("bodyText", "")
        preferred_images = payload.get("noteImages") or payload.get("images", [])
        images = self._extract_image_urls(preferred_images)
        if not images:
            raise ParseError(f"未提取到图片: note_id={summary.note_id}")

        like_count = self._metric_from_text(body_text, ("点赞", "赞")) or summary.like_count
        comment_count = self._metric_from_text(body_text, ("评论",)) or summary.comment_count

        return NoteRecord(
            note_id=summary.note_id,
            title=(payload.get("title") or summary.title or summary.note_id).strip(),
            description=(payload.get("description") or body_text[:500]).strip(),
            author_id="",
            author_name=(payload.get("author") or summary.author_name or "").strip(),
            published_at=published_at_from_text(body_text),
            tags=self._unique_tags(payload.get("tags", [])),
            like_count=like_count,
            comment_count=comment_count,
            note_url=(payload.get("pageUrl") or summary.note_url).strip(),
            images=images,
        )

    def _extract_image_urls(self, raw_images: List[Dict[str, Any]]) -> List[str]:
        unique = []
        seen = set()
        for item in raw_images:
            src = (item.get("src") or "").strip()
            width = int(item.get("width", 0) or 0)
            height = int(item.get("height", 0) or 0)
            lower_src = src.lower()
            if not src or src in seen:
                continue
            if not lower_src.startswith("http"):
                continue
            if width < 200 or height < 200:
                continue
            if any(token in lower_src for token in ("avatar", "icon", "logo", "qr", ".svg", "picasso-static.xiaohongshu.com/fe-platform")):
                continue
            seen.add(src)
            unique.append(src)
        return unique

    def _extract_note_id(self, href: str) -> str:
        if not href:
            return ""
        match = re.search(r"/(?:explore|discovery/item)/([^/?#]+)", href)
        if match:
            return match.group(1)
        return ""

    def _metric_from_text(self, text: str, labels: Any) -> int:
        for label in labels:
            match = re.search(rf"{label}\s*([0-9.,万wWkK]+)", text)
            if match:
                return normalize_count(match.group(1))

        numeric_tokens = re.findall(r"\d+(?:\.\d+)?[万wWkK]?", text)
        if numeric_tokens:
            return normalize_count(numeric_tokens[0])
        return 0

    def _author_from_text(self, text: str, title: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidates = []
        for line in lines:
            if line == title:
                continue
            if len(line) > 24:
                continue
            if normalize_count(line) > 0:
                continue
            candidates.append(line)
        return candidates[-1] if candidates else ""

    def _unique_tags(self, tags: List[str]) -> List[str]:
        seen = set()
        results = []
        for tag in tags:
            cleaned = tag.strip().lstrip("#")
            if not cleaned or cleaned in seen or len(cleaned) > 24:
                continue
            seen.add(cleaned)
            results.append(cleaned)
        return results

    def _create_page(self) -> Any:
        page = self._context.new_page()
        return page

    def _open_note_detail_from_search(self, page: Any, summary: NoteSummary) -> str:
        target = self._find_search_card(page, summary)
        if target is None:
            raise ParseError(f"未找到可点击的搜索结果卡片: note_id={summary.note_id}")

        previous_url = page.url
        page.mouse.click(float(target["x"]), float(target["y"]))
        try:
            page.wait_for_function(
                "(args) => location.href !== args.previousUrl && location.href.includes(args.noteId)",
                {"previousUrl": previous_url, "noteId": summary.note_id},
                timeout=10000,
            )
        except Exception:
            page.wait_for_timeout(self._config.note_detail_wait_ms)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(self._config.note_detail_wait_ms)
        return page.url

    def _find_search_card(self, page: Any, summary: NoteSummary) -> Optional[Dict[str, Any]]:
        target = self._locate_search_card(page, summary)
        if target is not None:
            return target

        viewport_height = int(page.evaluate("() => window.innerHeight || 900") or 900)
        scroll_height = int(page.evaluate("() => document.body.scrollHeight || 0") or 0)
        estimated_offset = max(0, ((max(summary.search_rank, 1) - 1) // 4) * 420)
        candidates = [0, estimated_offset]
        step = max(int(viewport_height * 0.8), 400)
        for offset in range(0, scroll_height + step, step):
            candidates.append(offset)

        visited = set()
        for offset in candidates:
            normalized = max(0, min(int(offset), max(scroll_height - viewport_height, 0)))
            if normalized in visited:
                continue
            visited.add(normalized)
            page.evaluate("(y) => window.scrollTo(0, y)", normalized)
            page.wait_for_timeout(350)
            target = self._locate_search_card(page, summary)
            if target is not None:
                return target
        return None

    def _locate_search_card(self, page: Any, summary: NoteSummary) -> Optional[Dict[str, Any]]:
        return page.evaluate(
            """
            (args) => {
              const normalize = (value) => (value || '').trim();
              const noteId = normalize(args.noteId);
              const title = normalize(args.title);
              const sections = Array.from(document.querySelectorAll('section'));
              const candidates = sections.map((section) => {
                const anchor = section.querySelector("a[href*='/explore/'], a[href*='/discovery/item/']");
                if (!anchor) {
                  return null;
                }
                const href = anchor.href || '';
                if (noteId && !href.includes(noteId)) {
                  return null;
                }
                const rect = section.getBoundingClientRect();
                const style = window.getComputedStyle(section);
                if (rect.width <= 100 || rect.height <= 40 || style.visibility === 'hidden' || style.display === 'none') {
                  return null;
                }
                const text = normalize(section.innerText || anchor.innerText || anchor.textContent || '');
                let score = 0;
                if (noteId && href.includes(noteId)) {
                  score += 100;
                }
                if (title && text.includes(title)) {
                  score += 50;
                }
                if (rect.top >= 100) {
                  score += 10;
                }
                return { section, href, text, score };
              }).filter(Boolean);
              if (!candidates.length) {
                return null;
              }
              candidates.sort((left, right) => right.score - left.score);
              const winner = candidates[0].section;
              winner.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
              const rect = winner.getBoundingClientRect();
              const anchor = winner.querySelector("a[href*='/explore/'], a[href*='/discovery/item/']");
              return {
                href: anchor ? (anchor.href || '') : '',
                text: normalize(winner.innerText || ''),
                x: rect.left + rect.width / 2,
                y: rect.top + Math.min(rect.height / 2, 160),
              };
            }
            """,
            {"noteId": summary.note_id, "title": summary.title},
        )

    def _restore_search_page(self, page: Any) -> None:
        try:
            if "/search_result" in (page.url or ""):
                return
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(self._config.search_page_wait_ms)
        except Exception:
            if self._last_search_url:
                page.goto(self._last_search_url, wait_until="domcontentloaded")
                page.wait_for_timeout(self._config.search_page_wait_ms)

    def _ensure_main_page_available(self) -> Any:
        try:
            if self._main_page.is_closed():
                self._main_page = self._create_page()
        except Exception:
            self._main_page = self._create_page()
        return self._main_page

    def _ensure_worker_page_available(self) -> Any:
        if self._worker_page is None:
            self._worker_page = self._create_page()
        else:
            try:
                if self._worker_page.is_closed():
                    self._worker_page = self._create_page()
            except Exception:
                self._worker_page = self._create_page()
        return self._worker_page

    def _focus_main_page(self) -> None:
        try:
            page = self._ensure_main_page_available()
            page.bring_to_front()
        except Exception:
            self._logger.debug("切回主页面失败", exc_info=True)

    def _content_type_of(self, response: Any) -> str:
        headers = getattr(response, "headers", {}) or {}
        if isinstance(headers, dict):
            for key, value in headers.items():
                if str(key).lower() == "content-type":
                    return str(value).split(";")[0].strip().lower()
        return ""

    def _auth_signal_from_text(self, text: str) -> Optional[str]:
        for signal in ("登录后查看更多", "立即登录"):
            if signal in text:
                return signal
        return None

    def _risk_signal_from_text(self, text: str) -> Optional[str]:
        for signal in ("访问验证", "安全验证", "请求过于频繁", "频繁访问", "请完成下列验证", "验证码"):
            if signal in text:
                return signal
        return None


class PlaywrightBrowserClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = get_logger(self.__class__.__name__)

    def login_and_save_session(
        self,
        storage_state_path: Path,
        browser_profile_dir: Path,
        wait_for_confirmation: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        sync_playwright = self._require_playwright()
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        browser_profile_dir.mkdir(parents=True, exist_ok=True)

        def _wait_for_confirmation() -> None:
            print("浏览器已打开，请在页面中完成登录。完成后回到终端按回车保存会话。")
            input()

        wait_for_confirmation = wait_for_confirmation or _wait_for_confirmation

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(user_agent=self._config.user_agent)
            page = context.new_page()
            page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
            wait_for_confirmation()
            cookies = context.cookies()
            context.storage_state(path=str(storage_state_path))
            browser.close()

        is_valid = any(cookie.get("name") in {"a1", "webId"} for cookie in cookies)
        return {
            "is_valid": is_valid,
            "cookie_count": len(cookies),
        }

    def validate_session(self, storage_state_path: Path) -> bool:
        if not storage_state_path.exists():
            return False
        try:
            payload = json.loads(storage_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        cookies = payload.get("cookies", [])
        return any(cookie.get("name") in {"a1", "webId"} for cookie in cookies)

    def open_session(self, storage_state_path: Path) -> PlaywrightBrowserSession:
        sync_playwright = self._require_playwright()
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=self._config.headless)
        kwargs: Dict[str, Any] = {"user_agent": self._config.user_agent}
        if storage_state_path.exists():
            kwargs["storage_state"] = str(storage_state_path)
        context = browser.new_context(**kwargs)
        return PlaywrightBrowserSession(playwright, browser, context, self._config)

    def _require_playwright(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover - runtime only
            raise DependencyMissingError(
                "当前环境缺少 Playwright，请先执行 `pip install -e .[runtime]` "
                "并运行 `playwright install chromium`。"
            ) from exc
        return sync_playwright
