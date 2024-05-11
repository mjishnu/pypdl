import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
import asyncio
import logging
import aiohttp

from downloader import Multidown, Simpledown
from utls import (
    FileValidator,
    ScreenCleaner,
    combine_files,
    create_segment_table,
    get_filepath,
    seconds_to_hms,
    to_mb,
    cursor_up,
)


class DownloadManager:
    def __init__(self, **kwargs):
        self._pool = ThreadPoolExecutor(max_workers=5)
        self._workers = []
        self._interrupt = Event()
        self._stop = False
        self._kwargs = {
            "timeout": 100,
            "allow_redirects": True,
        }  # request module kwargs
        self._kwargs.update(kwargs)

        self.size = None
        self.progress = 0
        self.speed = 0
        self.time_spent = 0
        self.current_size = 0
        self.eta = "99:59:59"
        self.remaining = None
        self.failed = False
        self.completed = False

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

    async def _single_thread(self, url, file_path):
        sd = Simpledown(self._interrupt)
        self._workers.append(sd)
        async with aiohttp.ClientSession() as session:
            await sd.worker(url, file_path, session)

    async def _multi_thread(self, segments, segement_table):
        tasks = []
        session = aiohttp.ClientSession()
        for segment in range(segments):
            md = Multidown(
                segment,
                self._interrupt,
                **self._kwargs,
            )
            self._workers.append(md)
            tasks.append(asyncio.create_task(md.worker(segement_table, session)))
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logging.error("(%s) [%s]", e.__class__.__name__, e)
        finally:
            await session.close()

    async def _get_header(self, url):
        kwargs = self._kwargs.copy()
        kwargs.pop("params", None)

        async with aiohttp.ClientSession() as session:
            async with session.head(url, **kwargs) as response:
                if response.status == 200:
                    return response.headers

            async with session.get(url, stream=True, **self._kwargs) as response:
                if response.status == 200:
                    return response.headers
        self._interrupt.set()
        raise ConnectionError(
            f"Server Returned: {response.reason}({response.status_code}), Invalid URL"
        )

    async def _get_info(self, url, file_path, multithread, etag):
        header = await self._get_header(url)
        file_path = get_filepath(url, header, file_path)
        if size := int(header.get("content-length", 0)):
            self.size = size

        etag = header.get("etag", not etag)  # since we check truthiness of etag

        if isinstance(etag, str):
            etag = etag.strip('"')

        if not self.size or not header.get("accept-ranges"):
            multithread = False

        return file_path, multithread, etag

    def _execute(self, url, file_path, segments, display, multithread, etag, overwrite):
        start_time = time.time()

        file_path, multithread, etag = asyncio.run(
            self._get_info(url, file_path, multithread, etag)
        )

        if not overwrite and Path(file_path).exists():
            self.completed = True
            return FileValidator(file_path)

        if multithread:
            segment_table = create_segment_table(
                url, file_path, segments, self.size, etag
            )
            segments = segment_table["segments"]
            with open("t.json", "w") as f:
                import json

                json.dump(segment_table, f, indent=4)

            self._pool.submit(
                lambda: asyncio.run(self._multi_thread(segments, segment_table))
            )
        else:
            self._pool.submit(lambda: asyncio.run(self._single_thread(url, file_path)))

        recent_queue = deque([0] * 12, maxlen=12)
        download_mode = "Multi-Threaded" if multithread else "Single-Threaded"
        interval = 0.5
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
                    if multithread:
                        combine_files(file_path, segments)
                    self.completed = True
                    self.time_spent = time.time() - start_time
                    return FileValidator(file_path)

                time.sleep(interval)
