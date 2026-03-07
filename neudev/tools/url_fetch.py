"""URL content fetcher tool for NeuDev — read web pages as text."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from neudev.tools.base import BaseTool, ToolError


class _ContentExtractor(HTMLParser):
    """Extract readable text from HTML, skipping scripts/styles."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self._skip_tags = {"script", "style", "noscript", "nav", "footer", "header"}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse excessive whitespace
        lines = [line.strip() for line in raw.splitlines()]
        collapsed: list[str] = []
        prev_blank = False
        for line in lines:
            if not line:
                if not prev_blank:
                    collapsed.append("")
                prev_blank = True
            else:
                collapsed.append(line)
                prev_blank = False
        return "\n".join(collapsed).strip()


class UrlFetchTool(BaseTool):
    """Fetch and extract text content from a URL."""

    @property
    def name(self) -> str:
        return "url_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch text content from a URL. Converts HTML to readable text. "
            "Useful for reading documentation, READMEs, API docs, and error pages. "
            "Output is truncated to 5000 characters."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 5000).",
                },
            },
            "required": ["url"],
        }

    @property
    def requires_permission(self) -> bool:
        return True

    def permission_message(self, args: dict) -> str:
        url = args.get("url", "")
        return f"Fetch content from URL: {url}"

    def execute(self, url: str, max_chars: int = 5000, **kwargs) -> str:
        if not url or not url.strip():
            raise ToolError("URL cannot be empty.")

        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        max_chars = min(max(500, max_chars), 15000)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NeuDev/1.0 (AI Coding Agent)",
                "Accept": "text/html, text/plain, application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(max_chars * 3)  # Read more for HTML overhead
                encoding = "utf-8"
                if "charset=" in content_type:
                    charset_match = re.search(r"charset=([\w-]+)", content_type)
                    if charset_match:
                        encoding = charset_match.group(1)
                text = raw.decode(encoding, errors="replace")
        except urllib.error.HTTPError as e:
            raise ToolError(f"HTTP {e.code} error fetching {url}: {e.reason}")
        except urllib.error.URLError as e:
            raise ToolError(f"Cannot reach {url}: {e.reason}")
        except Exception as e:
            raise ToolError(f"Failed to fetch {url}: {type(e).__name__}: {e}")

        # Extract readable text
        if "text/html" in content_type or text.strip().startswith("<!"):
            extractor = _ContentExtractor()
            try:
                extractor.feed(text)
                text = extractor.get_text()
            except Exception:
                pass  # Fall back to raw text

        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n\n... (content truncated)"

        return f"Content from: {url}\n\n{text}"
