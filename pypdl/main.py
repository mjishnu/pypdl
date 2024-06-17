from .factory import Factory
from .manager import DownloadManager


class Pypdl(DownloadManager):
    """
    A multi-segment file downloader that supports progress tracking, retries, pause/resume functionality etc.

    This class also supports additional keyword arguments specified in the documentation.
    """


class PypdlFactory(Factory):
    """
    A factory class for managing multiple instances of the Pypdl downloader.

    This class also supports additional keyword arguments specified in the documentation.
    """
