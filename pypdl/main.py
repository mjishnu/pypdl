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
        # keep track of recent download speed
        self._recent = deque([0] * 12, maxlen=12)
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
        self.download_mode = ""  # download mode: single-threaded or multi-threaded
        self.time_spent: Optional[float] = None  # time spent downloading
        self.downloaded = 0  # amount of data self.downloaded in MB
        self.eta = "99:59:59"  # estimated time remaining for download completion
        self.remaining = 0  # amount of data remaining to be self.downloaded
        self.Failed = False  # flag to indicate if download failure

    def _download(
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

        Parameters:
            url (str): The URL of the file to download.
            filepath (str): The file path to save the download.
                If it is directory or None then filepath is appended with file name.
            segments (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
        """
        header = requests.head(
            url, timeout=20, allow_redirects=True, **self._kwargs
        ).headers
        filename = get_filename(url, header)

        if filepath is None:
            filepath = filename

        if os.path.isdir(filepath) is True:
            filepath = os.path.join(filepath, filename)

        if size := int(header.get("content-length")):
            self.size = size

        start_time = time.time()

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
                # create multidownload object for each connection
                md = Multidown(self._dic, i, self._stop, self._Error, **self._kwargs)
                # create worker thread for each connection
                th = threading.Thread(target=md.worker)
                th.start()
                self._threads.append(th)
                self._workers.append(md)

        interval = 0.15
        self.download_mode = "Multi-Threaded" if multithread else "Single-Threaded"
        # use reprint library to print dynamic progress output
        with output(initial_len=5, interval=0) as dynamic_print:
            while True:
                # check if all workers have completed
                status = sum(i.completed for i in self._workers)
                # get the self.size amount of data self.downloaded
                self.downloaded = sum(i.curr for i in self._workers)
                # keep track of recent download speeds
                try:
                    # calculate download progress percentage
                    self.progress = int(100 * self.downloaded / self.size)
                except ZeroDivisionError:
                    self.progress = 0

                # calculate download speed
                self._recent.append(self.downloaded)
                recent_speed = len([i for i in self._recent if i])
                if not recent_speed:
                    self.speed = 0
                else:
                    recent = list(self._recent)[12 - recent_speed :]
                    if len(recent) == 1:
                        self.speed = recent[0] / 1048576 / interval
                    else:
                        diff = [b - a for a, b in zip(recent, recent[1:])]
                        self.speed = sum(diff) / len(diff) / 1048576 / interval

                # calculate estimated time remaining for download completion
                self.remaining = to_mb(self.size - self.downloaded)
                if self.speed and self.size != inf:
                    self.eta = timestring(self.remaining / self.speed)
                else:
                    self.eta = "99:59:59"

                # print dynamic progress output
                if display:
                    if multithread:
                        dynamic_print[0] = (
                            "[{0}{1}] {2}".format(
                                "\u2588" * self.progress,
                                "\u00b7" * (100 - self.progress),
                                str(self.progress),
                            )
                            + "%"
                        )
                        dynamic_print[
                            1
                        ] = f"Total: {to_mb(self.size):.2f} MB, Download Mode: {self.download_mode}, Speed: {self.speed:.2f} MB/s, ETA: {self.eta}"
                    else:
                        dynamic_print[0] = "Downloading..."
                        dynamic_print[
                            1
                        ] = f"Downloaded: {to_mb(self.downloaded):.2f} MB, Download Mode: {self.download_mode}, Speed: {self.speed:.2f} MB/s"

                # check if download has been stopped or if an error has occurred
                if self._stop.is_set() or self._Error.is_set():
                    break

                # check if all workers have completed
                if status == len(self._workers):
                    if multithread:
                        combine_files(filepath, segments)
                    break
                time.sleep(interval)
        self.time_spent = time.time() - start_time

        # print download result
        if display:
            if self._stop.is_set():
                print("Task interrupted!")
            print(f"Time elapsed: {timestring(self.time_spent)}")

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
                If filepath is a directory then the file is self.downloaded into it else the file is self.downloaded with the given name.
            segments (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
            block (bool): Whether to block until the download is complete.
            retries (int): The number of times to retry the download in case of an error.
            retry_func (function): A function to call to get a new download URL in case of an error.
        """

        def start_thread():
            try:
                # start the download, not using "try" since all expected errors and will trigger error event
                self._download(url, filepath, segments, display, multithread, etag)
                # retry the download if there are errors
                for _ in range(retries):
                    if self._Error.is_set():
                        time.sleep(3)
                        # reset the downloader object
                        self.__init__(**self._kwargs)

                        # get a new download URL to retry
                        _url = url
                        if callable(retry_func):
                            try:
                                _url = retry_func()
                            except Exception as e:
                                print(
                                    f"Retry function Error: ({e.__class__.__name__}, {e})"
                                )

                        if display:
                            print("retrying...")
                        # restart the download
                        self._download(
                            _url, filepath, segments, display, multithread, etag
                        )
                    else:
                        break
            # if there's an error, set the error event and print the error message
            except Exception as e:
                raise Exception(e)
                print(f"Download Error: ({e.__class__.__name__}, {e})")
                self._Error.set()

            # if error flag is set, set the failed flag to True
            if self._Error.is_set():
                self.Failed = True
                print("Download Failed!")

        # Initialize the downloader with stop Event
        self.__init__(**self._kwargs)
        # Start the download process in a new thread
        th = threading.Thread(target=start_thread)
        th.start()

        # Block the current thread until the download is complete
        if block:
            th.join()
