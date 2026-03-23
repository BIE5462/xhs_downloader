from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ..config import AppConfig
from ..domain.errors import AuthExpiredError, DependencyMissingError, ParseError, RateLimitedError
from ..domain.models import NoteRecord, NoteSummary
from ..infra.logging import get_logger
from ..infra.utils import first_non_empty_line, normalize_count, published_at_from_text


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

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> "PlaywrightBrowserSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def search_notes(self, keyword: str, pages: int, sort: str) -> List[NoteSummary]:
        page = self._context.new_page()
        results: List[NoteSummary] = []
        seen_ids = set()
        try:
            url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_explore_feed"
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

            return results
        except Exception as exc:
            raise ParseError(f"搜索结果解析失败: {exc}") from exc
        finally:
            page.close()

    def fetch_note_detail(self, summary: NoteSummary) -> NoteRecord:
        page = self._context.new_page()
        try:
            page.goto(summary.note_url, wait_until="domcontentloaded")
            page.wait_for_timeout(self._config.note_detail_wait_ms)
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
            return self._build_note_record(summary, payload)
        except Exception as exc:
            raise ParseError(f"笔记详情解析失败: note_id={summary.note_id}, error={exc}") from exc
        finally:
            page.close()

    def _ensure_page_available(self, page: Any) -> None:
        body_text = page.text_content("body") or ""
        if "登录后查看更多" in body_text or "立即登录" in body_text:
            raise AuthExpiredError("当前登录态无效，请重新执行 xhs login")
        if "访问验证" in body_text or "安全验证" in body_text or "请求过于频繁" in body_text:
            raise RateLimitedError("触发风控验证，请稍后重试")

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
        images = self._extract_image_urls(payload.get("images", []))
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
            note_url=summary.note_url,
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
            if any(token in lower_src for token in ("avatar", "icon", "logo", "qr", ".svg")):
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


class PlaywrightBrowserClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = get_logger(self.__class__.__name__)

    def login_and_save_session(
        self,
        storage_state_path: Path,
        browser_profile_dir: Path,
    ) -> Dict[str, Any]:
        sync_playwright = self._require_playwright()
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        browser_profile_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context(user_agent=self._config.user_agent)
            page = context.new_page()
            page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
            print("浏览器已打开，请在页面中完成登录。完成后回到终端按回车保存会话。")
            input()
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
