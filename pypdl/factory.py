import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Union

from .manager import DownloadManager as Pypdl
from .utls import (
    AutoShutdownFuture,
    ScreenCleaner,
    cursor_up,
    seconds_to_hms,
    to_mb,
)


class Factory:
    def __init__(self, instances: int = 2, allow_reuse=False, **kwargs):
        self._instances = [Pypdl(True, **kwargs) for _ in range(instances)]
        self._allow_reuse = allow_reuse
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._stop = False
        self._prog = True
        self._completed_size = 0
        self._completed_prog = 0
        self._lock = threading.Event()
        self._stop_lock = threading.Lock()
        self._running = []

        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.total = 0
        self.completed = []
        self.failed = []
        self.remaining = []

    def start(
        self, tasks: list, display: bool = True, block: bool = True
    ) -> Union[AutoShutdownFuture, Future, list]:
        """
        Start the download process.

        Parameters:
            tasks (list): A list of tasks to be downloaded.
                Each task is a tuple where the 1st element is the URL and the 2nd element is an optional dict with kwargs for pypdl start method.
            display (bool, Optional): Whether to display download progress and other messages. Default is True.
            block (bool, Optional): Whether to block the function until all downloads are complete. Default is True.

        Returns:
            AutoShutdownFuture: If `block` is False. This is a future object that can be used to check the status of the downloads.
            list: If `block` is True. This is a list of tuples where each tuple contains the URL of the download and the result of the download.
        """
        self._reset()
        if self._allow_reuse:
            future = self._pool.submit(self._execute, tasks, display)
        else:
            future = AutoShutdownFuture(
                self._pool.submit(self._execute, tasks, display),
                [*self._instances, self._pool],
            )

        if block:
            result = future.result()
            return result

        return future

    def stop(self) -> None:
        """Stops all active downloads."""
        with self._stop_lock:
            self._lock.set()
            self._stop = True
        for instance in self._instances:
            instance.stop()
        while self._lock.is_set():
            time.sleep(0.5)
        time.sleep(1)

    def shutdown(self) -> None:
        """Shutdown the factory."""
        for instance in self._instances:
            instance.shutdown()
        self._pool.shutdown()

    def _reset(self):
        self._stop = False
        self._prog = True
        self._completed_size = 0
        self._completed_prog = 0
        self._running.clear()
        self.completed.clear()
        self.failed.clear()
        self.remaining.clear()

    def _execute(self, tasks, display):
        start_time = time.time()
        self.total = len(tasks)
        self.remaining = tasks[len(self._instances) :]
        futures = {}

        for instance, task in zip(self._instances, tasks):
            self._add_future(instance, task, futures)
            self._running.append(instance)

        self._pool.submit(self._compute, display)

        while len(self.completed) + len(self.failed) != self.total:
            if self._stop:
                break

            for future in as_completed(futures):
                instance, curr_url = futures.pop(future)

                if instance.completed:
                    self._handle_completed(instance, curr_url, future.result())
                elif instance.failed:
                    self._handle_failed(curr_url)

                self._manage_remaining(instance, futures)

        self.time_spent = time.time() - start_time
        self._lock.clear()

        return self.completed

    def _add_future(self, instance, task, futures):
        url, *kwargs = task
        instance._status = None
        kwargs = kwargs[0] if kwargs else {}
        kwargs.update({"block": False, "display": False, "overwrite": False})
        future = instance.start(url, **kwargs)
        futures[future] = (instance, url)
        while instance._status is None:
            time.sleep(0.1)

    def _handle_completed(self, instance, curr_url, result):
        self._lock.set()
        if instance.size:
            self._completed_size += instance.size
        else:
            self._prog = False
        self._completed_prog += int((1 / self.total) * 100)
        self.completed.append((curr_url, result))

    def _handle_failed(self, curr_url):
        self._lock.set()
        self.failed.append(curr_url)
        logging.error("Download failed: %s", curr_url)

    def _manage_remaining(self, instance, futures):
        with self._stop_lock:
            if self._stop:
                self._running.remove(instance)
                return

            if self.remaining:
                self._add_future(instance, self.remaining.pop(0), futures)
            else:
                self._running.remove(instance)

            if len(self.completed) + len(self.failed) != self.total:
                self._lock.clear()
                time.sleep(0.5)

    def _compute(self, display):
        with ScreenCleaner(display):
            while True:
                if not self._lock.is_set():
                    self._calc_values()

                    if display:
                        self._display()

                    if (
                        self._stop
                        or len(self.completed) + len(self.failed) == self.total
                    ):
                        break
                time.sleep(0.5)

            self.progress = self._completed_prog
            self.current_size = self._completed_size
            if display:
                self._display()
                print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")

    def _calc_values(self):
        def sum_attribute(instances, attribute):
            return sum(getattr(instance, attribute) for instance in instances)

        def average_attribute(instances, attribute, total):
            return sum_attribute(instances, attribute) // total

        if self._running:
            self.speed = average_attribute(self._running, "speed", len(self._running))

            self.progress = (
                average_attribute(self._running, "progress", self.total)
                + self._completed_prog
            )
            self.current_size = (
                sum_attribute(self._running, "current_size") + self._completed_size
            )

    def _display(self):
        cursor_up()
        completed = len(self.completed)
        prog = (
            all(instance.size for instance in self._instances) if self._prog else False
        )

        if prog:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "
            print(progress_bar + info)
        else:
            download_stats = f"Downloading...{" " * 95}\n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "
            print(download_stats + info)
