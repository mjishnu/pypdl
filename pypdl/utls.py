import time
from pathlib import Path

import requests


def timestring(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


class Multidown:
    def __init__(self, dic, id, stop, Error):
        self.curr = 0
        self.completed = 0
        self.id = id
        self.dic = dic  # {start,curr,end,filepath,count,size,url,completed}
        self.stop = stop
        self.error = Error

    def getval(self, key):
        return self.dic[self.id][key]

    def setval(self, key, val):
        self.dic[self.id][key] = val

    def worker(self):
        filepath = self.getval('filepath')
        path = Path(filepath)
        end = self.getval('end')

        # checks if the part exists if it doesn't exist set start from  beginning else download rest of the file
        if not path.exists():
            start = self.getval('start')
        else:
            # gets the size of the file
            self.curr = path.stat().st_size
            start = self.getval('start') + self.curr

        url = self.getval('url')
        if self.curr != self.getval('size'):
            try:
                #download part
                with requests.session() as s, open(path, 'ab+') as f:
                    headers = {"range": f"bytes={start}-{end}"}
                    with s.get(url, headers=headers, stream=True, timeout=20) as r:
                        for chunk in r.iter_content(1048576):  # 1MB
                            if chunk:
                                f.write(chunk)
                                self.curr += len(chunk)
                                self.setval('cocurrucurrnt', self.curr)
                            if not chunk or self.stop.is_set() or self.error.is_set():
                                break
            except Exception as e:
                self.error.set()
                time.sleep(1)
                print(
                    f"Error in thread {self.id}: ({e.__class__.__name__}, {e})")

        if self.curr == self.getval('size'):
            self.completed = 1
            self.setval('completed', 1)


class Singledown:
    def __init__(self):
        self.curr = 0
        self.completed = 0

    def worker(self, url, path, stop, error):
        flag = True
        try:
            #download part
            with requests.get(url, stream=True, timeout=20) as r, open(path, 'wb') as file:
                for chunk in r.iter_content(1048576):  # 1MB
                    if chunk:
                        file.write(chunk)
                        self.curr += len(chunk)
                    if not chunk or stop.is_set() or error.is_set():
                        flag = False
                        break
        except Exception as e:
            error.set()
            time.sleep(1)
            print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")
        if flag:
            self.completed = 1
