import hashlib
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


@dataclass(frozen=True)
class StoredImage:
    source_url: str
    local_path: Path
    sha256: str
    content_type: str
    size_bytes: int


class ImageFetcher:
    def __init__(self, root: Path, user_agent: str, timeout: float = 60.0) -> None:
        self.root = root
        self.user_agent = user_agent
        self.timeout = timeout

    async def fetch(self, url: str, folder: str) -> StoredImage:
        target_dir = self.root / folder
        existing = self._find_existing(target_dir, url)
        if existing is not None:
            return existing
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": self.user_agent})
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
