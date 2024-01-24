import copy
import json
import threading
import time
from pathlib import Path
from typing import Dict, Union
from urllib.parse import unquote, urlparse

import requests

MEGABYTE = 1048576
BLOCKSIZE = 4096
BLOCKS = 1024
CHUNKSIZE = BLOCKSIZE * BLOCKS


def get_filepath(url: str, headers: Dict, file_path) -> str:
    content_disposition = headers.get("Content-Disposition", None)

    if content_disposition and "filename=" in content_disposition:
        filename_start = content_disposition.index("filename=") + len("filename=")
        filename = content_disposition[filename_start:]  # Get name from headers
        filename = unquote(filename.strip('"'))  # Decode URL encodings
    else:
        filename = unquote(urlparse(url).path.split("/")[-1])  # Generate name from url

    if file_path:
        file_path = Path(file_path)
        if file_path.is_dir():
            return str(file_path / filename)
        return str(file_path)
    else:
        return filename


def timestring(sec: int) -> str:
    """
    Converts seconds to a string formatted as HH:MM:SS.
    """
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def to_mb(size_in_bytes: int) -> float:
    return size_in_bytes / MEGABYTE


def create_segment_table(
    url: str, file_path: str, segments: str, size: int, etag: Union[str, bool]
) -> Dict:
    """
    Create a segment table for multi-threaded download.
    """
    segments = 5 if (segments > 5) and (to_mb(size) < 50) else segments
    progress_file = Path(file_path + ".json")

    try:
        progress = json.loads(progress_file.read_text())
        if etag and progress["url"] == url and progress["etag"] == etag:
            segments = progress["segments"]
    except Exception:
        pass

    progress_file.write_text(
        json.dumps(
            {"url": url, "etag": etag, "segments": segments},
            indent=4,
        )
    )

    dic = {"url": url, "segments": segments}
    partition_size = size / segments
    for segment in range(segments):
        start = int(partition_size * segment)
        end = int(partition_size * (segment + 1))
        segment_size = end - start
        if segment != (segments - 1):
            end -= 1  # [0-100, 100-200] -> [0-99, 100-200]
        # No segment_size+=1 for last setgment since final byte is end byte

        dic[segment] = {
            "start": start,
            "end": end,
            "segment_size": segment_size,
            "segment_path": f"{file_path }.{segment}.bin",
        }

    return dic


def combine_files(file_path: str, segments: int) -> None:
    """
    Combine the downloaded file segments into a single file.
    """
    with open(file_path, "wb") as dest:
        for i in range(segments):
            segment_file = f"{file_path }.{i}.bin"
            with open(segment_file, "rb") as src:
                while True:
                    chunk = src.read(CHUNKSIZE)
                    if chunk:
                        dest.write(chunk)
                    else:
                        break
            Path(segment_file).unlink()

    progress_file = Path(file_path + ".json")
    progress_file.unlink()


class Basicdown:
    """
    Base downloader class.
    """

    def __init__(self, interrupt: threading.Event):
        self.curr = 0  # Downloaded size in bytes (current size)
        self.completed = 0
        self.id = 0
        self.interrupt = interrupt

    def download(self, url: str, path: str, mode: str, **kwargs) -> None:
        """
        Download data in chunks.
        """
        try:
            with open(path, mode) as f:
                with requests.get(url, stream=True, **kwargs) as r:
                    for chunk in r.iter_content(MEGABYTE):
                        if chunk:
                            f.write(chunk)
                            self.curr += len(chunk)
                        if self.interrupt.is_set():
                            break

        except Exception as e:
            self.interrupt.set()
            time.sleep(1)
            print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")


class Simpledown(Basicdown):
    """
    Class for downloading the whole file in a single segment.
    """

    def __init__(
        self,
        url: str,
        file_path: str,
        interrupt: threading.Event,
        **kwargs,
    ):
        super().__init__(interrupt)
        self.url = url
        self.file_path = file_path
        self.kwargs = kwargs

    def worker(self) -> None:
        self.download(self.url, self.file_path, mode="wb", **self.kwargs)
        self.completed = 1


class Multidown(Basicdown):
    """
    Class for downloading a specific segment of the file.
    """

    def __init__(
        self,
        segement_table: Dict,
        segment_id: int,
        interrupt: threading.Event,
        **kwargs,
    ):
        super().__init__(interrupt)
        self.segment_id = segment_id
        self.segement_table = segement_table
        self.kwargs = kwargs

    def worker(self) -> None:
        url = self.segement_table["url"]
        segment_path = Path(self.segement_table[self.segment_id]["segment_path"])
        start = self.segement_table[self.segment_id]["start"]
        end = self.segement_table[self.segment_id]["end"]
        size = self.segement_table[self.segment_id]["segment_size"]

        if segment_path.exists():
            downloaded_size = segment_path.stat().st_size
            if downloaded_size > size:
                segment_path.unlink()
            else:
                self.curr = downloaded_size

        if self.curr < size:
            start = start + self.curr
            kwargs = copy.deepcopy(self.kwargs)  # since used by others
            kwargs.setdefault("headers", {}).update({"range": f"bytes={start}-{end}"})
            self.download(url, segment_path, "ab", **kwargs)

        if self.curr == size:
            self.completed = 1
