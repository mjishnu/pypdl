import os
import threading
import time
from math import inf
from typing import Callable, Optional
from collections import deque
import requests
from reprint import output
from utls import (
    Multidown,
    Simpledown,
    get_filename,
    create_segement_table,
    combine_files,
    timestring,
    to_mb,
)


class Downloader:
    def __init__(self, **kwargs):
        """
        Initializes the Downloader object.

        Parameters:
            headers (dict): User headers to be used in the download request.
            proxies (dict): An optional parameter to set custom proxies.
            auth (tuple): An optional parameter to set authentication for proxies.

        """
        # private attributes
        # keep track of non_zero_list download speed
        self._dic = {}  # dictionary to keep track of download progress
        self._workers = []  # list of multidownload object objects
        self._Error = threading.Event()  # event to signal any download errors
        self._threads = []  # list of all worker threads
        self._stop = threading.Event()  # event to stop the download
        self._kwargs = kwargs  # keyword arguments

        # public attributes
        self.size = inf  # download size in bytes
        self.progress = 0  # download progress percentage
        self.speed = 0  # download speed in MB/s
        self.time_spent: Optional[float] = None  # time spent downloading
        self.downloaded = 0  # amount of data self.downloaded in MB
        self.eta = "99:59:59"  # estimated time remaining for download completion
        self.remaining = 0  # amount of data remaining to be self.downloaded
        self.Failed = False  # flag to indicate if download failure
        self.completed = False  # flag to indicate if download is complete

    def _display(self):
        interval = 0.2
        download_mode = "Multi-Threaded" if self._dic else "Single-Threaded"
        with output(initial_len=2, interval=interval) as dynamic_print:
            while True:
                if self.size != inf:
                    with_size_0 = f"[{'\u2588' * self.progress}{'\u00b7' * (100 - self.progress)}] {self.progress}%"
                    with_size_1 = f"Total: {to_mb(self.size):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s, ETA: {self.eta}"

                    dynamic_print[0] = with_size_0
                    dynamic_print[1] = with_size_1
                else:
                    no_size_1 = f"Downloaded: {to_mb(self.downloaded):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s"

                    dynamic_print[0] = "Downloading..."
                    dynamic_print[1] = no_size_1
                if self._stop.is_set() or self._Error.is_set() or self.completed:
                    break
                time.sleep(interval)
        print(f"Time elapsed: {timestring(self.time_spent)}")

    def _calc_values(self, recent_queue, interval):
        self.downloaded = sum(i.curr for i in self._workers)
        self.progress = (
            int(100 * self.downloaded / self.size) if self.size != inf else 0
        )

        # speed calculation
        recent_queue.appendleft(self.downloaded)
        non_zero_vals = len([i for i in recent_queue if i])
        if non_zero_vals == 0:
            self.speed = 0
        else:
            non_zero_list = list(recent_queue)[:non_zero_vals]
            if len(non_zero_list) == 1:
                self.speed = to_mb(non_zero_list[0]) / interval
            else:
                diff = [a - b for a, b in zip(non_zero_list, non_zero_list[1:])]
                self.speed = to_mb(sum(diff) / len(diff)) / interval

        self.remaining = to_mb(self.size - self.downloaded)
        self.eta = (
            timestring(self.remaining / self.speed)
            if (self.size != inf and self.speed != 0)
            else "99:59:59"
        )

    def _downloader(
        self,
        url: str,
        filepath: str,
        segments: int,
        display: bool,
        multithread: bool,
        etag,
    ):
        """
        Internal download function.
        """
        start_time = time.time()
        head = requests.head(url, timeout=20, allow_redirects=True, **self._kwargs)
        if head.status_code != 200:
            self._Error.set()
            print(f"Server Returned: {head.reason}({head.status_code}), Invalid URL")
            return

        header = head.headers
        filename = get_filename(url, header)

        if filepath is None:
            filepath = filename

        if os.path.isdir(filepath) is True:
            filepath = os.path.join(filepath, filename)

        if size := int(header.get("content-length")):
            self.size = size

        if self.size is inf or header.get("accept-ranges") is None:
            multithread = False
            sd = Simpledown(url, filepath, self._stop, self._Error, **self._kwargs)
            th = threading.Thread(target=sd.worker)
            self._workers.append(sd)
            th.start()
        else:
            if etag := header.get("etag", not etag):
                etag = etag.strip('"')

            self._dic = create_segement_table(url, filepath, segments, self.size, etag)
            segments = self._dic["segments"]
            for i in range(segments):
                md = Multidown(self._dic, i, self._stop, self._Error, **self._kwargs)
                th = threading.Thread(target=md.worker)
                th.start()
                self._threads.append(th)
                self._workers.append(md)

        recent_queue = deque([0] * 12, maxlen=12)
        interval = 0.15

        if display:
            display_thread = threading.Thread(target=self._display)
            display_thread.start()

        while True:
            status = sum(i.completed for i in self._workers)
            self._calc_values(recent_queue, interval)

            if self._stop.is_set() or self._Error.is_set():
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
        # waiting for all threads to be killed by the poison pill
        for thread in self._threads:
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
        etag=True,
    ):
        """
        Start the download process.

        Parameters:
            url (str): The download URL.
            filepath (str): The optional file path to save the download. by default it uses the present working directory,
                If filepath is a directory then the file is downloaded into it else the file is downloaded with the given name.
            segments (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
            block (bool): Whether to block until the download is complete.
            retries (int): The number of times to retry the download in case of an error.
            retry_func (function): A function to call to get a new download URL in case of an error.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = url
                    if i > 0:
                        if display:
                            print(f"Retrying... ({i}/{retries})")
                        _url = retry_func() if callable(retry_func) else url
                        self.__init__(**self._kwargs)

                    self._downloader(
                        _url, filepath, segments, display, multithread, etag
                    )

                    if not self._Error.is_set():
                        break

                    time.sleep(3)

                except Exception as e:
                    print(f"Download Error: ({e.__class__.__name__}, {e})")
                    self._Error.set()

            # Set the Failed flag if there was an error
            if self._Error.is_set():
                self.Failed = True

        download_thread = threading.Thread(target=download)
        download_thread.start()

        if block:
            download_thread.join()
