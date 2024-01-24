import threading
import time
from collections import deque
from math import inf
from typing import Callable, Optional

import requests
from reprint import output

from utls import (
    Multidown,
    Simpledown,
    combine_files,
    create_segment_table,
    timestring,
    get_filepath,
    to_mb,
)


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
        timeout (number or tuple, optional): A number, or a tuple, indicating how many seconds to wait for the client to make a connection and/or send a response. Default is 20 seconds.
        verify (bool or str, optional): A Boolean or a String indication to verify the servers TLS certificate or not. Default is True.
    """

    def __init__(self, **kwargs):
        self._segement_table = {}
        self._workers = []
        self._threads = []
        self._interrupt = threading.Event()
        self._stop = False
        self._kwargs = {"timeout": 20, "allow_redirects": True}  # request module kwargs
        self._kwargs.update(kwargs)

        self.size = inf
        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.downloaded = 0
        self.eta = "99:59:59"
        self.remaining = 0
        self.failed = False
        self.completed = False

    def _display(self, multithread, interval):
        download_mode = "Multi-Threaded" if multithread else "Single-Threaded"
        with output(initial_len=2, interval=interval) as dynamic_print:
            while True:
                if self.size != inf:
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

        print(f"Time elapsed: {timestring(self.time_spent)}")

    def _calc_values(self, recent_queue, interval):
        self.downloaded = sum(worker.curr for worker in self._workers)
        self.progress = (
            int(100 * self.downloaded / self.size) if self.size != inf else 0
        )

        # Speed calculation
        recent_queue.appendleft(self.downloaded)
        non_zero_list = [value for value in recent_queue if value]
        if len(non_zero_list) < 2:
            self.speed = 0
        else:
            diff = [a - b for a, b in zip(non_zero_list, non_zero_list[1:])]
            self.speed = to_mb(sum(diff) / len(diff)) / interval

        self.remaining = to_mb(self.size - self.downloaded)
        if self.size != inf and self.speed != 0:
            self.eta = timestring(self.remaining / self.speed)
        else:
            self.eta = "99:59:59"

    def _single_thread(self, url, file_path):
        sd = Simpledown(url, file_path, self._interrupt, **self._kwargs)
        th = threading.Thread(target=sd.worker)
        self._workers.append(sd)
        th.start()

    def _multi_thread(self, url, file_path):
        segments = self._segement_table["segments"]
        for segment in range(segments):
            md = Multidown(
                self._segement_table,
                segment,
                self._interrupt,
                **self._kwargs,
            )
            th = threading.Thread(target=md.worker)
            th.start()
            self._threads.append(th)
            self._workers.append(md)

    def _downloader(self, url, file_path, segments, display, multithread, etag):
        start_time = time.time()

        kwargs = self._kwargs.copy()
        kwargs.pop("params", None)
        head = requests.head(url, **kwargs)

        if head.status_code != 200:
            self._interrupt.set()
            print(f"Server Returned: {head.reason}({head.status_code}), Invalid URL")
            return

        header = head.headers
        file_path = get_filepath(url, header, file_path)

        if size := int(header.get("content-length", 0)):
            self.size = size

        if not multithread or self.size is inf or header.get("accept-ranges") is None:
            multithread = False
            self._single_thread(url, file_path)

        else:
            if etag := header.get("etag", not etag):
                etag = etag.strip('"')

            self._segement_table = create_segment_table(
                url, file_path, segments, self.size, etag
            )
            self._multi_thread(url, file_path)

        interval = 0.15

        if display:
            display_thread = threading.Thread(
                target=self._display, args=[multithread, interval]
            )
            display_thread.start()

        recent_queue = deque([0] * 12, maxlen=12)

        while True:
            status = sum(worker.completed for worker in self._workers)
            self._calc_values(recent_queue, interval)

            if self._interrupt.is_set():
                break

            elif status == len(self._workers):
                if multithread:
                    combine_files(file_path, segments)
                self.completed = True
                break
            time.sleep(interval)

        self.time_spent = time.time() - start_time

    def stop(self):
        """
        Stop the download process.
        """
        time.sleep(3)
        self._interrupt.set()
        self._stop = True
        for thread in self._threads:  # waiting for threads to die
            thread.join()

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
    ):
        """
        Start the download process.

        Parameters:
            url (str): The download URL.
            file_path  (str, Optional): The optional file path to save the download. by default it uses the present working directory,
                If file_path  is a directory then the file is downloaded into it else the file is downloaded with the given name.
            segments (int, Optional): The number of segments the file should be divided in multi-threaded download.
            display (bool, Optional): Whether to display download progress and other opt_stopional messages.
            multithread (bool, Optional): Whether to use multi-threaded download.
            block (bool, Optional): Whether to block until the download is complete.
            retries (int, Optional): The number of times to retry the download in case of an error.
            mirror_func (function, Optional): A function to get a new download URL in case of an error.
            etag (bool, Optional): Whether to validate etag before resuming downloads.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = mirror_func() if i > 0 and callable(mirror_func) else url
                    if i > 0 and display:
                        print(f"Retrying... ({i}/{retries})")

                    self.__init__(**self._kwargs)  # for stop/start func
                    self._downloader(
                        _url, file_path, segments, display, multithread, etag
                    )

                    if self._stop or self.completed:
                        break

                    time.sleep(3)

                except Exception as e:
                    print(f"Download Error: ({e.__class__.__name__}, {e})")
                    self._interrupt.set()

            if not self._stop and self._interrupt.is_set():
                self.failed = True

        download_thread = threading.Thread(target=download)
        download_thread.start()

        if block:
            download_thread.join()
