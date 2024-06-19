import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from logging import Logger, getLogger
from typing import Union

from .pypdl_manager import Pypdl
from .utls import (
    AutoShutdownFuture,
    ScreenCleaner,
    cursor_up,
    default_logger,
    seconds_to_hms,
    to_mb,
)


class PypdlFactory:
    """
    A factory class for managing multiple instances of the Pypdl downloader.

    This class also supports additional keyword arguments specified in the documentation.
    """

    def __init__(
        self,
        instances: int = 2,
        allow_reuse: bool = False,
        logger: Logger = default_logger("PypdlFactory"),
        **kwargs,
    ):
        self._instances = [
            Pypdl(True, getLogger(f"PypdlFactory.instance-{i}"), **kwargs)
            for i in range(instances)
        ]
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
        self.logger = logger

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
        self.logger.debug("Downloading %s files", len(tasks))
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
            self.logger.debug("Initiating download stop")
            self._lock.set()
            self._stop = True
        for instance in self._instances:
            instance.stop()
        while self._lock.is_set():
            time.sleep(0.5)
        time.sleep(1)
        self.logger.debug("Download stopped")

    def shutdown(self) -> None:
        """Shutdown the factory."""
        self.logger.debug("Shutting down factory")
        for instance in self._instances:
            instance.shutdown()
        self._pool.shutdown()
        self.logger.debug("Factory shutdown")

    def _reset(self):
        self._stop = False
        self._prog = True
        self._completed_size = 0
        self._completed_prog = 0
        self._running.clear()
        self.completed.clear()
        self.failed.clear()
        self.remaining.clear()
        self.logger.debug("Reseted download factory")

    def _execute(self, tasks, display):
        start_time = time.time()
        self.total = len(tasks)
        self.remaining = tasks[len(self._instances) :]
        futures = {}

        for instance, task in zip(self._instances, tasks):
            self._add_future(instance, task, futures)
            self._running.append(instance)

        self._pool.submit(self._compute, display)

        self.logger.debug("Initiated waiting loop")
        while len(self.completed) + len(self.failed) != self.total:
            if self._stop:
                self.logger.debug("Exit waiting loop, download interrupted")
                break

            for future in as_completed(futures):
                instance, curr_url = futures.pop(future)

                if instance.completed:
                    self._handle_completed(instance, curr_url, future.result())
                elif instance.failed:
                    self._handle_failed(curr_url)

                self._manage_remaining(instance, futures)

        self.time_spent = time.time() - start_time
        self.logger.debug("Processed final task, clearing lock")
        self._lock.clear()
        self.logger.debug("Exit waiting loop, download completed")
        return self.completed

    def _add_future(self, instance, task, futures):
        self.logger.debug("Adding new task")
        url, *kwargs = task
        kwargs = kwargs[0] if kwargs else {}
        kwargs.update({"block": False, "display": False, "overwrite": False})
        future = instance.start(url, **kwargs)
        futures[future] = (instance, url)
        while instance.wait:
            time.sleep(0.1)
        self.logger.debug("Added new task: %s", url)

    def _handle_completed(self, instance, curr_url, result):
        self.logger.debug("Handling completed download, setting lock")
        self._lock.set()
        if instance.size:
            self._completed_size += instance.size
        else:
            self._prog = False
        self._completed_prog += (1 / self.total) * 100
        self.completed.append((curr_url, result))
        self.logger.debug("Download completed: %s", curr_url)

    def _handle_failed(self, curr_url):
        self.logger.debug("Handling failed download, setting lock")
        self._lock.set()
        self.failed.append(curr_url)
        self.logger.error("Download failed: %s", curr_url)

    def _manage_remaining(self, instance, futures):
        with self._stop_lock:
            if self._stop:
                self.logger.debug("Stop Initiated, removing instance from running")
                self._running.remove(instance)
                return

            if self.remaining:
                self.logger.debug("Remaining tasks: %s", len(self.remaining))
                self._add_future(instance, self.remaining.pop(0), futures)
            else:
                self.logger.debug("No remaining tasks, removing instance from running")
                self._running.remove(instance)

            if len(self.completed) + len(self.failed) != self.total:
                self.logger.debug("Not final task, releasing lock")
                self._lock.clear()
                time.sleep(0.5)

    def _compute(self, display):
        self.logger.debug("Starting download computation")
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

            self.progress = round(self._completed_prog)
            self.current_size = self._completed_size
            if display:
                self._display()
                print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")
            self.logger.debug("Computation ended")

    def _calc_values(self):
        def sum_attribute(instances, attribute):
            return sum(getattr(instance, attribute) for instance in instances)

        def average_attribute(instances, attribute, total):
            return sum_attribute(instances, attribute) // total

        if self._running:
            self.speed = average_attribute(self._running, "speed", len(self._running))

            self.progress = average_attribute(
                self._running, "progress", self.total
            ) + int(self._completed_prog)
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
            download_stats = f"Downloading...{' ' * 95}\n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "
            print(download_stats + info)
