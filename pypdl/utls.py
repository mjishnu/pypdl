import copy
import hashlib
import json
import logging
import time
from concurrent.futures import Executor, Future
from pathlib import Path
from threading import Event
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


def seconds_to_hms(sec: float) -> str:
    time_struct = time.gmtime(sec)
    return time.strftime("%H:%M:%S", time_struct)


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
            "segment_path": f"{file_path }.{segment}",
        }

    return dic


def combine_files(file_path: str, segments: int) -> None:
    """
    Combine the downloaded file segments into a single file.
    """
    with open(file_path, "wb") as dest:
        for segment in range(segments):
            segment_file = f"{file_path}.{segment}"
            with open(segment_file, "rb") as src:
                while True:
                    chunk = src.read(CHUNKSIZE)
                    if chunk:
                        dest.write(chunk)
                    else:
                        break
            Path(segment_file).unlink()

    progress_file = Path(f"{file_path}.json")
    progress_file.unlink()


class Basicdown:
    """
    Base downloader class.
    """

    def __init__(self, interrupt: Event):
        self.curr = 0  # Downloaded size in bytes (current size)
        self.completed = False
        self.id = 0
        self.interrupt = interrupt
        self.downloaded = 0

    def download(self, url: str, path: str, mode: str, **kwargs) -> None:
        """
        Download data in chunks.
        """
        try:
            with open(path, mode) as file, requests.get(
                url, stream=True, **kwargs
            ) as response:
                for chunk in response.iter_content(MEGABYTE):
                    file.write(chunk)
                    self.curr += len(chunk)
                    self.downloaded += len(chunk)

                    if self.interrupt.is_set():
                        break

        except Exception as e:
            self.interrupt.set()
            time.sleep(1)
            logging.error(f"(Thread: {self.id}) [{e.__class__.__name__}: {e}]")


class Simpledown(Basicdown):
    """
    Class for downloading the whole file in a single segment.
    """

    def __init__(
        self,
        url: str,
        file_path: str,
        interrupt: Event,
        **kwargs,
    ):
        super().__init__(interrupt)
        self.url = url
        self.file_path = file_path
        self.kwargs = kwargs

    def worker(self) -> None:
        self.download(self.url, self.file_path, mode="wb", **self.kwargs)
        self.completed = True


class Multidown(Basicdown):
    """
    Class for downloading a specific segment of the file.
    """

    def __init__(
        self,
        segement_table: Dict,
        segment_id: int,
        interrupt: Event,
        **kwargs,
    ):
        super().__init__(interrupt)
        self.id = segment_id
        self.segement_table = segement_table
        self.kwargs = kwargs

    def worker(self) -> None:
        url = self.segement_table["url"]
        segment_path = Path(self.segement_table[self.id]["segment_path"])
        start = self.segement_table[self.id]["start"]
        end = self.segement_table[self.id]["end"]
        size = self.segement_table[self.id]["segment_size"]

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
            self.completed = True


class FileValidator:
    """
    A class used to validate the integrity of the file.
    """

    def __init__(self, path: str):
        self.path = path

    def calculate_hash(self, algorithm: str, **kwargs) -> str:
        hash_obj = hashlib.new(algorithm, **kwargs)
        with open(self.path, "rb") as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def validate_hash(self, correct_hash: str, algorithm: str, **kwargs) -> bool:
        file_hash = self.calculate_hash(algorithm, **kwargs)
        return file_hash == correct_hash


class AutoShutdownFuture:
    """
    A Future object wrapper that shuts down the executor when the result is retrieved.
    """

    def __init__(self, future: Future, executor: Executor):
        self.future = future
        self.executor = executor

    def result(self, timeout: float = None) -> Union[FileValidator, None]:
        result = self.future.result(timeout)
        self.executor.shutdown()
        return result

    def done(self) -> bool:
        return self.future.done()
