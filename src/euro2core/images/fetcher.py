import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

import httpx

EXTENSION_FOR_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
log = logging.getLogger(__name__)


class HostBlocked(Exception):
    """Raised without a request once a host has refused too many downloads in a row."""


@dataclass(frozen=True)
class StoredImage:
    source_url: str
    local_path: Path
    sha256: str
    content_type: str
    size_bytes: int


class ImageFetcher:
    # Consecutive 403s from one host before the fetcher stops asking it for the rest of
    # its lifetime (one sync run): bot-protected CDNs answer every request the same way.
    BLOCK_AFTER = 3

    def __init__(self, root: Path, user_agent: str, timeout: float = 60.0) -> None:
        self.root = root
        self.user_agent = user_agent
        self.timeout = timeout
        self.blocked_hosts: set[str] = set()
        self._forbidden_streak: dict[str, int] = {}

    async def fetch(self, url: str, folder: str) -> StoredImage:
        target_dir = self.root / folder
        existing = self._find_existing(target_dir, url)
        if existing is not None:
            return existing
        host = urlparse(url).hostname or ""
        if host in self.blocked_hosts:
            raise HostBlocked(host)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": self.user_agent})
        self._track_forbidden(host, response.status_code)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type not in EXTENSION_FOR_TYPE:
            raise ValueError(f"{url}: not an image ({content_type or 'no content type'})")
        data = response.content
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / self.filename_for(url, content_type)
        path.write_bytes(data)
        return StoredImage(
            source_url=url,
            local_path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
            size_bytes=len(data),
        )

    def _track_forbidden(self, host: str, status: int) -> None:
        if status != 403:
            self._forbidden_streak.pop(host, None)
            return
        streak = self._forbidden_streak.get(host, 0) + 1
        self._forbidden_streak[host] = streak
        if streak >= self.BLOCK_AFTER:
            self.blocked_hosts.add(host)
            log.warning(
                "%s refused %d downloads in a row; keeping its images as references this run",
                host,
                streak,
            )

    def filename_for(self, url: str, content_type: str) -> str:
        name = unquote(PurePosixPath(urlparse(url).path).name) or "image"
        name = _UNSAFE.sub("_", name)
        if not PurePosixPath(name).suffix:
            name += EXTENSION_FOR_TYPE[content_type]
        return name

    def _find_existing(self, target_dir: Path, url: str) -> StoredImage | None:
        for content_type in EXTENSION_FOR_TYPE:
            candidate = target_dir / self.filename_for(url, content_type)
            if candidate.exists():
                data = candidate.read_bytes()
                return StoredImage(
                    source_url=url,
                    local_path=candidate,
                    sha256=hashlib.sha256(data).hexdigest(),
                    content_type=content_type,
                    size_bytes=len(data),
                )
        return None
