import asyncio
import logging
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Callable, Optional, Union

import aiohttp

from .downloader import Multidown, Simpledown
from .utls import (
    AutoShutdownFuture,
    FileValidator,
    ScreenCleaner,
    combine_files,
    create_segment_table,
    cursor_up,
    get_filepath,
    seconds_to_hms,
    to_mb,
)


class DownloadManager:
    def __init__(self, allow_reuse: bool = False, **kwargs):
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._workers = []
        self._status = 0
        self._interrupt = Event()
        self._stop = False
        self._kwargs = {"timeout": aiohttp.ClientTimeout(sock_read=60)}
        self._kwargs.update({**kwargs, "raise_for_status": True})
        self._allow_reuse = allow_reuse

        self.size = None
        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.eta = "99:59:59"
        self.remaining = None
        self.failed = False
        self.completed = False

    def start(
        self,
        url: str,
        file_path: Optional[str] = None,
        segments: int = 10,
        display: bool = True,
        multisegment: bool = True,
        block: bool = True,
        retries: int = 0,
        mirror_func: Optional[Callable[[], str]] = None,
        etag: bool = True,
        overwrite: bool = True,
    ) -> Union[AutoShutdownFuture, Future, FileValidator, None]:
        """
        Start the download process.

        Parameters:
            url (str): The URL to download from.
            file_path (str, Optional): The path to save the downloaded file. If not provided, the file is saved in the current working directory.
                If `file_path` is a directory, the file is saved in that directory. If `file_path` is a file name, the file is saved with that name.
            segments (int, Optional): The number of segments to divide the file into for multi-segment download. Default is 10.
            display (bool, Optional): Whether to display download progress and other messages. Default is True.
            multisegment (bool, Optional): Whether to use multi-Segment download. Default is True.
            block (bool, Optional): Whether to block the function until the download is complete. Default is True.
            retries (int, Optional): The number of times to retry the download if it fails. Default is 0.
            mirror_func (Callable[[], str], Optional): A function that returns a new download URL if the download fails. Default is None.
            etag (bool, Optional): Whether to validate the ETag before resuming downloads. Default is True.
            overwrite (bool, Optional): Whether to overwrite the file if it already exists. Default is True.

        Returns:
            AutoShutdownFuture: If `block` is False.
            FileValidator: If `block` is True and the download successful.
            None: If `block` is True and the download fails.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = mirror_func() if i > 0 and callable(mirror_func) else url
                    if i > 0:
                        logging.info("Retrying... (%d/%d)", i, retries)

                    self._reset()
                    result = self._execute(
                        _url,
                        file_path,
                        segments,
                        display,
                        multisegment,
                        etag,
                        overwrite,
                    )

                    if self._stop or self.completed:
                        if display:
                            print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")
                        return result

                    time.sleep(3)

                except Exception as e:
                    logging.error("(%s) [%s]", e.__class__.__name__, e)

            self._status = 1
            self.failed = True
            return None

        if self._allow_reuse:
            future = self._pool.submit(download)
        else:
            future = AutoShutdownFuture(self._pool.submit(download), [self._pool])

        if block:
            result = future.result()
            return result

        return future

    def stop(self) -> None:
        """Stop the download process."""
        self._interrupt.set()
        self._stop = True
        time.sleep(1)

    def shutdown(self) -> None:
        """Shutdown the download manager."""
        self._pool.shutdown()

    def _reset(self):
        self._workers.clear()
        self._interrupt.clear()
        self._stop = False

        self.size = None
        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.eta = "99:59:59"
        self.remaining = None
        self.failed = False
        self.completed = False

    def _execute(
        self, url, file_path, segments, display, multisegment, etag, overwrite
    ):
        start_time = time.time()

        file_path, multisegment, etag = self._get_info(
            url, file_path, multisegment, etag
        )

        if not overwrite and Path(file_path).exists():
            self._status = 1
            self.completed = True
            return FileValidator(file_path)

        if multisegment:
            segment_table = create_segment_table(
                url, file_path, segments, self.size, etag
            )
            segments = segment_table["segments"]

            self._pool.submit(
                lambda: asyncio.run(self._multi_segment(segments, segment_table))
            )
        else:
            self._pool.submit(lambda: asyncio.run(self._single_segment(url, file_path)))

        recent_queue = deque([0] * 12, maxlen=12)
        download_mode = "Multi-Segment" if multisegment else "Single-Segment"
        interval = 0.5
        self._status = 1
        with ScreenCleaner(display):
            while True:
                status = sum(worker.completed for worker in self._workers)
                self._calc_values(recent_queue, interval)

                if display:
                    self._display(download_mode)

                if self._interrupt.is_set():
                    self.time_spent = time.time() - start_time
                    return None

                if status and status == len(self._workers):
                    if multisegment:
                        combine_files(file_path, segments)
                    self.completed = True
                    self.time_spent = time.time() - start_time
                    return FileValidator(file_path)

                time.sleep(interval)

    def _get_info(self, url, file_path, multisegment, etag):
        header = asyncio.run(self._get_header(url))
        file_path = get_filepath(url, header, file_path)
        if size := int(header.get("content-length", 0)):
            self.size = size

        etag = header.get("etag", not etag)  # since we check truthiness of etag

        if isinstance(etag, str):
            etag = etag.strip('"')

        if not self.size or not header.get("accept-ranges"):
            multisegment = False

        return file_path, multisegment, etag

    async def _get_header(self, url):
        kwargs = self._kwargs.copy()
        kwargs.update({"raise_for_status": False})

        async with aiohttp.ClientSession() as session:
            async with session.head(url, **kwargs) as response:
                if response.status == 200:
                    return response.headers

            async with session.get(url, **self._kwargs) as response:
                if response.status == 200:
                    return response.headers

        self._interrupt.set()
        raise ConnectionError(
            f"Server Returned: {response.reason}({response.status}), Invalid URL"
        )

    async def _multi_segment(self, segments, segment_table):
        tasks = []
        async with aiohttp.ClientSession() as session:
            for segment in range(segments):
                md = Multidown(self._interrupt)
                self._workers.append(md)
                tasks.append(
                    asyncio.create_task(
                        md.worker(segment_table, segment, session, **self._kwargs)
                    )
                )
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                logging.error("(%s) [%s]", e.__class__.__name__, e)
                self._interrupt.set()

    async def _single_segment(self, url, file_path):
        async with aiohttp.ClientSession() as session:
            sd = Simpledown(self._interrupt)
            self._workers.append(sd)
            try:
                await sd.worker(url, file_path, session)
            except Exception as e:
                logging.error("(%s) [%s]", e.__class__.__name__, e)
                self._interrupt.set()

    def _calc_values(self, recent_queue, interval):
        self.current_size = sum(worker.curr for worker in self._workers)

        # Speed calculation
        recent_queue.append(sum(worker.downloaded for worker in self._workers))
        non_zero_list = [to_mb(value) for value in recent_queue if value]
        if len(non_zero_list) < 1:
            self.speed = 0
        elif len(non_zero_list) == 1:
            self.speed = non_zero_list[0] / interval
        else:
            diff = [b - a for a, b in zip(non_zero_list, non_zero_list[1:])]
            self.speed = (sum(diff) / len(diff)) / interval

        if self.size:
            self.progress = int((self.current_size / self.size) * 100)
            self.remaining = to_mb(self.size - self.current_size)

            if self.speed:
                self.eta = seconds_to_hms(self.remaining / self.speed)
            else:
                self.eta = "99:59:59"

    def _display(self, download_mode):
        cursor_up()
        if self.size:
            progress_bar = f"[{'█' * self.progress}{'·' * (100 - self.progress)}] {self.progress}% \n"
            info = f"Total: {to_mb(self.size):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s, ETA: {self.eta} "
            print(progress_bar + info)
        else:
            download_stats = "Downloading... \n"
            info = f"Downloaded: {to_mb(self.current_size):.2f} MB, Download Mode: {download_mode}, Speed: {self.speed:.2f} MB/s "
            print(download_stats + info)
