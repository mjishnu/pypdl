import json
import threading
import time
from collections import deque
from datetime import datetime
from math import inf
from pathlib import Path

import requests
from reprint import output
from utls import Multidown, Singledown, timestring


class Downloader:
    def __init__(self, StopEvent=threading.Event()):
        self._recent = deque([0] * 12, maxlen=12)  # keep track of recent download speed
        self._dic = {}  # dictionary to keep track of download progress
        self._workers = []  # list of download worker threads
        self._Error = threading.Event()  # event to signal any download errors

        # public attributes
        self.totalMB = 0  # total download size in MB
        self.progress = 0  # download progress percentage
        self.speed = 0  # download speed in MB/s
        self.download_mode = ''  # download mode: single-threaded or multi-threaded
        self.time_spent = None  # time spent downloading
        self.doneMB = 0  # amount of data downloaded in MB
        self.eta = '99:59:59'  # estimated time remaining for download completion
        self.remaining = 0  # amount of data remaining to be downloaded
        self.Stop = StopEvent  # event to signal download stop
        self.Failed = False  # flag to indicate if download failure

    def download(self, url, filepath, num_connections, display, multithread):
        json_file = Path(filepath + '.progress.json')  # progress file to keep track of download progress
        threads = []
        f_path = str(filepath)
        head = requests.head(url, timeout=20)  # get the header information for the file
        total = int(head.headers.get('content-length'))  # get the total size of the file from the header
        self.totalMB = total / 1048576  # 1MB = 1048576 bytes (size in MB)
        started = datetime.now()
        singlethread = False

        # adjust the number of connections for small files
        if self.totalMB < 50:
            num_connections = 5 if num_connections > 5 else num_connections

        # if no range available in header or no size from header use single thread
        if not total or not head.headers.get('accept-ranges') or not multithread:
            # create single threaded download object
            sd = Singledown()
            # create single download worker thread
            th = threading.Thread(target=sd.worker, args=(
                url, f_path, self.Stop, self._Error))
            self._workers.append(sd)
            th.start()
            total = inf if not total else total
            singlethread = True
        else:
            # multiple threads possible
            if json_file.exists():
                # load the progress from the progress file
                # the object_hook converts the key strings whose value is int to type int
                progress = json.loads(json_file.read_text(), object_hook=lambda d: {
                                      int(k) if k.isdigit() else k: v for k, v in d.items()})
            segment = total / num_connections
            self._dic['total'] = total
            self._dic['connections'] = num_connections
            self._dic['paused'] = False
            for i in range(num_connections):
                if not json_file.exists() or progress == {}:
                    # calculate the beginning byte offset by multiplying the segment by num_connections.
                    start = int(segment * i)
                    # here end is the ((segment * next part ) - 1 byte) since the last byte is downloaded by next part except for the last part
                    end = int(segment * (i + 1)) - (i != num_connections - 1)
                    curr = start
                    size = end - start + (i != num_connections - 1)
                else:
                    # use progress file to resume download
                    start = progress[i]['start']
                    end = progress[i]['end']
                    curr = progress[i]['curr']
                    size = progress[i]['size']

                self._dic[i] = {
                    'start': start,
                    'curr': curr,
                    'end': end,
                    'filepath': f'{filepath}.{i}.part',
                    'size': size,
                    'url': url,
                    'completed': False
                }
                # create multidownload object for each connection
                md = Multidown(self._dic, i, self.Stop, self._Error)
                # create worker thread for each connection
                th = threading.Thread(target=md.worker)
                threads.append(th)
                th.start()
                self._workers.append(md)

            # save the progress to the progress file
            json_file.write_text(json.dumps(self._dic, indent=4))

        downloaded = 0
        interval = 0.15
        self.download_mode = 'Multi-Threaded' if not singlethread else 'Single-Threaded'
        # use reprint library to print dynamic progress output
        with output(initial_len=5, interval=0) as dynamic_print:
            while True:
                # save progress to progress file
                json_file.write_text(json.dumps(self._dic, indent=4))
                # check if all workers have completed
                status = sum([i.completed for i in self._workers])
                # get the total amount of data downloaded
                downloaded = sum(i.curr for i in self._workers)
                self.doneMB = downloaded / 1048576
                # keep track of recent download speeds
                self._recent.append(downloaded)
                try:
                    # calculate download progress percentage
                    self.progress = int(100 * downloaded / total)
                except ZeroDivisionError:
                    self.progress = 0

                # calculate download speed
                gt0 = len([i for i in self._recent if i])
                if not gt0:
                    self.speed = 0
                else:
                    recent = list(self._recent)[12 - gt0:]
                    if len(recent) == 1:
                        self.speed = recent[0] / 1048576 / interval
                    else:
                        diff = [b - a for a, b in zip(recent, recent[1:])]
                        self.speed = sum(diff) / len(diff) / 1048576 / interval

                # calculate estimated time remaining for download completion
                self.remaining = self.totalMB - self.doneMB
                if self.speed and total != inf:
                    self.eta = timestring(self.remaining / self.speed)
                else:
                    self.eta = '99:59:59'

                # print dynamic progress output
                if display:
                    dynamic_print[0] = '[{0}{1}] {2}'.format('\u2588' * self.progress, '\u00b7' * (
                        100 - self.progress), str(self.progress)) + '%' if total != inf else "Downloading..."
                    dynamic_print[1] = f'Total: {self.totalMB:.2f} MB, Download Mode: {self.download_mode}, Speed: {self.speed :.2f} MB/s, ETA: {self.eta}'

                # check if download has been stopped or if an error has occurred
                if self.Stop.is_set() or self._Error.is_set():
                    self._dic['paused'] = True
                    json_file.write_text(json.dumps(self._dic, indent=4))
                    break

                # check if all workers have completed
                if status == len(self._workers):
                    if not singlethread:
                        # combine the parts together
                        BLOCKSIZE = 4096
                        BLOCKS = 1024
                        CHUNKSIZE = BLOCKSIZE * BLOCKS
                        with open(f_path, 'wb') as dest:
                            for i in range(num_connections):
                                file_ = f'{filepath}.{i}.part'
                                with open(file_, 'rb') as f:
                                    while True:
                                        chunk = f.read(CHUNKSIZE)
                                        if chunk:
                                            dest.write(chunk)
                                        else:
                                            break
                                Path(file_).unlink()
                    # delete the progress file
                    json_file.unlink()
                    break
                time.sleep(interval)

        ended = datetime.now()
        self.time_spent = (ended - started).total_seconds()

        # print download result
        if display:
            if self.Stop.is_set():
                print(f'Task interrupted!')
            print(f'Time elapsed: {timestring(self.time_spent)}')

    def stop(self):
        self.Stop.set()

    def start(self, url, filepath, num_connections=10, display=True, multithread=True, block=True, retries=0, retry_func=None):
        """
        Start the download process.

        Parameters:
            url (str): The download URL.
            filepath (str): The file path to save the download.
            num_connections (int): The number of connections to use for a multi-threaded download.
            display (bool): Whether to display download progress.
            multithread (bool): Whether to use multi-threaded download.
            block (bool): Whether to block until the download is complete.
            retries (int): The number of times to retry the download in case of an error.
            retry_func (function): A function to call to get a new download URL in case of an error.
        """
        def start_thread():
            try:
                # start the download
                self.download(url, filepath, num_connections,
                                display, multithread)
                # retry the download if there are errors
                for _ in range(retries):
                    if self._Error.is_set():
                        time.sleep(3)
                        # reset the downloader object
                        self.__init__(self.Stop)

                        # get a new download URL to retry
                        _url = url
                        if retry_func:
                            try:
                                _url = retry_func()
                            except Exception as e:
                                print(
                                    f"Retry function Error: ({e.__class__.__name__}, {e})")

                        if display:
                            print("retrying...")
                        # restart the download
                        self.download(_url, filepath, num_connections,
                                        display, multithread)
                    else:
                        break
            # if there's an error, set the error event and print the error message
            except Exception as e:
                print(f"Download Error: ({e.__class__.__name__}, {e})")
                self._Error.set()

            # if error flag is set, set the failed flag to True
            if self._Error.is_set():
                self.Failed = True
                print("Download Failed!")

        # Initialize the downloader with stop Event
        self.__init__(self.Stop)
        self.Stop.clear()
        # Start the download process in a new thread
        th = threading.Thread(target=start_thread)
        th.start()

        # Block the current thread until the download is complete, if necessary
        if block:
            th.join()