from threading import Event
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Union
import logging

import requests
from reprint import output

from utls import (
    Multidown,
    Simpledown,
    FileValidator,
    combine_files,
    create_segment_table,
    seconds_to_hms,
    get_filepath,
    to_mb,
    AutoShutdownFuture,
)

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)


class Downloader:
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
        timeout (number or tuple, optional): A number, or a tuple, indicating how many seconds to wait for the client to make a connection and/or send a response. Default is 5 seconds.
        verify (bool or str, optional): A Boolean or a String indication to verify the servers TLS certificate or not. Default is True.
    """

    def __init__(self, **kwargs):
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._workers = []
        self._interrupt = Event()
        self._stop = False
        self._kwargs = {"timeout": 5, "allow_redirects": True}  # request module kwargs
        self._kwargs.update(kwargs)

        # public attributes
        self.size = None
        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.downloaded = 0
        self.eta = "99:59:59"
        self.remaining = None
        self.failed = False
        self.completed = False

    def _display(self, multithread, interval):
        download_mode = "Multi-Threaded" if multithread else "Single-Threaded"
        with output(initial_len=2, interval=interval) as dynamic_print:
            while True:
                if self.size:
                    progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}%"
                    progress_stats = f"Total: {to_mb(self.size):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s, ETA: {self.eta}"
                    dynamic_print[0] = progress_bar
                    dynamic_print[1] = progress_stats
                else:
                    download_stats = f"Downloaded: {to_mb(self.downloaded):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s"
                    dynamic_print[0] = "Downloading..."
                    dynamic_print[1] = download_stats

                if self._interrupt.is_set() or self.completed:
                    break

                time.sleep(interval)

        print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")

    def _calc_values(self):
        self.downloaded = sum(worker.curr for worker in self._workers)
        self.speed = sum(worker.speed for worker in self._workers) / len(self._workers)

        if self.size:
            self.progress = int(100 * self.downloaded / self.size)
            self.remaining = to_mb(self.size - self.downloaded)

            if self.speed:
                self.eta = seconds_to_hms(self.remaining / self.speed)
            else:
                self.eta = "99:59:59"

    def _single_thread(self, url, file_path):
        sd = Simpledown(url, file_path, self._interrupt, **self._kwargs)
        self._workers.append(sd)
        self._pool.submit(sd.worker)

    def _multi_thread(self, url, file_path, segments):
        for segment in range(segments):
            md = Multidown(
                self._segement_table,
                segment,
                self._interrupt,
                **self._kwargs,
            )
            self._workers.append(md)
            self._pool.submit(md.worker)

    def _get_header(self, url):
        kwargs = self._kwargs.copy()
        kwargs.pop("params", None)
        head = requests.head(url, **kwargs)

        if head.status_code != 200:
            self._interrupt.set()
            raise ConnectionError(
                f"Server Returned: {head.reason}({head.status_code}), Invalid URL"
            )

        return head.headers

    def _downloader(self, url, file_path, segments, display, multithread, etag):
        start_time = time.time()

        header = self._get_header(url)
        file_path = get_filepath(url, header, file_path)

        if size := int(header.get("content-length", 0)):
            self.size = size

        if self.size and header.get("accept-ranges") and multithread:
            if etag := header.get("etag", not etag):
                etag = etag.strip('"')

            self._segement_table = create_segment_table(
                url, file_path, segments, self.size, etag
            )
            segments = self._segement_table["segments"]

            self._pool.shutdown()
            self._pool = ThreadPoolExecutor(max_workers=segments + 1)

            self._multi_thread(url, file_path, segments)
        else:
            multithread = False
            self._single_thread(url, file_path)

        interval = 0.15

        if display:
            self._pool.submit(self._display, multithread, interval)

        while True:
            status = sum(worker.completed for worker in self._workers)
            self._calc_values()

            if self._interrupt.is_set():
                self.time_spent = time.time() - start_time
                return None

            elif status == len(self._workers):
                if multithread:
                    combine_files(file_path, segments)
                self.completed = True
                self.time_spent = time.time() - start_time
                return FileValidator(file_path)

            time.sleep(interval)

    def stop(self) -> None:
        """
        Stop the download process.
        """
        self._interrupt.set()
        self._stop = True
        time.sleep(1)

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
                        logging.info(f"Retrying... ({i}/{retries})")

                    self.__init__(**self._kwargs)  # for stop/start func
                    result = self._downloader(
                        _url, file_path, segments, display, multithread, etag
                    )

                    if self._stop or self.completed:
                        return result

                    time.sleep(3)

                except Exception as e:
                    logging.error(f"({e.__class__.__name__}) [{e}]")

                finally:
                    self._pool.shutdown()

            self.failed = True

        ex = ThreadPoolExecutor(max_workers=1)
        future = AutoShutdownFuture(ex.submit(download), ex)

        if block:
            result = future.result()
            return result

        return future
