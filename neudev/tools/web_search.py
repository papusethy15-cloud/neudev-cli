"""Web search tool for NeuDev — search the web for documentation and solutions."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from neudev.tools.base import BaseTool, ToolError


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor for search result snippets."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    return extractor.get_text()


class WebSearchTool(BaseTool):
    """Search the web for documentation, error solutions, and API references."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for documentation, error solutions, code examples, "
            "and API references. Returns top results with title, URL, and snippet. "
            "Use this when you need external information not available in the workspace."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Be specific for better results.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5, max 10).",
                },
            },
            "required": ["query"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        query = args.get("query", "")
        return f"Search the web for: {query}"

    def execute(self, query: str, max_results: int = 5, **kwargs) -> str:
        if not query or not query.strip():
            raise ToolError("Search query cannot be empty.")

        max_results = min(max(1, max_results), 10)

        try:
            results = self._search_duckduckgo(query.strip(), max_results)
        except Exception as e:
            raise ToolError(f"Web search failed: {type(e).__name__}: {e}")

        if not results:
            return f"No results found for: {query}"

        lines = [f"Web search results for: **{query}**\n"]
        for i, result in enumerate(results, 1):
            title = result.get("title", "Untitled")
            url = result.get("url", "")
            snippet = result.get("snippet", "")
            lines.append(f"{i}. **{title}**")
            lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
        """Search DuckDuckGo Lite and parse results."""
        encoded = urllib.parse.urlencode({"q": query})
        url = f"https://lite.duckduckgo.com/lite/?{encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NeuDev/1.0 (AI Coding Agent)",
                "Accept": "text/html",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            raise ToolError(f"Cannot reach search engine: {e}")

        results: list[dict] = []
        # Parse DuckDuckGo Lite result links and snippets
        link_pattern = re.compile(
            r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            re.DOTALL,
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (href, title_html) in enumerate(links):
            if i >= max_results:
                break
            if not href.startswith("http"):
                continue
            title = _html_to_text(title_html).strip() or href
            snippet = _html_to_text(snippets[i]).strip() if i < len(snippets) else ""
            results.append({
                "title": title[:200],
                "url": href[:500],
                "snippet": snippet[:300],
            })

        return results
