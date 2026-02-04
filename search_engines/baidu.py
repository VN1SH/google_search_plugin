import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode
from bs4 import BeautifulSoup

import aiohttp

from .base import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)


class BaiduEngine(BaseSearchEngine):
    """百度搜索引擎实现"""

    base_urls: List[str]

    SELECTOR_CONFIG: Dict[str, Dict[str, Any]] = {
        "url": {
            "primary": "h3 > a",
            "fallback": [
                "h3 a",
                "a.c-showurl",
                "a[href]",
            ],
        },
        "title": {
            "primary": "h3 > a",
            "fallback": [
                "h3 a",
                "h3",
                ".c-title",
            ],
        },
        "text": {
            "primary": ".c-abstract",
            "fallback": [
                ".result-summary",
                ".content-right_8Zs40",
                ".c-span-last",
                ".c-span9",
            ],
        },
        "links": {
            "primary": "#content_left > div.result, #content_left > div.c-container",
            "fallback": [
                "#content_left > div",
                "div.result",
                "div.c-container",
            ],
        },
        "next": {
            "primary": "a#page-next",
            "fallback": [
                "a.n",
                "#page a.n",
            ],
        },
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.base_urls = ["https://www.baidu.com", "https://m.baidu.com"]
        self.headers.update({
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

    def _set_selector(self, selector: str) -> str:
        config = self.SELECTOR_CONFIG.get(selector, {})
        return config.get("primary", "")

    def _get_fallback_selectors(self, selector: str) -> List[str]:
        config = self.SELECTOR_CONFIG.get(selector, {})
        return config.get("fallback", [])

    async def _resolve_redirect(self, url: str) -> str:
        if not url:
            return ""
        headers = self.headers
        headers["Referer"] = url
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT),
                    proxy=self.proxy,
                    allow_redirects=True,
                ) as resp:
                    return str(resp.url)
            except Exception:
                return url

    async def _get_next_page(self, query: str, *, base_url: Optional[str] = None) -> str:
        params = {
            "wd": query,
            "ie": "utf-8",
        }
        search_url = f"{base_url or self.base_urls[0]}/s?{urlencode(params)}"
        logger.info(f"Requesting Baidu search URL: {search_url}")
        return await self._get_html(search_url)

    def _get_link_elements(self, soup: BeautifulSoup) -> List[Any]:
        links_selector = self._set_selector("links")
        if links_selector:
            links = soup.select(links_selector)
            if links:
                return links
        for fallback_selector in self._get_fallback_selectors("links"):
            links = soup.select(fallback_selector)
            if links:
                logger.info(f"Fallback selector '{fallback_selector}' found {len(links)} results")
                return links
        return []

    def _select_with_fallback(self, element: Any, selector_name: str) -> Optional[Any]:
        primary = self._set_selector(selector_name)
        if primary:
            found = element.select_one(primary)
            if found:
                return found
        for fallback in self._get_fallback_selectors(selector_name):
            found = element.select_one(fallback)
            if found:
                return found
        return None

    async def search(self, query: str, num_results: int) -> List[SearchResult]:
        try:
            resp = await self._get_next_page(query)
            soup = BeautifulSoup(resp, "html.parser")
            links = self._get_link_elements(soup)
            if not links:
                resp = await self._get_next_page(query, base_url=self.base_urls[1])
                soup = BeautifulSoup(resp, "html.parser")
                links = self._get_link_elements(soup)
            if not links:
                return []

            results: List[SearchResult] = []
            for idx, link in enumerate(links):
                title_elem = self._select_with_fallback(link, "title")
                url_elem = self._select_with_fallback(link, "url")
                text_elem = self._select_with_fallback(link, "text")

                title = self.tidy_text(title_elem.text) if title_elem else ""
                url_raw = url_elem.get("href") if url_elem else ""
                url = self._normalize_url(url_raw, base_url=self.base_urls[0])
                snippet = self.tidy_text(text_elem.text) if text_elem else ""

                if title and url:
                    if "baidu.com/link?" in url:
                        url = await self._resolve_redirect(url)
                    results.append(SearchResult(title=title, url=url, snippet=snippet, abstract=snippet, rank=idx))

            logger.info(f"Returning {len(results[:num_results])} Baidu results for query '{query}'")
            return results[:num_results]
        except Exception as e:
            logger.error(f"Error in Baidu search for query {query}: {e}", exc_info=True)
            return []
