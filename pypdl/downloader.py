import asyncio
import time

import aiofiles
from aiohttp import ClientSession

MEGABYTE = 1048576


class Basicdown:
    """Base downloader class."""

    def __init__(self, session: ClientSession, speed_limit: float) -> None:
        self.session = session
        self.speed_limit = speed_limit * MEGABYTE
        self.curr = 0

    async def download(self, url: str, path: str, mode: str, **kwargs) -> None:
        """Download data in chunks."""
        speedlimit_time = time.time()
        speedlimit_size = 0
        async with self.session.get(url, **kwargs) as response:
            async with aiofiles.open(path, mode) as file:
                async for chunk in response.content.iter_chunked(MEGABYTE):
                    if self.speed_limit > 0:
                        now = time.time()
                        time_passed = now - speedlimit_time
                        if time_passed > 0.1:
                            curr_download = self.curr - speedlimit_size
                            if curr_download / time_passed >= self.speed_limit:
                                await asyncio.sleep(curr_download / self.speed_limit)
                            else:
                                speedlimit_time = now
                                speedlimit_size = self.curr

                    await file.write(chunk)
                    self.curr += len(chunk)


class Singledown(Basicdown):
    """Class for downloading the whole file in a single segment."""

    async def worker(self, url: str, file_path: str, **kwargs) -> None:
        await self.download(url, file_path, "wb", **kwargs)


class Multidown(Basicdown):
    """Class for downloading a specific segment of the file."""

    async def worker(self, segment_table: dict, id: int, **kwargs) -> None:
        url = segment_table["url"]
        overwrite = segment_table["overwrite"]
        segment_path = segment_table[id]["segment_path"]
        size = segment_table[id]["segment_size"]

        if await aiofiles.os.path.exists(segment_path):
            downloaded_size = await aiofiles.os.path.getsize(segment_path)
            if overwrite or downloaded_size > size.value:
                await aiofiles.os.remove(segment_path)
            else:
                self.curr = downloaded_size

        if kwargs.get("headers") is not None:
            kwargs["headers"] = kwargs["headers"].copy()

        if self.curr < size.value:
            start = size.start + self.curr
            kwargs.setdefault("headers", {}).update(
                {"range": f"bytes={start}-{size.end}"}
            )
            await self.download(url, segment_path, "ab", **kwargs)

        if self.curr != size.value:
            raise Exception(
                f"Incorrect segment size: expected {size} bytes, received {self.curr} bytes"
            )
