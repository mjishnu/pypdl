import os
import threading
import time
import copy
from pathlib import Path
from typing import Any, Dict
from urllib.parse import unquote, urlparse

import requests


def get_filename_from_headers(headers: Dict) -> str:
    content_disposition = headers.get("Content-Disposition")

    if content_disposition and "filename=" in content_disposition:
        filename_start = content_disposition.index("filename=") + len("filename=")
        filename = content_disposition[filename_start:]
        filename = filename.strip(' "')
        filename = unquote(filename)  # Decode URL encoding
        return filename
    return None


def get_filename_from_url(url: str) -> str:
    filename = unquote(urlparse(url).path.split("/")[-1])
    return filename


def timestring(sec: int) -> str:
    """
    Converts seconds to a string formatted as HH:MM:SS.
    """

    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Multidown:
    """
    Class for downloading a specific part of a file in multiple chunks.
    """

    def __init__(
        self,
        dic: Dict,
        id: int,
        stop: threading.Event,
        error: threading.Event,
        **kwargs,
    ):
        self.curr = 0  # current size of downloaded part
        self.completed = 0
        self.id = id
        self.dic = dic  # {start, curr, end, filepath, size, url, completed}
        self.stop = stop
        self.error = error
        self.kwargs = kwargs  # Request Module kwargs

    def getval(self, key: str) -> Any:
        return self.dic[self.id][key]

    def setval(self, key: str, val: Any):
        self.dic[self.id][key] = val

    def worker(self):
        """
        Download a part of the file in multiple chunks.
        """

        filepath = self.getval("filepath")
        path = Path(filepath)
        end = self.getval("end")

        # checks if the part exists, if it doesn't exist set start from the beginning, else download the rest of the file
        if not path.exists():
            start = self.getval("start")
        else:
            # gets the size of the file
            self.curr = path.stat().st_size
            # add the old start size and the current size to get the new start size
            start = self.getval("start") + self.curr
            # corruption check to make sure parts are not corrupted
            if start > end:
                os.remove(path)
                self.error.set()
                print("corrupted file!")

        url = self.getval("url")
        # not updating self.kwargs because it will reference the orginal headers dict and will cause wrong range
        kwargs = copy.deepcopy(self.kwargs)
        range_header = {"range": f"bytes={start}-{end}"}
        kwargs.setdefault("headers", {}).update(range_header)

        if self.curr != self.getval("size"):
            try:
                # download part
                with requests.session() as s, open(path, "ab+") as f:
                    with s.get(
                        url,
                        stream=True,
                        timeout=20,
                        **kwargs,
                    ) as r:
                        for chunk in r.iter_content(1048576):  # 1MB
                            if chunk:
                                f.write(chunk)
                                self.curr += len(chunk)
                                self.setval("curr", self.curr)
                            if not chunk or self.stop.is_set() or self.error.is_set():
                                break
            except Exception as e:
                self.error.set()
                time.sleep(1)
                print(f"Error in thread {self.id}: ({e.__class__.__name__}, {e})")

        if self.curr == self.getval("size"):
            self.completed = 1
            self.setval("completed", 1)


class Singledown:
    """
    Class for downloading a whole file in a single chunk.
    """

    def __init__(
        self,
        url: str,
        path: str,
        stop: threading.Event,
        error: threading.Event,
        **kwargs,
    ):
        self.curr = 0  # current size of downloaded file
        self.completed = 0  # whether the download is complete
        self.url = url  # url of the file
        self.path = path  # path to save the file
        self.stop = stop  # event to stop the download
        self.error = error  # event to indicate an error occurred
        self.kwargs = kwargs  # user kwargs

    def worker(self):
        """
        Download a whole file in a single chunk.
        """
        flag = True
        try:
            # download part
            with requests.get(
                self.url, stream=True, timeout=20, **self.kwargs
            ) as r, open(self.path, "wb") as file:
                for chunk in r.iter_content(1048576):  # 1MB
                    if chunk:
                        file.write(chunk)
                        self.curr += len(chunk)
                    if not chunk or self.stop.is_set() or self.error.is_set():
                        flag = False
                        break
        except Exception as e:
            self.error.set()
            time.sleep(1)
            print(f"Error in download thread: ({e.__class__.__name__}: {e})")
        if flag:
            self.completed = 1
