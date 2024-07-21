from pathlib import Path
from threading import Event

import aiofiles
from aiohttp import ClientSession

MEGABYTE = 1048576


class Basicdown:
    """Base downloader class."""

    def __init__(self, interrupt: Event):
        self.curr = 0  # Downloaded size in bytes (current size)
        self.completed = False
        self.interrupt = interrupt
        self.downloaded = 0

    async def download(
        self, url: str, path: str, mode: str, session: ClientSession, **kwargs
    ) -> None:
        """Download data in chunks."""
        async with session.get(url, **kwargs) as response:
            async with aiofiles.open(path, mode) as file:
                async for chunk in response.content.iter_chunked(MEGABYTE):
                    await file.write(chunk)
                    self.curr += len(chunk)
                    self.downloaded += len(chunk)
                    if self.interrupt.is_set():
                        break


class Singledown(Basicdown):
    """Class for downloading the whole file in a single segment."""

    async def worker(
        self, url: str, file_path: str, session: ClientSession, **kwargs
    ) -> None:
        await self.download(url, file_path, "wb", session, **kwargs)
        self.completed = True


class Multidown(Basicdown):
    """Class for downloading a specific segment of the file."""

    async def worker(
        self, segment_table: dict, id: int, session: ClientSession, **kwargs
    ) -> None:
        url = segment_table["url"]
        overwrite = segment_table["overwrite"]
        segment_path = Path(segment_table[id]["segment_path"])
        start = segment_table[id]["start"]
        end = segment_table[id]["end"]
        size = segment_table[id]["segment_size"]

        if segment_path.exists():
            downloaded_size = segment_path.stat().st_size
            if overwrite or downloaded_size > size:
                segment_path.unlink()
            else:
                self.curr = downloaded_size

        if kwargs.get("headers") is not None:
            kwargs["headers"] = kwargs["headers"].copy()

        if self.curr < size:
            start = start + self.curr
            kwargs.setdefault("headers", {}).update({"range": f"bytes={start}-{end}"})
            await self.download(url, segment_path, "ab", session, **kwargs)

        if self.curr == size:
            self.completed = True
        else:
            if not self.interrupt.is_set():
                raise Exception(
                    f"Incorrect segment size: expected {size} bytes, received {self.curr} bytes"
                )
