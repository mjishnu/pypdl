import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pypdl import Pypdl


class TestPypdl(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super(TestPypdl, self).__init__(*args, **kwargs)
        self.temp_dir = os.path.join(tempfile.gettempdir(), "pypdl_test")
        self.download_file_1MB = "https://7-zip.org/a/7z2409-src.tar.xz"
        self.no_head_support_url = "https://ash-speed.hetzner.com/100MB.bin"

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.mkdir(self.temp_dir)

    def setUp(self):
        warnings.filterwarnings(
            "ignore", message="unclosed <socket.socket", category=ResourceWarning
        )
        warnings.filterwarnings(
            "ignore",
            message="unclosed transport",
            category=ResourceWarning,
        )

    def _assert_download(self, expected, success, filepath):
        self.assertEqual(success, expected, f"{expected - success} downloads failed")
        for path in filepath:
            self.assertTrue(os.path.exists(path))

    def test_single_segment_download(self):
        dl = Pypdl()
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir)
        result = dl.start(url, file_path, display=False, multisegment=False)
        success = len(result)
        self.assertEqual(success, 1, "Download failed")

    def test_multi_segment_download(self):
        dl = Pypdl()
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        future = dl.start(url, file_path, display=False, block=False, speed_limit=0.5)
        time.sleep(2)
        self.assertTrue(os.path.exists(file_path + ".json"))
        success = len(future.result())
        self._assert_download(1, success, [file_path])

    def test_multiple_downloads(self):
        dl = Pypdl(max_concurrent=2)
        filepath = [os.path.join(self.temp_dir, f"file{i}.dat") for i in range(4)]
        tasks = [
            {
                "url": self.download_file_1MB,
                "file_path": filepath[0],
            },
            {
                "url": self.download_file_1MB,
                "file_path": filepath[1],
            },
            {
                "url": self.download_file_1MB,
                "file_path": filepath[2],
            },
            {
                "url": self.download_file_1MB,
                "file_path": filepath[3],
            },
        ]
        result = dl.start(tasks=tasks, block=True, display=False)
        success = len(result)
        self._assert_download(4, success, filepath)

    def test_allow_reuse(self):
        result = []
        dl = Pypdl(allow_reuse=True)
        url = self.download_file_1MB
        filepath = [os.path.join(self.temp_dir, f"file{i}.dat") for i in range(2)]

        res1 = dl.start(url, filepath[0], display=False)
        result.append(res1)
        res2 = dl.start(url, filepath[1], display=False)
        result.append(res2)
        success = len(result)
        dl.shutdown()
        self._assert_download(2, success, filepath)

    def test_speed_limit(self):
        dl = Pypdl()
        url = self.download_file_1MB  # file is 1.44MB, accurate time is 14s
        file_path = os.path.join(self.temp_dir, "test_1.dat")
        dl.start(url, file_path, display=False, speed_limit=0.1)
        self.assertTrue(10 <= int(dl.time_spent) <= 30, f"took: {dl.time_spent}s")

    def test_unblocked_download(self):
        dl = Pypdl(max_concurrent=2)
        filepath = [os.path.join(self.temp_dir, f"file{i}.dat") for i in range(2)]
        tasks = [
            {
                "url": self.download_file_1MB,
                "file_path": filepath[0],
            },
            {
                "url": self.download_file_1MB,
                "file_path": filepath[1],
            },
        ]
        future = dl.start(tasks=tasks, block=False, display=False)
        while not dl.completed:
            time.sleep(1)
        success = len(future.result())
        self._assert_download(2, success, filepath)

    def test_stop_restart_with_segements(self):
        dl = Pypdl(max_concurrent=2)
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl.start(
            url, file_path, block=False, display=False, speed_limit=0.15, segments=3
        )
        time.sleep(5)
        progress = dl.progress
        dl.stop()
        self.assertTrue(os.path.exists(file_path + ".0"))
        self.assertTrue(os.path.exists(file_path + ".1"))
        self.assertTrue(dl.is_idle)
        dl.start(url, file_path, display=False, speed_limit=0.01, block=False)
        time.sleep(3)
        self.assertTrue(dl.progress >= progress)
        dl.stop()
        self.assertTrue(dl.is_idle)
        res = dl.start(url, file_path, display=False)
        success = len(res)
        self._assert_download(1, success, [file_path])

    def test_logger(self):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        log_file = os.path.join(self.temp_dir, "test.log")
        handler = logging.FileHandler(log_file, mode="a", delay=True)
        logger.addHandler(handler)

        dl = Pypdl(logger=logger)
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl.start(url, file_path, display=False, block=False)
        time.sleep(3)
        dl.shutdown()
        logger.removeHandler(handler)
        handler.close()
        self.assertTrue(os.path.exists(log_file))

    def test_header(self):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        log_file = os.path.join(self.temp_dir, "header.log")
        handler = logging.FileHandler(log_file, mode="a", delay=True)
        logger.addHandler(handler)

        dl = Pypdl(allow_reuse=True, logger=logger)
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl.start(url, file_path, display=False, block=False, speed_limit=0.1)
        time.sleep(3)
        dl.stop()
        self.assertTrue(os.path.exists(log_file))
        with open(log_file, "r") as f:
            log_content = f.read()
        header_pattern = re.compile("Header acquired from HEAD request")
        self.assertTrue(
            header_pattern.search(log_content),
            "Unable to acquire header from HEAD request",
        )

        url = self.no_head_support_url
        file_path = os.path.join(self.temp_dir, "temp.csv")
        dl.start(url, file_path, display=False, block=False, speed_limit=0.1)
        time.sleep(10)

        dl.shutdown()
        logger.removeHandler(handler)
        handler.close()

        with open(log_file, "r") as f:
            log_content = f.read()
        header_pattern = re.compile("Header acquired from GET request")
        self.assertTrue(
            header_pattern.search(log_content),
            "Unable to acquire header from GET request",
        )

    def test_retries(self):
        mirrors = [self.download_file_1MB, "http://fake_website/file2"]
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl = Pypdl()
        res = dl.start(
            "http://fake_website/file",
            file_path,
            display=False,
            retries=2,
            mirrors=mirrors,
        )
        success = len(res)
        self._assert_download(1, success, [file_path])

    def test_overwrite(self):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        log_file = os.path.join(self.temp_dir, "overwrite.log")
        handler = logging.FileHandler(log_file, mode="a", delay=True)
        logger.addHandler(handler)

        dl = Pypdl(logger=logger, allow_reuse=True)
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        res = dl.start(url, file_path, display=False)
        success = len(res)
        self._assert_download(1, success, [file_path])
        res = dl.start(url, file_path, display=False, overwrite=False)
        success = len(res)
        self._assert_download(1, success, [file_path])

        with open(log_file, "r") as f:
            log_content = f.read()
        header_pattern = re.compile("File already exists, download completed")
        self.assertTrue(header_pattern.search(log_content), "overwrite not working")
        dl.shutdown()
        logger.removeHandler(handler)
        handler.close()

    def test_etag_validation(self):
        dl = Pypdl()
        url = self.download_file_1MB
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl.start(url, file_path, display=False, block=False, speed_limit=0.1)
        time.sleep(5)
        progress = dl.progress
        dl.stop()

        with open(file_path + ".json", "r") as f:
            json_file = json.load(f)

        json_file["etag"] = "fake_etag"

        with open(file_path + ".json", "w") as f:
            json.dump(json_file, f)

        dl.start(
            url,
            file_path,
            display=False,
            etag_validation=False,
            speed_limit=0.01,
            block=False,
        )
        time.sleep(3)
        self.assertTrue(dl.progress >= progress)
        dl.shutdown()

    def test_failed(self):
        dl = Pypdl()
        url = "http://fake_website/file"
        file_path = os.path.join(self.temp_dir, "test.dat")
        dl.start(url, file_path, display=False)
        self.assertEqual(len(dl.failed), 1, "Failed downloads not found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
