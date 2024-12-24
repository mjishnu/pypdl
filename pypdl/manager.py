import asyncio
import time
from collections import deque
from logging import Logger
from threading import Event
from typing import Callable, Union

import aiohttp

from producer import Producer
from consumer import Consumer
from utils import (
    AutoShutdownFuture,
    ScreenCleaner,
    cursor_up,
    default_logger,
    seconds_to_hms,
    to_mb,
    LoggingExecutor,
    TEventLoop,
    EFuture,
    Task,
)


class Pypdl:
    def __init__(
        self,
        max_concurrent: int = 1,
        allow_reuse: bool = False,
        logger: Logger = default_logger("Pypdl"),
        **kwargs,
    ):
        self._interrupt = Event()
        self._kwargs = {
            "timeout": aiohttp.ClientTimeout(sock_read=60),
            "raise_for_status": True,
        }
        self._kwargs.update(kwargs)
        self._pool = LoggingExecutor(logger, max_workers=2)
        self._recent_queue = deque(maxlen=12)
        self._loop = TEventLoop(self._pool)
        self._producer = None
        self._consumers = []
        self._producer_queue = None
        self._consumer_queue = None
        self._max_concurrent = max_concurrent
        self._allow_reuse = allow_reuse
        self._logger = logger
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
        self.completed = False
        self.success = []
        self.failed = []

    @property
    def is_idle(self) -> bool:
        return not self._loop.has_running_tasks()

    @property
    def logger(self):
        """Return logger if logger is in accessible state, otherwise returns None"""
        if self.is_idle:
            return self._logger
        return None

    def set_max_concurrent(self, max_concurrent) -> bool:
        """Returns True if max_concurrent was successfully set, otherwise returns False"""
        if self.is_idle:
            self._max_concurrent = max_concurrent
            return True
        return False

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

    def start(
        self,
        url: Union[Callable, str] = None,
        file_path: str = None,
        tasks: list = None,
        overwrite: bool = True,
        block: bool = True,
        retries: int = 0,
        multisegment: bool = True,
        segments: int = 5,
        etag_validation: bool = True,
        display: bool = True,
        clear_terminal: bool = True,
    ) -> Union[EFuture, AutoShutdownFuture]:
        if isinstance(url, str) or callable(url):
            tasks = [(url, file_path)]

        if tasks is None:
            raise TypeError(
                "Either 'url' (str or callable) or 'tasks' (list) must be provided"
            )
        self._reset()

        task_dict = {}
        self.total_task = 0
        for i, task in enumerate(tasks):
            url, file_path = task + (None,) * (2 - len(task))
            task_dict[i] = Task(url, file_path, multisegment, 0, retries + 1)
            self.total_task += 1

        coro = self._download_tasks(
            task_dict, segments, overwrite, etag_validation, display, clear_terminal
        )

        self._future = EFuture(
            asyncio.run_coroutine_threadsafe(coro, self._loop.get()), self._loop
        )

        if not self._allow_reuse:
            future = AutoShutdownFuture(self._future, self._loop, self._pool)
        else:
            future = self._future

        if block:
            result = future.result()
            return result

        return future

    async def _download_tasks(
        self,
        tasks,
        segments,
        overwrite,
        etag_validation,
        display,
        clear_terminal,
    ):
        self._logger.debug("Starting download tasks")
        start_time = time.time()
        coroutines = []
        self._producer_queue = asyncio.Queue(self.total_task)
        self._consumer_queue = asyncio.Queue(self.total_task)

        async with aiohttp.ClientSession(**self._kwargs) as session:
            self._producer = Producer(session, self._logger, tasks, **self._kwargs)
            producer_task = asyncio.create_task(
                self._producer.enqueue_tasks(self._producer_queue, self._consumer_queue)
            )
            coroutines.append(producer_task)
            await self._producer_queue.put([key for key in tasks.keys()])

            for _id in range(self._max_concurrent):
                consumer = Consumer(session, self._logger, _id, **self._kwargs)
                consumer_task = asyncio.create_task(
                    consumer.process_tasks(
                        self._consumer_queue,
                        self._producer_queue,
                        segments,
                        overwrite,
                        etag_validation,
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
            print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")

        return self.success

    def stop(self) -> None:
        self._logger.debug("stop called")
        if self.is_idle or self.completed:
            self._logger.debug("Task not running")
            return None
        self._interrupt.set()
        self._future._stop()

    def shutdown(self) -> None:
        """Shutdown the download manager."""
        self.stop()
        self._loop.stop()
        self._pool.shutdown()
        self._logger.debug("Shutdown download manager")

    def _reset(self) -> None:
        self._interrupt.clear()
        self._recent_queue.clear()
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
        self.completed = False
        self.success.clear()
        self.failed.clear()

    def _progress_monitor(self, display, clear_terminal):
        self._logger.debug("Starting progress monitor")
        interval = 0.5
        with ScreenCleaner(display, clear_terminal):
            while not self.completed and not self._interrupt.is_set():
                self._calc_values(interval)
                if display:
                    self._display()
                time.sleep(interval)
        self._logger.debug("exiting progress monitor")

    async def _completed(self):
        self._logger.debug("All downloads completed")
        await self._producer_queue.put(None)
        for i in range(self._max_concurrent):
            await self._consumer_queue.put(None)
        self.completed = True

    def _calc_values(self, interval):
        self.size = self._producer.size
        self.current_size = sum(consumer.size for consumer in self._consumers)

        self.completed_task = sum(
            len(consumer.success) for consumer in self._consumers
        ) + len(self._producer.failed)

        self.task_progress = int((self.completed_task / self.total_task) * 100)

        # Speed calculation
        self._recent_queue.append(self.current_size)
        if len(self._recent_queue) >= 2:
            bytes_diff = self._recent_queue[-1] - self._recent_queue[-2]
            self.speed = to_mb(bytes_diff) / interval
        else:
            self.speed = 0

        if self.size:
            self.progress = int((self.current_size / self.size) * 100)
            self.remaining_size = to_mb(self.size - self.current_size)

            if self.speed:
                self.eta = seconds_to_hms(self.remaining_size / self.speed)
            else:
                self.eta = "99:59:59"

        if self.completed_task is self.total_task:
            future = asyncio.run_coroutine_threadsafe(
                self._completed(), self._loop.get()
            )
            future.result()

    def _display(self):
        cursor_up()
        if self.size:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"

            if self.total_task > 1:
                info1 = f"Total Downloads: {self.completed_task}/{self.total_task}, "
            else:
                info1 = ""

            info2 = f"Size: {to_mb(self.size):.2f} MB, Speed: {self.speed:.2f} MB/s, ETA: {self.eta} "
            print(progress_bar + info1 + info2)
        else:
            if self.total_task > 1:
                download_stats = f"[{'█' * self.task_progress}{'·' * (100 - self.task_progress)}] {self.task_progress}% \n"
            else:
                download_stats = "Downloading... \n"

            info = f"Total Downloads: {self.completed_task}/{self.total_task}, Downloaded Size: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "

            print(download_stats + info)
