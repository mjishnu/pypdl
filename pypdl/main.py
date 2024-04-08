import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Union

from manager import DownloadManager

from utls import (
    AutoShutdownFuture,
    FileValidator,
    seconds_to_hms,
)

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)


class Pypdl(DownloadManager):
    """
    A multi-threaded file downloader that supports progress tracking, retries, pause/resume functionality etc.

    Keyword Arguments:
        params (dict, optional): A dictionary, list of tuples or bytes to send as a query string. Default is None.
        allow_redirects (bool, optional): A Boolean to enable/disable redirection. Default is True.
        auth (tuple, optional): A tuple to enable a certain HTTP authentication. Default is None.
        cert (str or tuple, optional): A String or Tuple specifying a cert file or key. Default is None.
        cookies (dict, optional): A dictionary of cookies to send to the specified url. Default is None.
        headers (dict, optional): A dictionary of HTTP headers to send to the specified url. Default is None.
        proxies (dict, optional): A dictionary of the protocol to the proxy url. Default is None.
        timeout (number or tuple, optional): A number, or a tuple, indicating how many seconds to wait for the client to make a connection and/or send a response. Default is 10 seconds.
        verify (bool or str, optional): A Boolean or a String indication to verify the servers TLS certificate or not. Default is True.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stop = False

    def start(
        self,
        url: str,
        file_path: Optional[str] = None,
        segments: int = 10,
        display: bool = True,
        multithread: bool = True,
        block: bool = True,
        retries: int = 0,
        mirror_func: Optional[Callable[[], str]] = None,
        etag: bool = True,
    ) -> Union[AutoShutdownFuture, FileValidator, None]:
        """
        Start the download process.

        Parameters:
            url (str): The URL to download from.
            file_path (str, Optional): The path to save the downloaded file. If not provided, the file is saved in the current working directory.
                If `file_path` is a directory, the file is saved in that directory. If `file_path` is a file name, the file is saved with that name.
            segments (int, Optional): The number of segments to divide the file into for multi-threaded download. Default is 10.
            display (bool, Optional): Whether to display download progress and other messages. Default is True.
            multithread (bool, Optional): Whether to use multi-threaded download. Default is True.
            block (bool, Optional): Whether to block the function until the download is complete. Default is True.
            retries (int, Optional): The number of times to retry the download if it fails. Default is 0.
            mirror_func (Callable[[], str], Optional): A function that returns a new download URL if the download fails. Default is None.
            etag (bool, Optional): Whether to validate the ETag before resuming downloads. Default is True.

        Returns:
            AutoShutdownFuture: If `block` is False.
            FileValidator: If `block` is True and the download successful.
            None: If `block` is True and the download fails.
        """

        def download():
            for i in range(retries + 1):
                try:
                    _url = mirror_func() if i > 0 and callable(mirror_func) else url
                    if i > 0 and display:
                        logging.info("Retrying... (%d/%d)", i, retries)

                    self.__init__(**self._kwargs)
                    result = self._execute(
                        _url, file_path, segments, display, multithread, etag
                    )

                    if self._stop or self.completed:
                        if display:
                            print(f"Time elapsed: {seconds_to_hms(self.time_spent)}")
                        return result

                    time.sleep(3)

                except Exception as e:
                    logging.error("(%s) [%s]", e.__class__.__name__, e)

                finally:
                    if self._pool:
                        self._pool.shutdown()

            self.failed = True
            return None

        ex = ThreadPoolExecutor(max_workers=1)
        future = AutoShutdownFuture(ex.submit(download), ex)

        if block:
            result = future.result()
            return result

        return future

    def stop(self) -> None:
        """Stop the download process."""
        self._interrupt.set()
        self._stop = True
        time.sleep(1)  # wait for threads
