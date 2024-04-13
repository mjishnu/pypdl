import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Union
from threading import Event

from manager import DownloadManager
from utls import AutoShutdownFuture, FileValidator, ScreenCleaner, seconds_to_hms, to_mb

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)


class Pypdl(DownloadManager):
    """
    A multi-threaded file downloader that supports progress tracking, retries, pause/resume functionality etc.

    Keyword Arguments:
        params (dict, optional): A dictionary, list of tuples or bytes to send as a query string. Default is None.
        allow_redirects (bool, optional): A Boolean to enable/disable redirection. Default is True.
        auth (tuple, optional): A tuple to enable a certain HTTP authentication. Default is None.
        cert (str or tuple, optional): A String or Tuple specifying a cert file or key. Default is None.
        cookies (dict, optional): A dictionary of cookies to send to the specified url. Default is None.
        headers (dict, optional): A dictionary of HTTP headers to send to the specified url. Default is None.
        proxies (dict, optional): A dictionary of the protocol to the proxy url. Default is None.
        timeout (number or tuple, optional): A number, or a tuple, indicating how many seconds to wait for the client to make a connection and/or send a response. Default is 10 seconds.
        verify (bool or str, optional): A Boolean or a String indication to verify the servers TLS certificate or not. Default is True.
    """

    def start(
        self,
        url: str,
        file_path: Optional[str] = None,
        segments: int = 10,
        display: bool = True,
        multithread: bool = True,
        block: bool = True,
        retries: int = 0,
        mirror_func: Optional[Callable[[], str]] = None,
        etag: bool = True,
        overwrite: bool = True,
    ) -> Union[AutoShutdownFuture, FileValidator, None]:
        """
        Start the download process.

        Parameters:
            url (str): The URL to download from.
            file_path (str, Optional): The path to save the downloaded file. If not provided, the file is saved in the current working directory.
                If `file_path` is a directory, the file is saved in that directory. If `file_path` is a file name, the file is saved with that name.
            segments (int, Optional): The number of segments to divide the file into for multi-threaded download. Default is 10.
            display (bool, Optional): Whether to display download progress and other messages. Default is True.
            multithread (bool, Optional): Whether to use multi-threaded download. Default is True.
            block (bool, Optional): Whether to block the function until the download is complete. Default is True.
            retries (int, Optional): The number of times to retry the download if it fails. Default is 0.
            mirror_func (Callable[[], str], Optional): A function that returns a new download URL if the download fails. Default is None.
            etag (bool, Optional): Whether to validate the ETag before resuming downloads. Default is True.
            overwrite (bool, Optional): Whether to overwrite the file if it already exists. Default is True.

        Returns:
            AutoShutdownFuture: If `block` is False.
            FileValidator: If `block` is True and the download successful.
            None: If `block` is True and the download fails.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = mirror_func() if i > 0 and callable(mirror_func) else url
                    if i > 0 and display:
                        logging.info("Retrying... (%d/%d)", i, retries)

                    self.__init__(**self._kwargs)
                    result = self._execute(
                        _url, file_path, segments, display, multithread, etag, overwrite
                    )

                    if self._stop or self.completed:
                        if display:
                            print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")
                        return result

                    time.sleep(3)

                except Exception as e:
                    logging.error("(%s) [%s]", e.__class__.__name__, e)

                finally:
                    if self._pool:
                        self._pool.shutdown()

            self.failed = True
            return None

        ex = ThreadPoolExecutor(max_workers=1)
        future = AutoShutdownFuture(ex.submit(download), ex)

        if block:
            result = future.result()
            return result

        return future

    def stop(self) -> None:
        """Stop the download process."""
        self._interrupt.set()
        self._stop = True
        time.sleep(1)  # wait for threads


class PypdlFactory:
    def __init__(self, instances: int, **kwargs):
        self._kwargs = kwargs
        self._instances = [Pypdl(**self._kwargs) for _ in range(instances)]
        self._stop = False
        self._completed_data = 0
        self._completed_prog = 0
        self._clear = Event()

        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.total = 0
        self.eta = "99:59:59"
        self.completed = []
        self.failed = []
        self.remaining = []

    def _compute(self, display):
        with ScreenCleaner(display) as cleaner:
            while len(self.completed) + len(self.failed) < self.total:
                self._calc_values()

                if display:
                    self._display(cleaner)

                if self._stop:
                    break

                time.sleep(0.5)
            self._calc_values()
            if display:
                self._display(cleaner)

    def _calc_values(self):
        def sum_attribute(instances, attribute):
            return sum(getattr(instance, attribute) for instance in instances)

        def average_attribute(instances, attribute, total):
            return sum_attribute(instances, attribute) // total

        self.current_size = (
            sum_attribute(self._instances, "current_size") + self._completed_data
        )
        self.speed = average_attribute(self._instances, "speed", len(self._instances))
        self.progress = (
            average_attribute(self._instances, "progress", self.total)
            + self._completed_prog
        )

        if self.speed:
            self.eta = seconds_to_hms(
                (sum_attribute(self._instances, "remaining") // self.speed) * self.total
            )
        else:
            self.eta = "99:59:59"

    def _display(self, cleaner):
        sys.stdout.write("\x1b[1A" * 2)  # Cursor up 2 lines
        completed = len(self.completed)

        if self._clear.is_set():
            cleaner.clear()
            self._clear.clear()

        prog = all(instance.size for instance in self._instances)

        if prog:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s, ETA: {self.eta} "
            print(progress_bar + info)
        else:
            download_stats = "Downloading... \n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "
            print(download_stats + info)

        sys.stdout.flush()

    def _execute(self, tasks):
        start_time = time.time()
        self.total = len(tasks)

        for instance, task in zip(self._instances, tasks):
            url, kwargs = task
            kwargs.update({"block": False, "display": False, "overwrite": False})
            job = instance.start(url, **kwargs)
            futures = {job.future: (job, instance, url)}
            self.remaining = tasks[len(self._instances) :]

        while len(self.completed) + len(self.failed) < self.total:
            for future in as_completed(futures):
                job, instance, curr_url = futures.pop(future)
                result = job.result()  # shutdown executor
                self._clear.set()

                if instance.completed:
                    self._completed_data += instance.size if instance.size else 0
                    self._completed_prog += int((1 / self.total) * 100)
                    self.completed.append((curr_url, result))
                elif instance.failed:
                    self.failed.append(curr_url)
                else:
                    break

                if self.remaining:
                    new_url, kwargs = self.remaining.pop(0)
                    kwargs.update(
                        {"block": False, "display": False, "overwrite": False}
                    )
                    job = instance.start(new_url, **kwargs)
                    futures[job.future] = (job, instance, url)

        self.time_spent = time.time() - start_time
        print("Time elapsed: ", seconds_to_hms(self.time_spent))
        return self.completed

    def start(self, tasks, display=True, block=True):
        self.__init__(len(self._instances), **self._kwargs)

        if block:
            pool = ThreadPoolExecutor(max_workers=1)
        else:
            pool = ThreadPoolExecutor(max_workers=2)

        future = AutoShutdownFuture(pool.submit(self._execute, tasks), pool)

        if block:
            self._compute(display)
            result = future.result()
            return result

        pool.submit(self._compute, display)
        return future

    def stop(self):
        self.stop = True
        for instance in self._instances:
            instance.stop()
