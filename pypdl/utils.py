import asyncio
import hashlib
import json
import logging
import sys
import time
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Union
from urllib.parse import unquote, urlparse

from aiofiles import open as fopen
from aiofiles import os

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


async def get_filepath(url: str, headers: Dict, file_path: str) -> str:
    content_disposition = headers.get("Content-Disposition", None)

    if content_disposition and "filename=" in content_disposition:
        filename_start = content_disposition.index("filename=") + len("filename=")
        filename = content_disposition[filename_start:]  # Get name from headers
        filename = unquote(filename.strip('"'))  # Decode URL encodings
    else:
        filename = unquote(urlparse(url).path.split("/")[-1])  # Generate name from URL

    filename = filename.replace("/", "_")

    if file_path:
        if await os.path.isdir(file_path):
            return os.path.join(file_path, filename)
        return file_path

    return filename


async def create_segment_table(
    url: str, file_path: str, segments: str, size: int, etag: str, etag_validation: bool
) -> Dict:
    """Create a segment table for multi-segment download."""
    progress_file = file_path + ".json"
    overwrite = True

    if await os.path.exists(progress_file):
        async with fopen(progress_file, "r") as f:
            progress = json.loads(await f.read())
            if not etag_validation or (
                progress["etag"]
                and (progress["url"] == url and progress["etag"] == etag)
            ):
                segments = progress["segments"]
                overwrite = False

    async with fopen(progress_file, "w") as f:
        await f.write(
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


async def combine_files(file_path: str, segments: int) -> None:
    """Combine the downloaded file segments into a single file."""
    async with fopen(file_path, "wb") as dest:
        for segment in range(segments):
            segment_file = f"{file_path}.{segment}"
            async with fopen(segment_file, "rb") as src:
                while True:
                    chunk = await src.read(CHUNKSIZE)
                    if chunk:
                        await dest.write(chunk)
                    else:
                        break

            await os.remove(segment_file)

    progress_file = Path(f"{file_path}.json")
    await os.remove(progress_file)


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


class Task:
    def __init__(
        self,
        multisegment,
        segments,
        tries,
        overwrite,
        etag_validation,
        size=0,
        **kwargs,
    ):
        self.url = None
        self.file_path = None
        self.multisegment = multisegment
        self.segments = segments
        self.tries = tries + 1
        self.overwrite = overwrite
        self.etag_validation = etag_validation
        self.size = size
        self.kwargs = kwargs

    def set(self, **kwargs):
        self.kwargs = {}
        for key, value in kwargs.items():
            if key == "retries":
                key = "tries"
                value = value + 1

            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.kwargs[key] = value

    def __repr__(self):
        return f"Task(url={self.url}, file_path={self.file_path}, tries={self.tries}, size={self.size})"


class TEventLoop:
    "A Threaded Eventloop"

    def __init__(self, executor: Executor):
        self.loop = asyncio.new_event_loop()
        executor.submit(self.loop.run_forever)

    def get(self) -> asyncio.AbstractEventLoop:
        return self.loop

    def call_soon_threadsafe(self, func, *args):
        return self.loop.call_soon_threadsafe(func, *args)

    def has_running_tasks(self) -> bool:
        tasks = asyncio.all_tasks(self.loop)
        return any(not task.done() for task in tasks)

    def clear_wait(self):
        while self.has_running_tasks():
            time.sleep(0.1)

    def stop(self, *args):
        self.clear_wait()
        self.call_soon_threadsafe(self.loop.stop)
        while self.loop.is_running():
            time.sleep(0.1)


class LoggingExecutor:
    """An Executor that logs exceptions."""

    def __init__(self, logger: logging.Logger, *args, **kwargs):
        self.executor = ThreadPoolExecutor(*args, **kwargs)
        self.logger = logger

    def submit(self, func: callable, *args, **kwargs):
        return self.executor.submit(self._wrap(func, *args, **kwargs))

    def shutdown(self):
        self.executor.shutdown()

    def _wrap(self, func, *args, **kwargs):
        def wrapper():
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.error(e)

        return wrapper


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
    """A Future object wrapper that shuts down the eventloop and executor when the result is retrieved."""

    def __init__(self, future: Future, loop: TEventLoop, executor: Executor):
        self.future = future
        self.executor = executor
        self.loop = loop

    def result(self, timeout: float = None) -> Union[[FileValidator, None], []]:
        result = self.future.result(timeout)
        self.loop.stop()
        self.executor.shutdown()
        return result


class EFuture:
    def __init__(self, future: Future, loop: TEventLoop):
        self.future = future
        self.loop = loop

    def result(self, timeout: float = None):
        return self.future.result(timeout)

    def _stop(self):
        self.loop.call_soon_threadsafe(self.future.cancel)
        try:
            self.result()
        except CancelledError:
            pass

        self.loop.clear_wait()


class ScreenCleaner:
    """A context manager to clear the screen and hide cursor."""

    def __init__(self, display: bool, clear_terminal: bool):
        self.display = display
        self.clear_terminal = clear_terminal

    def clear(self) -> None:
        sys.stdout.write(2 * "\n")
        if self.clear_terminal:
            sys.stdout.write("\033c")  # Clear screen
        sys.stdout.write("\x1b[?25l")  # Hide cursor
        sys.stdout.flush()

    def __enter__(self):
        if self.display:
            self.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.display:
            sys.stdout.write("\x1b[?25h")  # Show cursor
            sys.stdout.flush()
