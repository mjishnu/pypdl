import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from math import inf
from pathlib import Path
from typing import Callable, Optional

import requests
from reprint import output
from utls import Multidown, Singledown, get_filename, timestring, to_mb


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
        self.size = 0  # download size in bytes
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
        num_connections: int,
        display: bool,
        multithread: bool,
    ):
        """
        Internal download function.

        Parameters:
            url (str): The URL of the file to download.
            filepath (str): The file path to save the download.
                If it is directory or None then filepath is appended with file name.
            num_connections (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
        """
        header = requests.head(url, timeout=20, allow_redirects=True, **self._kwargs)

        filename = get_filename(url, header.headers)
        if filepath is None:
            filepath = filename

        elif os.path.isdir(filepath) is True:
            filepath = os.path.join(filepath, filename)

        self.size = int(header.headers.get("content-length"))
        if self.size == 0:
            self.size = inf
            multithread = False

        started = datetime.now()

        if to_mb(self.size) < 50:
            num_connections = 5 if num_connections > 5 else num_connections

        if not multithread or header.headers.get("accept-ranges") is None:
            sd = Singledown(url, filepath, self._stop, self._Error, **self._kwargs)
            th = threading.Thread(target=sd.worker)
            self._workers.append(sd)
            th.start()
            # completed till here
        else:
            progress_file = Path(filepath + ".json")
            if progress_file.exists():
                # load the progress from the progress file
                # the object_hook converts the key strings whose value is int to type int
                try:
                    progress = json.loads(
                        progress_file.read_text(),
                        object_hook=lambda d: {
                            int(k) if k.isdigit() else k: v for k, v in d.items()
                        },
                    )
                    if progress["url"] == url and progress["total_size"] == self.size:
                        num_connections = progress["threads"]

                except:
                    pass
            segment = self.size / num_connections
            self._dic["url"] = url
            self._dic["total_size"] = self.size
            self._dic["threads"] = num_connections
            for i in range(num_connections):
                try:
                    # try to use progress file to resume download
                    start = progress[i]["start"]
                    end = progress[i]["end"]
                    segment_size = progress[i]["size"]
                except:
                    # if not able to use progress file, then calculate the start, end, curr, and self.size
                    # calculate the beginning byte offset by multiplying the segment by num_connections.
                    start = int(segment * i)
                    # here end is the ((segment * next part) - 1 byte) since the last byte is self.downloaded by next part except for the last part
                    end = int(segment * (i + 1)) - (i != num_connections - 1)
                    segment_size = end - start + (i != num_connections - 1)

                self._dic[i] = {
                    "start": start,
                    "end": end,
                    "segment_size": segment_size,
                    "path": f"{filepath}.{i}.part",
                }
                # create multidownload object for each connection
                md = Multidown(self._dic, i, self._stop, self._Error, **self._kwargs)
                # create worker thread for each connection
                th = threading.Thread(target=md.worker)
                th.start()
                self._threads.append(th)
                self._workers.append(md)

            # save the progress to the progress file
            if multithread:
                progress_file.write_text(json.dumps(self._dic, indent=4))

        self.downloaded = 0
        interval = 0.15
        self.download_mode = "Multi-Threaded" if multithread else "Single-Threaded"
        # use reprint library to print dynamic progress output
        with output(initial_len=5, interval=0) as dynamic_print:
            while True:
                if multithread:
                    # save progress to progress file
                    progress_file.write_text(json.dumps(self._dic, indent=4))
                # check if all workers have completed
                status = sum(i.completed for i in self._workers)
                # get the self.size amount of data self.downloaded
                self.downloaded = sum(i.curr for i in self._workers)
                # keep track of recent download speeds
                self._recent.append(self.downloaded)
                try:
                    # calculate download progress percentage
                    self.progress = int(100 * self.downloaded / self.size)
                except ZeroDivisionError:
                    self.progress = 0

                # calculate download speed
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
                    if multithread:
                        # save progress to progress file
                        progress_file.write_text(json.dumps(self._dic, indent=4))
                    break

                # check if all workers have completed
                if status == len(self._workers):
                    if multithread:
                        # combine the parts together
                        BLOCKSIZE = 4096
                        BLOCKS = 1024
                        CHUNKSIZE = BLOCKSIZE * BLOCKS
                        with open(filepath, "wb") as dest:
                            for i in range(num_connections):
                                file_ = f"{filepath}.{i}.part"
                                with open(file_, "rb") as f:
                                    while True:
                                        chunk = f.read(CHUNKSIZE)
                                        if chunk:
                                            dest.write(chunk)
                                        else:
                                            break
                                Path(file_).unlink()
                        # delete the progress file
                        progress_file.unlink()
                    break
                time.sleep(interval)

        ended = datetime.now()
        self.time_spent = (ended - started).total_seconds()

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
        num_connections: int = 10,
        display: bool = True,
        multithread: bool = True,
        block: bool = True,
        retries: int = 0,
        retry_func: Optional[Callable[[], str]] = None,
    ):
        """
        Start the download process.

        Parameters:
            url (str): The download URL.
            filepath (str): The optional file path to save the download. by default it uses the present working directory,
                If filepath is a directory then the file is self.downloaded into it else the file is self.downloaded with the given name.
            num_connections (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
            block (bool): Whether to block until the download is complete.
            retries (int): The number of times to retry the download in case of an error.
            retry_func (function): A function to call to get a new download URL in case of an error.
        """

        def start_thread():
            try:
                # start the download, not using "try" since all expected errors and will trigger error event
                self._download(url, filepath, num_connections, display, multithread)
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
                            _url, filepath, num_connections, display, multithread
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
