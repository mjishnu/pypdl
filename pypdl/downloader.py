import aiofiles
from aiohttp import ClientSession

MEGABYTE = 1048576


class Basicdown:
    """Base downloader class."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.curr = 0
        self.completed = False

    async def download(self, url: str, path: str, mode: str, **kwargs) -> None:
        """Download data in chunks."""
        async with self.session.get(url, **kwargs) as response:
            async with aiofiles.open(path, mode) as file:
                async for chunk in response.content.iter_chunked(MEGABYTE):
                    await file.write(chunk)
                    self.curr += len(chunk)


class Singledown(Basicdown):
    """Class for downloading the whole file in a single segment."""

    async def worker(self, url: str, file_path: str, **kwargs) -> None:
        await self.download(url, file_path, "wb", **kwargs)
        self.completed = True


class Multidown(Basicdown):
    """Class for downloading a specific segment of the file."""

    async def worker(self, segment_table: dict, id: int, **kwargs) -> None:
        url = segment_table["url"]
        overwrite = segment_table["overwrite"]
        segment_path = segment_table[id]["segment_path"]
        start = segment_table[id]["start"]
        end = segment_table[id]["end"]
        size = segment_table[id]["segment_size"]

        if await aiofiles.os.path.exists(segment_path):
            downloaded_size = await aiofiles.os.path.getsize(segment_path)
            if overwrite or downloaded_size > size:
                await aiofiles.os.remove(segment_path)
            else:
                self.curr = downloaded_size

        if kwargs.get("headers") is not None:
            kwargs["headers"] = kwargs["headers"].copy()

        if self.curr < size:
            start = start + self.curr
            kwargs.setdefault("headers", {}).update({"range": f"bytes={start}-{end}"})
            await self.download(url, segment_path, "ab", **kwargs)

        if self.curr == size:
            self.completed = True
        else:
            raise Exception(
                f"Incorrect segment size: expected {size} bytes, received {self.curr} bytes"
            )
