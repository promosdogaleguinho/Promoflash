import gzip
import io
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.clients.awin import AwinError, AwinHttpError, AwinTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)


def sanitize_feed_url_for_log(url: str) -> str:
    """Remove query/fragment e segmentos sensíveis do path (ex.: apikey)."""
    parsed = urlparse(url)
    host = parsed.netloc or "unknown-host"
    parts = [segment for segment in (parsed.path or "/").split("/") if segment]
    sanitized_parts: list[str] = []
    skip_next = False
    for index, part in enumerate(parts):
        if skip_next:
            sanitized_parts.append("***")
            skip_next = False
            continue
        lowered = part.lower()
        if lowered in {"apikey", "api_key", "token", "key", "secret"}:
            sanitized_parts.append(part)
            skip_next = True
            continue
        sanitized_parts.append(part)
    path = "/" + "/".join(sanitized_parts) if sanitized_parts else "/"
    return f"{parsed.scheme or 'https'}://{host}{path}"


class AwinProductFeedClient:
    def __init__(
        self,
        feed_url: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._feed_url = feed_url.strip()
        self._timeout = timeout

    def download(self) -> bytes:
        logger.info(
            "Awin product feed download started url=%s",
            sanitize_feed_url_for_log(self._feed_url),
        )
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(
                    timeout=self._timeout,
                    follow_redirects=True,
                ) as client:
                    response = client.get(self._feed_url)
            except httpx.TimeoutException as exc:
                last_error = AwinTimeoutError(str(exc))
                self._sleep(attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = AwinHttpError(str(exc))
                self._sleep(attempt)
                continue

            if response.status_code >= 500:
                last_error = AwinHttpError(
                    f"Product feed HTTP {response.status_code}"
                )
                self._sleep(attempt)
                continue

            if response.status_code >= 400:
                raise AwinHttpError(
                    f"Product feed HTTP {response.status_code}"
                )

            content = response.content
            logger.info(
                "Awin product feed downloaded bytes=%s url=%s",
                len(content),
                sanitize_feed_url_for_log(self._feed_url),
            )
            return content

        assert last_error is not None
        raise last_error

    @staticmethod
    def _sleep(attempt: int) -> None:
        if attempt >= len(RETRY_BACKOFF_SECONDS):
            return
        import time

        time.sleep(RETRY_BACKOFF_SECONDS[attempt])


def decompress_feed_content(content: bytes) -> bytes:
    if content.startswith(b"\x1f\x8b"):
        return gzip.decompress(content)
    try:
        return gzip.decompress(content)
    except OSError:
        return content


def open_feed_text_stream(content: bytes) -> io.TextIOBase:
    raw = decompress_feed_content(content)
    return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
