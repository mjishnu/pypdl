import asyncio

from aiofiles import os

from .downloader import Multidown, Singledown
from .utils import FileValidator, combine_files, create_segment_table


class Consumer:
    def __init__(self, session, logger, _id):
        self._workers = []
        self._downloaded_size = 0
        self._size = 0
        self._show_size = True
        self.id = _id

        self.logger = logger
        self.session = session
        self.success = []

    @property
    def size(self):
        if self._show_size:
            self._size = (
                sum(worker.curr for worker in self._workers) + self._downloaded_size
            )
        return self._size

    async def process_tasks(self, in_queue, out_queue):
        self.logger.debug("Consumer %s started", self.id)
        while True:
            task = await in_queue.get()
            self.logger.debug("Consumer %s received task", self.id)
            if task is None:
                break
            try:
                await self._download(task)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.debug("Task %s failed", self.id)
                self.logger.exception(e)
                await out_queue.put([task[0]])

            self._workers.clear()
            self._show_size = True

            self.logger.debug("Consumer %s completed task", self.id)
        self.logger.debug("Consumer %s exited", self.id)
        return self.success

    async def _download(
        self,
        task,
    ):
        _id, task = task
        (
            url,
            file_path,
            multisegment,
            etag,
            size,
            segments,
            overwrite,
            speed_limit,
            etag_validation,
            kwargs,
        ) = task

        self.logger.debug("Download started %s", self.id)
        if not overwrite and await os.path.exists(file_path):
            self.logger.debug("File already exists, download completed")
            self.success.append(FileValidator(file_path))
            self._downloaded_size += await os.path.getsize(file_path)
            return

        if multisegment:
            segment_table = await create_segment_table(
                url, file_path, segments, size, etag, etag_validation
            )
            await self._multi_segment(segment_table, file_path, speed_limit, **kwargs)
        else:
            await self._single_segment(url, file_path, speed_limit, **kwargs)

        self.success.append((url, FileValidator(file_path)))
        self.logger.debug("Download exited %s", self.id)

    async def _multi_segment(self, segment_table, file_path, speed_limit, **kwargs):
        tasks = set()
        segments = segment_table["segments"]
        speed_limit = speed_limit / segments
        self.logger.debug("Multi-Segment download started %s", self.id)
        for segment in range(segments):
            md = Multidown(self.session, speed_limit)
            self._workers.append(md)
            tasks.add(asyncio.create_task(md.worker(segment_table, segment, **kwargs)))

        await asyncio.gather(*tasks)
        await combine_files(file_path, segments)
        self.logger.debug("Downloaded all segments %s", self.id)
        self._show_size = False
        self._downloaded_size += await os.path.getsize(file_path)

    async def _single_segment(self, url, file_path, speed_limit, **kwargs):
        self.logger.debug("Single-Segment download started %s", self.id)
        sd = Singledown(self.session, speed_limit)
        self._workers.append(sd)
        await sd.worker(url, file_path, **kwargs)
        self.logger.debug("Downloaded single segment %s", self.id)
        self._show_size = False
        self._downloaded_size += await os.path.getsize(file_path)
