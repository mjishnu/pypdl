import copy
import os
import threading
import time
from pathlib import Path
from typing import Dict
from urllib.parse import unquote, urlparse

import requests


def get_filename_from_headers(headers: Dict) -> str:
    content_disposition = headers.get("Content-Disposition")

    if content_disposition is not None and "filename=" in content_disposition:
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


class Basicdown:
    """
    Base downloader class.
    """

    def __init__(self, stop: threading.Event, error: threading.Event):
        self.curr = 0  # Downloaded size in bytes (current size)
        self.completed = 0
        self.id = 0
        self.stop = stop
        self.error = error

    def download(self, url: str, path: str, mode: str, **kwargs) -> None:
        """
        Download data in chunks.
        """
        try:
            with open(path, mode) as f:
                with requests.get(url, stream=True, timeout=20, **kwargs) as r:
                    for chunk in r.iter_content(1048576):  # chunk size = 1MB
                        if chunk:
                            f.write(chunk)
                            self.curr += len(chunk)
                        if not chunk or self.stop.is_set() or self.error.is_set():
                            break
        except Exception as e:
            self.error.set()
            time.sleep(1)
            print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")


class Singledown(Basicdown):
    """
    Class for downloading a whole file.
    """

    def __init__(
        self,
        url: str,
        path: str,
        stop: threading.Event,
        error: threading.Event,
        **kwargs,
    ):
        super().__init__(stop, error)
        self.url = url
        self.path = path
        self.kwargs = kwargs

    def worker(self) -> None:
        """
        Download a whole file in a single part.
        """
        self.download(self.url, self.path, mode="wb", **self.kwargs)
        self.completed = 1


class Multidown(Basicdown):
    """
    Class for downloading a specific part of a file.
    """

    def __init__(
        self,
        dic: Dict,
        id: int,
        stop: threading.Event,
        error: threading.Event,
        **kwargs,
    ):
        super().__init__(stop, error)
        self.id = id
        self.dic = dic
        self.kwargs = kwargs

    def worker(self) -> None:
        """
        Download a part of the file in multiple chunks.
        """
        url = self.dic["url"]
        path = Path(self.dic[self.id]["path"])
        start = self.dic[self.id]["start"]
        end = self.dic[self.id]["end"]
        size = self.dic[self.id]["size"]

        if path.exists():
            self.curr = path.stat().st_size
            start = start + self.curr

        kwargs = copy.deepcopy(self.kwargs)  # since it will be used by other threads
        kwargs.setdefault("headers", {}).update({"range": f"bytes={start}-{end}"})

        if self.curr > size:
            os.remove(path)
            self.error.set()
            print("corrupted file!")

        elif self.curr < size:
            self.download(url, path, "ab", **kwargs)

        if self.curr == size:
            self.completed = 1
