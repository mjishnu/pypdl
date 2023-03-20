import json
import time
from collections import deque
from datetime import datetime
from math import inf
from pathlib import Path
import threading
import requests
from reprint import output


def timestring(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


class Multidown:
    def __init__(self, dic, id, stop, Error):
        self.count = 0
        self.completed = 0
        # used to differniate between diffent instance of multidown class
        self.id = id
        # the dic is filled with data from the json {start,position,end,filepath,count,length,url,completed}
        # the json also has info like total bytes,number of connections (parts)
        self.dic = dic
        self.position = self.getval('position')
        self.stop = stop
        self.Error = Error

    def getval(self, key):
        return self.dic[self.id][key]

    def setval(self, key, val):
        self.dic[self.id][key] = val

    def worker(self):
        # getting the path(file_name/file) from the json file (dict)
        filepath = self.getval('filepath')
        path = Path(filepath)
        end = self.getval('end')
        # checks if the part exists if it doesn't exist set start from the json file(download from beginning) else download beginning from size of the file
        if not path.exists():
            start = self.getval('start')
        else:
            # gets the size of the file
            self.count = path.stat().st_size
            start = self.getval('start') + self.count
        url = self.getval('url')
        self.position = start
        with open(path, 'ab+') as f:
            if self.count != self.getval('length'):
                try:
                    s = requests.Session()
                    r = s.get(
                        url, headers={"range": f"bytes={start}-{end}"}, stream=True)
                    while True:
                        if self.stop.is_set():
                            r.connection.close()
                            r.close()
                            s.close()
                            break
                        # the next returns the next element form the iterator of r(the request we send to dowload) and returns None if the iterator is exhausted
                        chunk = next(r.iter_content(128 * 1024), None)
                        if chunk:
                            f.write(chunk)
                            self.count += len(chunk)
                            self.position += len(chunk)
                            self.setval('count', self.count)
                            self.setval('position', self.position)
                        else:
                            break   
                except Exception as e:
                    self.stop.set()
                    self.Error.set()
                    time.sleep(1)
                    print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")
        # self.count is the length of current download if its equal to the size of the part we need to download them mark as downloaded
        if self.count == self.getval('length'):
            self.completed = 1
            self.setval('completed', 1)


class Singledown:
    def __init__(self):
        self.count = 0
        self.completed = 0

    def worker(self, url, path,stop,Error):
        try:
            with requests.get(url, stream=True) as r, open(path, 'wb') as file:
                for chunk in r.iter_content(1048576):  # 1MB
                    if chunk:
                        self.count += len(chunk)
                        file.write(chunk)
                    if stop.is_set():
                        return
        except Exception as e:
            stop.set()
            Error.set()
            time.sleep(1)
            print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")

        self.completed = 1


class Downloader:
    def __init__(self):
        self.recent = deque([0] * 12, maxlen=12)
        self.dic = {}
        self.workers = []
        self.signal = threading.Event() #stop signal
        self.Error = threading.Event()

        self.totalMB = 0
        self.progress = 0
        self.speed = 0
        self.download_mode = ''
        self.time_spent = None
        self.doneMB = 0
        self.eta = '99:59:59'
        self.remaining = 0

    def download(self, url, filepath, num_connections, display):
        json_file = Path(filepath + '.progress.json')
        threads = []
        f_path = str(filepath)
        head = requests.head(url)
        total = int(head.headers.get('content-length'))
        self.totalMB = total / 1048576  # 1MB = 1048576 bytes (size in MB)
        started = datetime.now()
        singlethread = False

        if self.totalMB < 50:
            num_connections = 5
        # if no range avalable in header or no size from header use single thread
        if not total or not head.headers.get('accept-ranges'):
            sd = Singledown()
            th = threading.Thread(target=sd.worker, args=(url, f_path,self.signal,self.Error))
            th.daemon = True
            self.workers.append(sd)
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
            self.dic['total'] = total
            self.dic['connections'] = num_connections
            self.dic['paused'] = False
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

                self.dic[i] = {
                    'start': start,
                    'position': position,
                    'end': end,
                    'filepath': f'{filepath}.{i}.part',
                    'count': 0,
                    'length': length,
                    'url': url,
                    'completed': False
                }
                md = Multidown(self.dic, i, self.signal,self.Error)
                th = threading.Thread(target=md.worker)
                threads.append(th)
                th.start()
                self.workers.append(md)

            json_file.write_text(json.dumps(self.dic, indent=4))
        downloaded = 0
        interval = 0.15
        self.download_mode = 'Multi-Threaded' if not singlethread else 'Single-Threaded'
        with output(initial_len=5, interval=0) as dynamic_print:
            while True:
                json_file.write_text(json.dumps(self.dic, indent=4))
                status = sum([i.completed for i in self.workers])
                downloaded = sum(i.count for i in self.workers)
                self.doneMB = downloaded / 1048576
                self.recent.append(downloaded)
                try:
                    self.progress = int(100 * downloaded / total)
                except ZeroDivisionError:
                    self.progress = 0

                gt0 = len([i for i in self.recent if i])
                if not gt0:
                    self.speed = 0
                else:
                    recent = list(self.recent)[12 - gt0:]
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
                    dynamic_print[0] = '[{0}{1}] {2}'.format('\u2588' * self.progress, '\u00b7' * (100 - self.progress), str(self.progress)) + '%' if total != inf else "Downloading..."
                    dynamic_print[1] = f'Total: {self.totalMB:.2f} MB, Download Mode: {self.download_mode}, Speed: {self.speed :.2f} MB/s, ETA: {self.eta}'

                if self.signal.is_set():
                    self.dic['paused'] = True
                    json_file.write_text(json.dumps(self.dic, indent=4))
                    if singlethread:
                        print("Download wont be resumed in single thread mode")
                    break

                if status == len(self.workers):
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
                    break
                time.sleep(interval)

        ended = datetime.now()
        self.time_spent = (ended - started).total_seconds()
        if status == len(self.workers):
            if display:
                print(f'Task completed, total time elapsed: {timestring(self.time_spent)}')
            json_file.unlink()
        else:
            if self.Error.is_set():
                print("Download Error Occured!")
                return 
            if display:
                print(f'Task interrupted, time elapsed: {timestring(self.time_spent)}')

    def stop(self):
        self.signal.set()

    def start(self, url, filepath, num_connections=3 ,display=True,block=True,retries=0, retry_func=None):
        
        def inner():
            self.download(url, filepath, num_connections, display)   
            for _ in range(retries):  
                if self.Error.is_set():
                    time.sleep(3)
                    self.__init__()
                    if display:
                        print("retrying...")
                    self.download(url, filepath, num_connections, display)
                else:
                    break

        th = threading.Thread(target=inner)
        th.start()
        if block:
            th.join()
        

if __name__ == '__main__':
    d = Downloader()
    url = "https://gamedownloads.rockstargames.com/public/installer/Rockstar-Games-Launcher.exe"
    d.start(url,"dfd.exe",2,True,True)
    print("hello")
    # th = threading.Thread(target=d.start, args=(url,"dfd.exe",2))
    # th.start()
    # while True:
    #     print(d.progress,d.speed,d.eta,d.doneMB,d.totalMB,d.remaining,d.time_spent,d.download_mode)
    #     time.sleep(1)
    # time.sleep(2)
    # d.Error.set()
    # d.stop()
    # time.sleep(4)
    # d.Error.set()
    # d.stop()
    # print("stoped 2")
    # time.sleep(3)
    # d.Error.set()
    # d.stop()
    # print("stoped 3")
    
