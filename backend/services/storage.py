import os

import aiofiles

from backend.config import get_settings


class LocalStorage:
    """Manages media files stored under MEDIA_DIR."""

    def __init__(self, media_dir: str | None = None):
        self.media_dir = media_dir or get_settings().media_dir
        os.makedirs(self.media_dir, exist_ok=True)

    def get_path(self, relative_path: str) -> str:
        """Return the absolute path for a relative media path."""
        return os.path.join(self.media_dir, relative_path)

    async def save(self, lecture_id: str, kind: str, filename: str, data: bytes) -> str:
        """Save bytes to MEDIA_DIR/<lecture_id>/<kind>/<filename>. Returns relative path."""
        dir_path = os.path.join(self.media_dir, lecture_id, kind)
        os.makedirs(dir_path, exist_ok=True)
        relative_path = os.path.join(lecture_id, kind, filename)
        abs_path = os.path.join(self.media_dir, relative_path)
        async with aiofiles.open(abs_path, "wb") as f:
            await f.write(data)
        return relative_path

    async def load(self, relative_path: str) -> bytes:
        """Load file bytes by relative path."""
        abs_path = self.get_path(relative_path)
        async with aiofiles.open(abs_path, "rb") as f:
            return await f.read()

    def delete(self, relative_path: str) -> None:
        """Delete a file by relative path."""
        abs_path = self.get_path(relative_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)

    def exists(self, relative_path: str) -> bool:
        return os.path.exists(self.get_path(relative_path))
