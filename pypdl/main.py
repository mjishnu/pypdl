import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Union

from manager import DownloadManager
from utls import (
    AutoShutdownFuture,
    FileValidator,
    ScreenCleaner,
    cursor_up,
    seconds_to_hms,
    to_mb,
)

handler = logging.FileHandler("pypdl.log", mode="a", delay=True)
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(levelname)s: %(message)s", datefmt="%d-%m-%y %H:%M:%S"
    )
)
logging.basicConfig(level=logging.INFO, handlers=[handler])


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
        multisegment: bool = True,
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
            multisegment (bool, Optional): Whether to use multi-Segment download. Default is True.
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
                    if i > 0:
                        logging.info("Retrying... (%d/%d)", i, retries)

                    self._reset()
                    result = self._execute(
                        _url,
                        file_path,
                        segments,
                        display,
                        multisegment,
                        etag,
                        overwrite,
                    )

                    if self._stop or self.completed:
                        if display:
                            print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")
                        return result

                    time.sleep(3)

                except Exception as e:
                    logging.error("(%s) [%s]", e.__class__.__name__, e)

            self.failed = True
            return None

        future = AutoShutdownFuture(self._pool.submit(download), self._pool)

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
    """
    A factory class for managing multiple instances of the Pypdl downloader.

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

    def __init__(self, instances: int = 2, **kwargs):
        if not hasattr(self, "_instances"):
            self._instances = [Pypdl(**kwargs) for _ in range(instances)]
        self._stop = False
        self._prog = True
        self._pool = None
        self._completed_size = 0
        self._completed_prog = 0

        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.total = 0
        self.eta = "99:59:59"
        self.completed = []
        self.failed = []
        self.remaining = []

    def _calc_values(self):
        def sum_attribute(instances, attribute):
            return sum(getattr(instance, attribute) for instance in instances)

        def average_attribute(instances, attribute, total):
            return sum_attribute(instances, attribute) // total

        self.speed = average_attribute(self._instances, "speed", len(self._instances))

        self.progress = (
            average_attribute(self._instances, "progress", self.total)
            + self._completed_prog
        )
        self.current_size = (
            sum_attribute(self._instances, "current_size") + self._completed_size
        )

        if self.speed:
            self.eta = seconds_to_hms(
                (sum_attribute(self._instances, "remaining") // self.speed) * self.total
            )
        else:
            self.eta = "99:59:59"

    def _display(self):
        cursor_up()
        completed = len(self.completed)
        prog = (
            all(instance.size for instance in self._instances) if self._prog else False
        )

        if prog:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s, ETA: {self.eta} "
            print(progress_bar + info)
        else:
            download_stats = f"Downloading...{" " * 95}\n"
            info = f"Total: {completed}/{self.total}, Downloaded: {to_mb(self.current_size):.2f} MB, Speed: {self.speed:.2f} MB/s "
            print(download_stats + info)

    def _compute(self, display):
        with ScreenCleaner(display):
            while len(self.completed) + len(self.failed) < self.total:
                self._calc_values()
                if display:
                    self._display()
                if self._stop:
                    break
                time.sleep(0.5)

            self.progress = self._completed_prog
            self.current_size = self._completed_size
            if display:
                self._display()
                print("Time elapsed: ", seconds_to_hms(self.time_spent))

    def _add_future(self, instance, task, futures):
        url, *kwargs = task
        kwargs = kwargs[0] if kwargs else {}
        kwargs.update({"block": False, "display": False, "overwrite": False})
        job = instance.start(url, **kwargs)
        futures[job.future] = (job, instance, url)

    def _execute(self, tasks):
        start_time = time.time()
        self.total = len(tasks)
        self.remaining = tasks[len(self._instances) :]
        futures = {}

        for instance, task in zip(self._instances, tasks):
            self._add_future(instance, task, futures)

        while len(self.completed) + len(self.failed) < self.total:
            if self._stop:
                break

            for future in as_completed(futures):
                job, instance, curr_url = futures.pop(future)
                result = job.result()  # shutdown executor

                if instance.completed:
                    if instance.size:
                        self._completed_size += instance.size
                    else:
                        self._prog = False
                    self._completed_prog += int((1 / self.total) * 100)
                    self.completed.append((curr_url, result))
                elif instance.failed:
                    self.failed.append(curr_url)
                    logging.error("Download failed: %s", curr_url)
                else:
                    continue

                if self.remaining:
                    self._add_future(instance, self.remaining.pop(0), futures)

        self.time_spent = time.time() - start_time
        return self.completed

    def start(
        self, tasks: list, display: bool = True, block: bool = True
    ) -> Union[AutoShutdownFuture, list]:
        """
        Start the download process for multiple tasks.

        Parameters:
            tasks (list): A list of tasks to be downloaded.
                Each task is a tuple where the 1st element is the URL and the 2nd element is an optional dict with kwargs for pypdl start method.
            display (bool, Optional): Whether to display download progress and other messages. Default is True.
            block (bool, Optional): Whether to block the function until all downloads are complete. Default is True.

        Returns:
            AutoShutdownFuture: If `block` is False. This is a future object that can be used to check the status of the downloads.
            list: If `block` is True. This is a list of tuples where each tuple contains the URL of the download and the result of the download.
        """

        self.__init__()

        if block:
            self._pool = ThreadPoolExecutor(max_workers=1)
        else:
            self._pool = ThreadPoolExecutor(max_workers=2)

        future = AutoShutdownFuture(self._pool.submit(self._execute, tasks), self._pool)

        if block:
            self._compute(display)
            result = future.result()
            return result

        self._pool.submit(self._compute, display)
        return future

    def stop(self):
        """Stops all active downloads."""
        self._stop = True
        for instance in self._instances:
            instance.stop()
        self._pool.shutdown()
