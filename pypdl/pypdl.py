import asyncio
import time
from collections import deque
from logging import Logger
from threading import Event
from typing import Callable, Union

import aiohttp

from . import utils
from .consumer import Consumer
from .producer import Producer


class Pypdl:
    def __init__(
        self,
        allow_reuse: bool = False,
        logger: Logger = utils.default_logger("Pypdl"),
        max_concurrent: int = 1,
    ):
        self._interrupt = Event()
        self._pool = utils.LoggingExecutor(logger, max_workers=1)
        self._loop = utils.TEventLoop()
        self._producer = None
        self._consumers = []
        self._producer_queue = None
        self._consumer_queue = None
        self._allow_reuse = allow_reuse
        self._logger = logger
        self._max_concurrent = max_concurrent
        self._future = None

        self.size = None
        self.current_size = None
        self.remaining_size = None
        self.progress = None
        self.speed = None
        self.time_spent = None
        self.eta = None
        self.total_task = None
        self.completed_task = None
        self.task_progress = None
        self.completed = False
        self.success = []
        self.failed = []

    @property
    def is_idle(self) -> bool:
        """Return True if download manager is idle, otherwise returns False"""
        return not self._loop.has_running_tasks()

    @property
    def logger(self) -> Union[Logger, None]:
        """Return logger if logger is in accessible state, otherwise returns None"""
        if self.is_idle:
            return self._logger
        return None

    def set_allow_reuse(self, allow_reuse) -> bool:
        """Returns True if allow_reuse was successfully set, otherwise returns False"""
        if self.is_idle:
            self._allow_reuse = allow_reuse
            return True
        return False

    def set_logger(self, logger) -> bool:
        """Returns True if logger was successfully set, otherwise returns False"""
        if self.is_idle:
            self._logger = logger
            return True
        return False

    def set_max_concurrent(self, max_concurrent) -> bool:
        """Returns True if max_concurrent was successfully set, otherwise returns False"""
        if self.is_idle:
            self._max_concurrent = max_concurrent
            return True
        return False

    def start(
        self,
        url: Union[Callable, str] = None,
        file_path: str = None,
        tasks: list = None,
        multisegment: bool = True,
        segments: int = 5,
        retries: int = 0,
        overwrite: bool = True,
        speed_limit: float = 0,
        etag_validation: bool = True,
        block: bool = True,
        display: bool = True,
        clear_terminal: bool = True,
        **kwargs,
    ) -> Union[utils.EFuture, utils.AutoShutdownFuture, list]:
        """
        Start the download process.

        :param url: URL (str or callable) if `tasks` not provided.
        :param file_path: Local file path for the single download.
        :param tasks: List of tasks (dict), each with its own URL and other supported keys.
        :param multisegment: Whether to download in multiple segments.
        :param segments: Number of segments if multi-segmented.
        :param retries: Number of retries for failed downloads.
        :param overwrite: Overwrite existing files if True.
        :param speed_limit: Limit download speed in MB/s if > 0.
        :param etag_validation: Validate server-provided ETag if True.
        :param block: If True, block until downloads finish.
        :param display: If True, display progress.
        :param clear_terminal: If True, clear terminal before displaying progress bar.
        :param kwargs: Addtional keyword arguments for aiohttp.
        :return: A future-like object if non-blocking, or a result list if blocking.
        :raises RuntimeError: If downloads are already in progress.
        :raises TypeError: If invalid parameters or task definitions are provided.
        """
        if not self.is_idle:
            tasks = asyncio.all_tasks(self._loop.loop)
            raise RuntimeError(f"Pypdl already running {tasks}")

        if tasks and (url or file_path):
            raise TypeError(
                "Either provide 'tasks' or a 'url' (with optional 'file_path'), but not both."
            )

        if tasks is None:
            if not (isinstance(url, str) or callable(url)):
                raise TypeError(
                    "Expected a 'url' (str or callable) when 'tasks' not provided."
                )
            tasks = [{"url": url, "file_path": file_path}]

        self._reset()

        task_dict = {}
        self.total_task = 0
        _kwargs = {
            "timeout": aiohttp.ClientTimeout(sock_read=60),
            "raise_for_status": True,
        }
        _kwargs.update(kwargs)
        for i, task_kwargs in enumerate(tasks):
            task = utils.Task(
                multisegment,
                segments,
                retries,
                overwrite,
                speed_limit,
                etag_validation,
                **_kwargs,
            )
            task.set(**task_kwargs)
            task_dict[i] = task
            self.total_task += 1

        coro = self._download_tasks(task_dict, display, clear_terminal)

        self._future = utils.EFuture(
            asyncio.run_coroutine_threadsafe(coro, self._loop.get()), self._loop
        )

        while self.is_idle:
            self.logger.debug("waiting for download to start")
            time.sleep(0.1)

        if not self._allow_reuse:
            future = utils.AutoShutdownFuture(self._future, self._loop, self._pool)
        else:
            future = self._future

        if block:
            result = future.result()
            return result

        return future

    async def _download_tasks(self, tasks_dict, display, clear_terminal):
        self._logger.debug("Starting download tasks")
        start_time = time.time()
        coroutines = []
        self._producer_queue = asyncio.Queue(self.total_task)
        self._consumer_queue = asyncio.Queue(self.total_task)

        async with aiohttp.ClientSession() as session:
            self._producer = Producer(session, self._logger, tasks_dict)
            producer_task = asyncio.create_task(
                self._producer.enqueue_tasks(self._producer_queue, self._consumer_queue)
            )
            coroutines.append(producer_task)
            await self._producer_queue.put(list(tasks_dict))

            for _id in range(self._max_concurrent):
                consumer = Consumer(session, self._logger, _id)
                consumer_task = asyncio.create_task(
                    consumer.process_tasks(
                        self._consumer_queue,
                        self._producer_queue,
                    )
                )
                coroutines.append(consumer_task)
                self._consumers.append(consumer)

            self._logger.debug("Starting producer and consumer tasks")
            self._pool.submit(self._progress_monitor, display, clear_terminal)

            res = await asyncio.gather(*coroutines)
            self.failed.extend(res.pop(0))
            for success in res:
                self.success.extend(success)
            await asyncio.sleep(0.5)

        self.time_spent = time.time() - start_time
        if display:
            print(f"Time elapsed: {utils.seconds_to_hms(self.time_spent)}")

        return self.success

    def stop(self) -> None:
        """Stop the download manager."""
        self._logger.debug("stop called")
        if self.is_idle or self.completed:
            self._logger.debug("Task not running, nothing to stop")
            return None
        self._future._stop()
        self._interrupt.set()

    def shutdown(self) -> None:
        """Shutdown the download manager."""
        self.stop()
        self._loop.stop()
        self._pool.shutdown()
        self._logger.debug("Shutdown download manager")

    def _reset(self):
        self._interrupt.clear()
        self._consumers.clear()
        self._producer = None

        self.size = None
        self.current_size = None
        self.remaining_size = None
        self.progress = None
        self.speed = None
        self.time_spent = None
        self.eta = None
        self.total_task = None
        self.completed_task = None
        self.task_progress = None
        self.completed = False
        self.success.clear()
        self.failed.clear()

    def _progress_monitor(self, display, clear_terminal):
        self._logger.debug("Starting progress monitor")
        interval = 0.5
        recent_queue = deque(maxlen=12)
        with utils.ScreenCleaner(display, clear_terminal):
            while not self.completed and not self._interrupt.is_set():
                self._calc_values(recent_queue, interval)
                if display:
                    self._display()
                time.sleep(interval)
        self._logger.debug("exiting progress monitor")

    async def _completed(self):
        self._logger.debug("All downloads completed")
        await self._producer_queue.put(None)
        for _ in range(self._max_concurrent):
            await self._consumer_queue.put(None)
        self.completed = True

    def _calc_values(self, recent_queue, interval):
        self.size = self._producer.size
        self.current_size = sum(consumer.size for consumer in self._consumers)

        self.completed_task = sum(
            len(consumer.success) for consumer in self._consumers
        ) + len(self._producer.failed)

        self.task_progress = int((self.completed_task / self.total_task) * 100)

        # Speed calculation
        recent_queue.append(self.current_size)
        non_zero_list = [utils.to_mb(value) for value in recent_queue if value]
        if len(non_zero_list) < 1:
            self.speed = 0
        elif len(non_zero_list) == 1:
            self.speed = non_zero_list[0] / interval
        else:
            diff = [b - a for a, b in zip(non_zero_list, non_zero_list[1:])]
            self.speed = (sum(diff) / len(diff)) / interval

        if self.size:
            self.progress = int((self.current_size / self.size) * 100)
            self.remaining_size = utils.to_mb(self.size - self.current_size)

            if self.speed:
                self.eta = self.remaining_size / self.speed
            else:
                self.eta = -1

        if self.completed_task is self.total_task:
            future = asyncio.run_coroutine_threadsafe(
                self._completed(), self._loop.get()
            )
            future.result()

    def _display(self):
        utils.cursor_up()
        whitespace = " "
        if self.size:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"

            if self.total_task > 1:
                info1 = f"Total Downloads: {self.completed_task}/{self.total_task}, "
            else:
                info1 = ""

            info2 = f"Size: {utils.to_mb(self.size):.2f} MB, Speed: {self.speed:.2f} MB/s, ETA: { utils.seconds_to_hms(self.eta)}"
            print(progress_bar + info1 + info2 + whitespace * 35)
        else:
            if self.total_task > 1:
                download_stats = f"[{'█' * self.task_progress}{'·' * (100 - self.task_progress)}] {self.task_progress}% \n"
            else:
                download_stats = f"Downloading... {whitespace * 95}\n"

            info = f"Total Downloads: {self.completed_task}/{self.total_task}, Downloaded Size: {utils.to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s"

            print(download_stats + info + whitespace * 35)
