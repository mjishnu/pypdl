import hashlib
import json
import time
from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Dict, Union
from urllib.parse import unquote, urlparse

MEGABYTE = 1048576
BLOCKSIZE = 4096
BLOCKS = 1024
CHUNKSIZE = BLOCKSIZE * BLOCKS


def to_mb(size_in_bytes: int) -> float:
    return size_in_bytes / MEGABYTE


def seconds_to_hms(sec: float) -> str:
    time_struct = time.gmtime(sec)
    return time.strftime("%H:%M:%S", time_struct)


def get_filepath(url: str, headers: Dict, file_path: str) -> str:
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

    return filename


def create_segment_table(
    url: str, file_path: str, segments: str, size: int, etag: Union[str, bool]
) -> Dict:
    """Create a segment table for multi-threaded download."""
    progress_file = Path(file_path + ".json")

    if progress_file.exists():
        progress = json.loads(progress_file.read_text())
        if etag is True or (progress["url"] == url and progress["etag"] == etag):
            segments = progress["segments"]

    progress_file.write_text(
        json.dumps(
            {"url": url, "etag": etag, "segments": segments},
            indent=4,
        )
    )

    dic = {"url": url, "segments": segments}
    partition_size, add_bytes = divmod(size, segments)

    for segment in range(segments):
        start = partition_size * segment
        end = partition_size * (segment + 1) - 1

        if segment == segments - 1:
            end += add_bytes

        segment_size = end - start + 1  # since range is inclusive
        dic[segment] = {
            "start": start,
            "end": end,
            "segment_size": segment_size,
            "segment_path": f"{file_path}.{segment}",
        }

    return dic


def combine_files(file_path: str, segments: int) -> None:
    """Combine the downloaded file segments into a single file."""
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


class FileValidator:
    """A class used to validate the integrity of the file."""

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
    """A Future object wrapper that shuts down the executor when the result is retrieved."""

    def __init__(self, future: Future, executor: Executor):
        self.future = future
        self.executor = executor

    def result(self, timeout: float = None) -> Union[FileValidator, None]:
        result = self.future.result(timeout)
        self.executor.shutdown()
        return result
