import asyncio
from .utils import get_filepath, Size, get_range


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
                            kwargs,
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
                        self.logger.exception(e)
                        continue

                    if size.value == 0:
                        self.logger.debug("Size is Unavailable, setting size to None")
                        self.size_avail = False

                    total_size -= task.size.value
                    total_size += size.value
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
                                kwargs,
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

        user_headers = kwargs.get("headers", {})
        range_header = None

        if user_headers:
            _user_headers = user_headers.copy()
            for key, value in user_headers.items():
                if key.lower() == "range":
                    range_header = value
                    self.logger.debug("Range header found %s", range_header)
                    del _user_headers[key]
            kwargs["headers"] = _user_headers

        header = await self._fetch_header(url, **kwargs)
        file_path = await get_filepath(url, header, file_path)
        if file_size := int(header.get("content-length", 0)):
            self.logger.debug("File size acquired from header")

        if range_header:
            start, end = get_range(range_header, file_size)
        else:
            start = 0
            end = file_size - 1

        size = Size(start, end)
        etag = header.get("etag", "")
        if etag != "":
            self.logger.debug("ETag acquired from header")
            etag = etag.strip('"')

        if size.value < 1 or not header.get("accept-ranges"):
            self.logger.debug("Single segment mode, accept-ranges or size not found")
            kwargs["headers"] = user_headers
            multisegment = False

        return url, file_path, multisegment, etag, size, kwargs

    async def _fetch_header(self, url, **kwargs):
        try:
            async with self.session.head(url, **kwargs) as response:
                if response.status < 400:
                    self.logger.debug("Header acquired from HEAD request")
                    return response.headers
        except Exception:
            pass

        async with self.session.get(url, **kwargs) as response:
            if response.status < 400:
                self.logger.debug("Header acquired from GET request")
                return response.headers
