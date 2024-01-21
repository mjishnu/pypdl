import os
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
    get_filename,
    timestring,
    to_mb,
)


class Downloader:
    def __init__(self, **kwargs):
        """
        Initializes the Downloader object.

        Parameters:
            kwargs: Keyword arguments to pass to the requests library.
        """
        # private attributes
        self._segement_table = {}  # dictionary to keep track of download progress
        self._workers = []  # list of multidownload object objects
        self._threads = []  # list of all worker threads
        self._error = threading.Event()  # event to signal any download errors
        self._stop = threading.Event()  # event to stop the download
        self._kwargs = kwargs  # keyword arguments

        # public attributes
        self.size = inf  # download size in bytes
        self.progress = 0  # download progress percentage
        self.speed = 0  # download speed in MB/s
        self.time_spent = 0  # time spent downloading
        self.downloaded = 0  # amount of data downloaded in MB
        self.eta = "99:59:59"  # estimated time remaining for download completion
        self.remaining = 0  # amount of data remaining to be downloaded
        self.failed = False  # flag to indicate if download failure
        self.completed = False  # flag to indicate if download is complete

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

                if self._stop.is_set() or self._error.is_set() or self.completed:
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

    def _downloader(self, url, filepath, segments, display, multithread, etag):
        start_time = time.time()
        head = requests.head(url, timeout=20, allow_redirects=True, **self._kwargs)

        if head.status_code != 200:
            self._error.set()
            print(f"Server Returned: {head.reason}({head.status_code}), Invalid URL")
            return

        header = head.headers
        filename = get_filename(url, header)
        filepath = filepath or filename

        if os.path.isdir(filepath):
            filepath = os.path.join(filepath, filename)

        if size := int(header.get("content-length", 0)):
            self.size = size

        if self.size is inf or header.get("accept-ranges") is None:
            multithread = False
            sd = Simpledown(url, filepath, self._stop, self._error, **self._kwargs)
            th = threading.Thread(target=sd.worker)
            self._workers.append(sd)
            th.start()
        else:
            if etag := header.get("etag", not etag):
                etag = etag.strip('"')

            self._segement_table = create_segment_table(
                url, filepath, segments, self.size, etag
            )
            segments = self._segement_table["segments"]
            for segment in range(segments):
                md = Multidown(
                    self._segement_table,
                    segment,
                    self._stop,
                    self._error,
                    **self._kwargs,
                )
                th = threading.Thread(target=md.worker)
                th.start()
                self._threads.append(th)
                self._workers.append(md)

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

            if self._stop.is_set() or self._error.is_set():
                break

            if status == len(self._workers):
                if multithread:
                    combine_files(filepath, segments)
                self.completed = True
                break
            time.sleep(interval)

        self.time_spent = time.time() - start_time

    def stop(self):
        """
        Stop the download process.
        """
        time.sleep(3)
        self._stop.set()
        for thread in self._threads:  # waiting for threads to die
            thread.join()

    def start(
        self,
        url: str,
        filepath: Optional[str] = None,
        segments: int = 10,
        display: bool = True,
        multithread: bool = True,
        block: bool = True,
        retries: int = 0,
        retry_func: Optional[Callable[[], str]] = None,
        etag: bool = True,
    ):
        """
        Start the download process.

        Parameters:
            url (str): The download URL.
            filepath (str): The optional file path to save the download. by default it uses the present working directory,
                If filepath is a directory then the file is downloaded into it else the file is downloaded with the given name.
            segments (int): The number of segments the file should be divided in multi-threaded download.
            display (bool): Whether to display download progress and other optional messages.
            multithread (bool): Whether to use multi-threaded download.
            block (bool): Whether to block until the download is complete.
            retries (int): The number of times to retry the download in case of an error.
            retry_func (function): A function to call to get a new download URL in case of an error.
            etag (bool): Whether to validate etag before resuming downloads.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = retry_func() if i > 0 and callable(retry_func) else url
                    if i > 0 and display:
                        print(f"Retrying... ({i}/{retries})")

                    self.__init__(**self._kwargs)  # for stop/start func
                    self._downloader(
                        _url, filepath, segments, display, multithread, etag
                    )

                    if not self._error.is_set():
                        break

                    time.sleep(3)

                except Exception as e:
                    print(f"Download Error: ({e.__class__.__name__}, {e})")
                    self._error.set()

            if self._error.is_set():
                self.failed = True

        download_thread = threading.Thread(target=download)
        download_thread.start()

        if block:
            download_thread.join()
