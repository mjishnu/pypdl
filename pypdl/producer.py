import asyncio

from utils import get_filepath


class Producer:
    def __init__(self, session, logger, tasks):
        self._size = None

        self.logger = logger
        self.session = session
        self.tasks = tasks
        self.failed = []
        self.size_avail = True

    @property
    def size(self):
        if self.size_avail and self._size is not None:
            return self._size

    async def enqueue_tasks(self, in_queue: asyncio.queues, out_queue):
        self.logger.debug("Producer started")
        while True:
            batch = await in_queue.get()

            if batch is None:
                break

            total_size = 0

            for _id in batch:
                task = self.tasks[_id]
                if task.tries > 0:
                    task.tries -= 1
                    try:
                        (
                            url,
                            file_path,
                            multisegment,
                            etag,
                            size,
                        ) = await self._fetch_task_info(
                            task.url, task.file_path, task.multisegment, **task.kwargs
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        await asyncio.sleep(3)
                        await in_queue.put([_id])
                        self.logger.debug(
                            f"Failed to get header for {task}, skipping task"
                        )
                        self.logger.error(e)
                        continue

                    if size == 0:
                        self.logger.debug("Size is Unavailable, setting size to None")
                        self.size_avail = False

                    total_size -= task.size
                    total_size += size
                    task.size = size
                    await out_queue.put(
                        (
                            _id,
                            (
                                url,
                                file_path,
                                multisegment,
                                etag,
                                size,
                                task.segments,
                                task.overwrite,
                                task.speed_limit,
                                task.etag_validation,
                                task.kwargs,
                            ),
                        )
                    )
                else:
                    self.failed.append(task.url)

            if self._size is None:
                self._size = total_size
            else:
                self._size += total_size
        self.logger.debug("Producer exited")
        return self.failed

    async def _fetch_task_info(self, url, file_path, multisegment, **kwargs):
        if callable(url):
            url = url()
        kwargs.update({"raise_for_status": False})
        header = await self._fetch_header(url, **kwargs)
        file_path = await get_filepath(url, header, file_path)
        if size := int(header.get("content-length", 0)):
            self.logger.debug("Size acquired from header")

        etag = header.get("etag", "")
        if etag != "":
            self.logger.debug("ETag acquired from header")
            etag = etag.strip('"')

        if not size or not header.get("accept-ranges"):
            self.logger.debug("Single segment mode, accept-ranges or size not found")
            multisegment = False

        return url, file_path, multisegment, etag, size

    async def _fetch_header(self, url, **kwargs):
        async with self.session.head(url, **kwargs) as response:
            if response.status < 400:
                self.logger.debug("Header acquired from HEAD request")
                return response.headers
        async with self.session.get(url, **kwargs) as response:
            if response.status < 400:
                self.logger.debug("Header acquired from GET request")
                return response.headers
        raise Exception(
            f"Failed to get header (Status: {response.status}, Reason: {response.reason})"
        )
