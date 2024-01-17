import copy
import os
import threading
import time
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
        filename = unquote(filename)  # Decode URL encodings
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
        self.curr = 0  # Downloaded size in bytes
        self.completed = 0
        self.id = id
        self.dic = dic
        self.url = dic["url"]
        self.stop = stop
        self.error = error
        self.kwargs = kwargs  # Request Module kwargs

    def getval(self, key: str) -> Any:
        return self.dic[self.id][key]  # {start, end, path, size}

    def setval(self, key: str, val: Any) -> None:
        self.dic[self.id][key] = val

    def worker(self) -> None:
        """
        Download a part of the file in multiple chunks.
        """
        start = self.getval("start")
        end = self.getval("end")
        path = Path(self.getval("path"))
        size = self.getval("size")

        if path.exists():
            self.curr = path.stat().st_size
            start = start + self.curr
            if self.curr > size:
                os.remove(path)
                self.error.set()
                print("corrupted file!")

        kwargs = copy.deepcopy(self.kwargs)  # since it will be used by other threads
        kwargs.setdefault("headers", {}).update({"range": f"bytes={start}-{end}"})
        if self.curr != size:
            try:
                with open(path, "ab+") as f:
                    with requests.get(self.url, stream=True, timeout=20, **kwargs) as r:
                        for chunk in r.iter_content(1048576):  # chunk size = 1MB
                            if chunk:
                                f.write(chunk)
                                self.curr += len(chunk)
                            if not chunk or self.stop.is_set() or self.error.is_set():
                                break
            except Exception as e:
                self.error.set()
                time.sleep(1)
                print(f"Error in thread {self.id}: ({e.__class__.__name__}, {e})")
        if self.curr == size:
            self.completed = 1


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
        self.curr = 0  # Downloaded size in bytes
        self.completed = 0
        self.url = url
        self.path = path
        self.stop = stop
        self.error = error
        self.kwargs = kwargs  # Request Module kwargs

    def worker(self) -> None:
        """
        Download a whole file in a single part.
        """
        try:
            with open(self.path, "ab+") as f:
                with requests.get(
                    self.url, stream=True, timeout=20, **self.kwargs
                ) as r:
                    for chunk in r.iter_content(1048576):  # chunk size = 1MB
                        if chunk:
                            f.write(chunk)
                            self.curr += len(chunk)
                        if not chunk or self.stop.is_set() or self.error.is_set():
                            break
        except Exception as e:
            self.error.set()
            time.sleep(1)
            print(f"Error in download thread: ({e.__class__.__name__}: {e})")
        self.completed = 1
