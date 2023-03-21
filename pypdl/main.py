import json
import threading
import time
from collections import deque
from datetime import datetime
from math import inf
from pathlib import Path

import requests
from reprint import output
from .utls import Multidown, Singledown, timestring


class Downloader:
    def __init__(self, StopEvent=threading.Event()):
        self._recent = deque([0] * 12, maxlen=12)
        self._dic = {}
        self._workers = []
        self._Error = threading.Event()

        # attributes
        self.totalMB = 0
        self.progress = 0
        self.speed = 0
        self.download_mode = ''
        self.time_spent = None
        self.doneMB = 0
        self.eta = '99:59:59'
        self.remaining = 0
        self.Stop = StopEvent
        self.Failed = False

    def download(self, url, filepath, num_connections, display, multithread):
        json_file = Path(filepath + '.progress.json')
        threads = []
        f_path = str(filepath)
        head = requests.head(url, timeout=20)
        total = int(head.headers.get('content-length'))
        self.totalMB = total / 1048576  # 1MB = 1048576 bytes (size in MB)
        started = datetime.now()
        singlethread = False

        if self.totalMB < 50:
            num_connections = 5 if num_connections > 5 else num_connections
        # if no range avalable in header or no size from header use single thread
        if not total or not head.headers.get('accept-ranges') or not multithread:
            sd = Singledown()
            th = threading.Thread(target=sd.worker, args=(
                url, f_path, self.Stop, self._Error))
            self._workers.append(sd)
            th.start()
            total = inf if not total else total
            singlethread = True
        else:
            # multiple threads possible
            if json_file.exists():
                # the object_hook converts the key strings whose value is int to type int
                progress = json.loads(json_file.read_text(), object_hook=lambda d: {
                                      int(k) if k.isdigit() else k: v for k, v in d.items()})
            segment = total / num_connections
            self._dic['total'] = total
            self._dic['connections'] = num_connections
            self._dic['paused'] = False
            for i in range(num_connections):
                if not json_file.exists() or progress == {}:
                    # get the starting byte size by multiplying the segment by the part number eg 1024 * 2 = part2 beginning byte etc.
                    start = int(segment * i)
                    # here end is the ((segment * next part ) - 1 byte) since the last byte is also downloaded by next part
                    # here (i != num_connections - 1) since we don't want to do this 1 byte subtraction for last part (index is from 0)
                    end = int(segment * (i + 1)) - (i != num_connections - 1)
                    position = start
                    length = end - start + (i != num_connections - 1)
                else:
                    start = progress[i]['start']
                    end = progress[i]['end']
                    position = progress[i]['position']
                    length = progress[i]['length']

                self._dic[i] = {
                    'start': start,
                    'position': position,
                    'end': end,
                    'filepath': f'{filepath}.{i}.part',
                    'count': 0,
                    'length': length,
                    'url': url,
                    'completed': False
                }
                md = Multidown(self._dic, i, self.Stop, self._Error)
                th = threading.Thread(target=md.worker)
                threads.append(th)
                th.start()
                self._workers.append(md)

            json_file.write_text(json.dumps(self._dic, indent=4))
        downloaded = 0
        interval = 0.15
        self.download_mode = 'Multi-Threaded' if not singlethread else 'Single-Threaded'
        with output(initial_len=5, interval=0) as dynamic_print:
            while True:
                json_file.write_text(json.dumps(self._dic, indent=4))
                status = sum([i.completed for i in self._workers])
                downloaded = sum(i.count for i in self._workers)
                self.doneMB = downloaded / 1048576
                self._recent.append(downloaded)
                try:
                    self.progress = int(100 * downloaded / total)
                except ZeroDivisionError:
                    self.progress = 0

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

                self.remaining = self.totalMB - self.doneMB
                if self.speed and total != inf:
                    self.eta = timestring(self.remaining / self.speed)
                else:
                    self.eta = '99:59:59'

                if display:
                    dynamic_print[0] = '[{0}{1}] {2}'.format('\u2588' * self.progress, '\u00b7' * (
                        100 - self.progress), str(self.progress)) + '%' if total != inf else "Downloading..."
                    dynamic_print[1] = f'Total: {self.totalMB:.2f} MB, Download Mode: {self.download_mode}, Speed: {self.speed :.2f} MB/s, ETA: {self.eta}'

                if self.Stop.is_set() or self._Error.is_set():
                    self._dic['paused'] = True
                    json_file.write_text(json.dumps(self._dic, indent=4))
                    break

                if status == len(self._workers):
                    if not singlethread:
                        BLOCKSIZE = 4096
                        BLOCKS = 1024
                        CHUNKSIZE = BLOCKSIZE * BLOCKS
                        # combine the parts together
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
                    json_file.unlink()
                    if display:
                        print('Task completed!')
                    break
                time.sleep(interval)

        ended = datetime.now()
        self.time_spent = (ended - started).total_seconds()

        if display:
            if self.Stop:
                print(f'Task interrupted!')
            print(f'Time elapsed: {timestring(self.time_spent)}')

    def stop(self):
        self.Stop.set()

    def start(self, url, filepath, num_connections=10, display=True, multithread=True, block=True, retries=0, retry_func=None):

        def start_thread():
            try:
                self.download(url, filepath, num_connections,
                              display, multithread)
                for _ in range(retries):
                    if self._Error.is_set():
                        time.sleep(3)
                        self.__init__(self.Stop)

                        _url = url
                        if retry_func:
                            try:
                                _url = retry_func()
                            except Exception as e:
                                print(
                                    f"Retry function Error: ({e.__class__.__name__}, {e})")

                        if display:
                            print("retrying...")
                        self.download(_url, filepath, num_connections,
                                      display, multithread)
                    else:
                        break
            except Exception as e:
                print(f"Download Error: ({e.__class__.__name__}, {e})")
                self._Error.set()

            if self._Error.is_set():
                self.Failed = True
                print("Download Failed!")

        self.__init__(self.Stop)
        self.Stop.clear()
        th = threading.Thread(target=start_thread)
        th.start()

        if block:
            th.join()
