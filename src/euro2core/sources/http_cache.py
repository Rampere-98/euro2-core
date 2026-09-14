import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CachedResponse:
    url: str
    body: str
    etag: str | None
    last_modified: str | None
    fetched_at: datetime


class HttpCache:
    """Disk cache of raw HTTP bodies keyed by URL, with validators for conditional requests."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, url: str) -> CachedResponse | None:
        body_path, meta_path = self._paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text("utf-8"))
        return CachedResponse(
            url=url,
            body=body_path.read_text("utf-8"),
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
            fetched_at=datetime.fromisoformat(meta["fetched_at"]),
        )

    def put(
        self, url: str, body: str, *, etag: str | None = None, last_modified: str | None = None
    ) -> CachedResponse:
        body_path, meta_path = self._paths(url)
        self.root.mkdir(parents=True, exist_ok=True)
        fetched_at = datetime.now(UTC)
        body_path.write_text(body, "utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "etag": etag,
                    "last_modified": last_modified,
                    "fetched_at": fetched_at.isoformat(),
                }
            ),
            "utf-8",
        )
        return CachedResponse(url, body, etag, last_modified, fetched_at)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode()).hexdigest()
        return self.root / f"{key}.body", self.root / f"{key}.meta.json"
