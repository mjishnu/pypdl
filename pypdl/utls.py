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
                    print(
                        f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")
        # self.count is the length of current download if its equal to the size of the part we need to download them mark as downloaded
        if self.count == self.getval('length'):
            self.completed = 1
            self.setval('completed', 1)


class Singledown:
    def __init__(self):
        self.count = 0
        self.completed = 0

    def worker(self, url, path, stop, Error):
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
