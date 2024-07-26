import hashlib
import json
import logging
import sys
import time
from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Dict, List, Union
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


def cursor_up() -> None:
    sys.stdout.write("\x1b[1A" * 2)  # Move cursor up two lines
    sys.stdout.flush()


def get_filepath(url: str, headers: Dict, file_path: str) -> str:
    content_disposition = headers.get("Content-Disposition", None)

    if content_disposition and "filename=" in content_disposition:
        filename_start = content_disposition.index("filename=") + len("filename=")
        filename = content_disposition[filename_start:]  # Get name from headers
        filename = unquote(filename.strip('"'))  # Decode URL encodings
    else:
        filename = unquote(urlparse(url).path.split("/")[-1])  # Generate name from URL

    filename = filename.replace("/", "_")

    if file_path:
        file_path = Path(file_path)
        if file_path.is_dir():
            return str(file_path / filename)
        return str(file_path)

    return filename


def create_segment_table(
    url: str, file_path: str, segments: str, size: int, etag: Union[str, bool]
) -> Dict:
    """Create a segment table for multi-segment download."""
    progress_file = Path(file_path + ".json")
    overwrite = True

    if progress_file.exists():
        progress = json.loads(progress_file.read_text())

        if (etag is True) or (
            progress["etag"] and (progress["url"] == url and progress["etag"] == etag)
        ):
            segments = progress["segments"]
            overwrite = False

    progress_file.write_text(
        json.dumps(
            {"url": url, "etag": etag, "segments": segments},
            indent=4,
        )
    )

    dic = {"url": url, "segments": segments, "overwrite": overwrite}
    partition_size, add_bytes = divmod(size, segments)

    for segment in range(segments):
        start = partition_size * segment
        end = partition_size * (segment + 1) - 1  # since range is inclusive

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


def default_logger(name: str) -> logging.Logger:
    """Creates a default debugging logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.ERROR)
    handler = logging.FileHandler("pypdl.log", mode="a", delay=True)
    handler.setFormatter(
        logging.Formatter(
            "(%(name)s)  %(asctime)s - %(levelname)s: %(message)s",
            datefmt="%d-%m-%y %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


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
    """A Future object wrapper that shuts down the executors when the result is retrieved."""

    def __init__(self, future: Future, executors: List[Executor]):
        self.future = future
        self.executors = executors

    def result(self, timeout: float = None) -> Union[FileValidator, None]:
        result = self.future.result(timeout)
        for executor in self.executors:
            executor.shutdown()
        return result


class ScreenCleaner:
    """A context manager to clear the screen and hide cursor."""

    def __init__(self, display: bool):
        self.display = display

    def clear(self) -> None:
        sys.stdout.write("\033c")  # Clear screen
        sys.stdout.write("\x1b[?25l")  # Hide cursor

    def __enter__(self):
        if self.display:
            self.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.display:
            sys.stdout.write("\x1b[?25h")  # Show cursor
