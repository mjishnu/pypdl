import logging

from .factory import Factory
from .manager import DownloadManager

handler = logging.FileHandler("pypdl.log", mode="a", delay=True)
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(levelname)s: %(message)s", datefmt="%d-%m-%y %H:%M:%S"
    )
)
logging.basicConfig(level=logging.INFO, handlers=[handler])


class Pypdl(DownloadManager):
    """
    A multi-segment file downloader that supports progress tracking, retries, pause/resume functionality etc.

    This class accepts keyword arguments that are valid for aiohttp.ClientSession.
    """


class PypdlFactory(Factory):
    """
    A factory class for managing multiple instances of the Pypdl downloader.

    This class accepts keyword arguments that are valid for Pypdl.
    """
