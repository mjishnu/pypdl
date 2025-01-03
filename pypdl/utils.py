import asyncio
import hashlib
import json
import logging
import sys
import time
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Union, List, Optional, Callable, Tuple
from urllib.parse import unquote, urlparse
from threading import Thread

from aiofiles import open as fopen
from aiofiles import os

MEGABYTE = 1048576
BLOCKSIZE = 4096
BLOCKS = 1024
CHUNKSIZE = BLOCKSIZE * BLOCKS


class Task:
    def __init__(
        self,
        multisegment: bool,
        segments: int,
        tries: int,
        overwrite: bool,
        speed_limit: Union[float, int],
        etag_validation: bool,
        **kwargs,
    ):
        self.url = None
        self.file_path = None
        self.multisegment = multisegment
        self.segments = segments
        self.tries = tries + 1
        self.overwrite = overwrite
        self.speed_limit = speed_limit
        self.etag_validation = etag_validation
        self.size = Size(0, 0)
        self.kwargs = kwargs if kwargs else {}

    def set(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if key == "retries":
                key = "tries"
                value = value + 1

            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.kwargs[key] = value
        self.validate()

    def validate(self) -> None:
        if not (isinstance(self.url, str) or callable(self.url)):
            raise TypeError(
                f"url should be of type str or callable, got {type(self.url).__name__}"
            )

        if not isinstance(self.file_path, str):
            raise TypeError(
                f"file_path should be of type str, got {type(self.file_path).__name__}"
            )
        if not isinstance(self.multisegment, bool):
            raise TypeError(
                f"multisegment should be of type bool, got {type(self.multisegment).__name__}"
            )
        if not isinstance(self.segments, int):
            raise TypeError(
                f"segments should be of type int, got {type(self.segments).__name__}"
            )
        if not isinstance(self.tries, int):
            raise TypeError(
                f"tries should be of type int, got {type(self.tries).__name__}"
            )
        if not isinstance(self.overwrite, bool):
            raise TypeError(
                f"overwrite should be of type bool, got {type(self.overwrite).__name__}"
            )
        if not isinstance(self.speed_limit, (float, int)):
            raise TypeError(
                f"speed_limit should be of type float or int, got {type(self.speed_limit).__name__}"
            )
        if not isinstance(self.etag_validation, bool):
            raise TypeError(
                f"etag_validation should be of type bool, got {type(self.etag_validation).__name__}"
            )

    def __repr__(self) -> str:
        return f"Task(url={self.url}, file_path={self.file_path}, tries={self.tries}, size={self.size})"


class Size:
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end
        self.value = end - start + 1  # since range is inclusive[0-99 -> 100]

    def __repr__(self) -> str:
        return str(self.value)


class TEventLoop:
    """A Threaded Eventloop"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run, daemon=False)
        self._thread.start()

    def _run(self) -> None:
        self.loop.run_forever()
        self.loop.close()

    def get(self) -> asyncio.AbstractEventLoop:
        return self.loop

    def call_soon_threadsafe(self, func, *args) -> None:
        return self.loop.call_soon_threadsafe(func, *args)

    def has_running_tasks(self) -> bool:
        tasks = asyncio.all_tasks(self.loop)
        return any(not task.done() for task in tasks)

    def clear_wait(self) -> None:
        while self.has_running_tasks():
            time.sleep(0.1)

    def stop(self, *args) -> None:
        self.clear_wait()
        self.call_soon_threadsafe(self.loop.stop)
        self._thread.join()


class LoggingExecutor:
    """An Executor that logs exceptions."""

    def __init__(self, logger: logging.Logger, *args, **kwargs):
        self.executor = ThreadPoolExecutor(*args, **kwargs)
        self.logger = logger

    def submit(self, func: Callable, *args, **kwargs) -> Future:
        return self.executor.submit(self._wrap(func, *args, **kwargs))

    def shutdown(self) -> None:
        self.executor.shutdown()

    def _wrap(self, func: Callable, *args, **kwargs) -> Callable:
        def wrapper():
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.exception(e)

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

    def result(
        self, timeout: Optional[float] = None
    ) -> Union[List[FileValidator], None]:
        result = self.future.result(timeout)
        self.loop.stop()
        self.executor.shutdown()
        return result


class EFuture:
    """A Future object wrapper that cancels the future and clears the eventloop when stopped."""

    def __init__(self, future: Future, loop: TEventLoop):
        self.future = future
        self.loop = loop

    def result(
        self, timeout: Optional[float] = None
    ) -> Union[List[FileValidator], None]:
        return self.future.result(timeout)

    def _stop(self) -> None:
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


def to_mb(size_in_bytes: int) -> float:
    return size_in_bytes / MEGABYTE


def seconds_to_hms(sec: float) -> str:
    if sec == -1:
        return "99:59:59"
    time_struct = time.gmtime(sec)
    return time.strftime("%H:%M:%S", time_struct)


def cursor_up() -> None:
    sys.stdout.write("\x1b[1A" * 2)  # Move cursor up two lines
    sys.stdout.flush()


async def get_filepath(url: str, headers: Dict[str, str], file_path: str) -> str:
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
    url: str,
    file_path: str,
    segments: int,
    size: Size,
    etag: str,
    etag_validation: bool,
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
    partition_size, add_bytes = divmod(size.value, segments)

    for segment in range(segments):
        start = size.start + partition_size * segment
        end = (
            size.start + partition_size * (segment + 1) - 1
        )  # since range is inclusive[0-99]

        if segment == segments - 1:
            end += add_bytes

        dic[segment] = {
            "segment_size": Size(start, end),
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
    logger.setLevel(logging.WARN)
    handler = logging.FileHandler("pypdl.log", mode="a", delay=True)
    handler.setFormatter(
        logging.Formatter(
            "(%(name)s)  %(asctime)s - %(levelname)s: %(message)s",
            datefmt="%d-%m-%y %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


def get_range(range_header: str, file_size: int) -> Tuple[int, int]:
    def parse_part(part: str) -> Optional[int]:
        return int(part) if part else None

    range_value = range_header.replace("bytes=", "")
    parts = range_value.split("-")
    if len(parts) != 2:
        raise TypeError("Invalid range format")

    start, end = map(parse_part, parts)

    if start is not None and end is not None:
        if start > end:
            raise TypeError("Invalid range, start is greater than end")
    else:
        if file_size == 0:
            raise TypeError("Invalid range, file size is 0")

        if end is not None:
            if end > file_size - 1:
                raise TypeError("Invalid range, end is greater than file size")
            start = file_size - end
            end = file_size - 1
        elif start is not None:
            if start > file_size - 1:
                raise TypeError("Invalid range, start is greater than file size")
            end = file_size - 1
        else:
            raise TypeError(f"Invalid range: {start}-{end}")

    return start, end
