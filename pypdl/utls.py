import os
import time
from pathlib import Path

import requests


def timestring(sec):
    """
    Converts seconds to a string formatted as HH:MM:SS.

    Parameters:
        sec (int): The number of seconds.

    Returns:
        str: The formatted time string in the format HH:MM:SS.
    """
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Multidown:
    """
    Class for downloading a specific part of a file in multiple chunks.
    """

    def __init__(self, dic, id, stop, error, headers):
        """
        Initializes the Multidown object.

        Parameters:
            dic (dict): Dictionary containing download information for all parts.
                        Format: {start, curr, end, filepath, count, size, url, completed}
            id (int): ID of this download part.
            stop (threading.Event): Event to stop the download.
            error (threading.Event): Event to indicate an error occurred.
            headers (dict): User headers to be used in the download request.
        """
        self.curr = 0  # current size of downloaded file
        self.completed = 0  # whether the download for this part is complete
        self.id = id  # ID of this download part
        self.dic = dic  # dictionary containing download information for all parts
        self.stop = stop  # event to stop the download
        self.error = error  # event to indicate an error occurred
        self.headers = headers  # user headers

    def getval(self, key):
        """
        Get the value of a key from the dictionary.

        Parameters:
            key (str): The key to retrieve the value for.

        Returns:
            Any: The value associated with the given key in the dictionary.
        """
        return self.dic[self.id][key]

    def setval(self, key, val):
        """
        Set the value of a key in the dictionary.

        Parameters:
            key (str): The key to set the value for.
            val (Any): The value to set for the given key.
        """
        self.dic[self.id][key] = val

    def worker(self):
        """
        Download a part of the file in multiple chunks.
        """
        filepath = self.getval("filepath")
        path = Path(filepath)
        end = self.getval("end")

        # checks if the part exists, if it doesn't exist set start from the beginning, else download the rest of the file
        if not path.exists():
            start = self.getval("start")
        else:
            # gets the size of the file
            self.curr = path.stat().st_size
            # add the old start size and the current size to get the new start size
            start = self.getval("start") + self.curr
            # corruption check to make sure parts are not corrupted
            if start > end:
                os.remove(path)
                self.error.set()
                print("corrupted file!")

        url = self.getval("url")
        # not updating self.header because some wierd bug that cause the file to be unopenable
        headers = {"range": f"bytes={start}-{end}"}
        headers.update(self.headers)

        if self.curr != self.getval("size"):
            try:
                # download part
                with requests.session() as s, open(path, "ab+") as f:
                    with s.get(url, headers=headers, stream=True, timeout=20) as r:
                        for chunk in r.iter_content(1048576):  # 1MB
                            if chunk:
                                f.write(chunk)
                                self.curr += len(chunk)
                                self.setval("curr", self.curr)
                            if not chunk or self.stop.is_set() or self.error.is_set():
                                break
            except Exception as e:
                self.error.set()
                time.sleep(1)
                print(
                    f"Error in thread {self.id}: ({e.__class__.__name__}, {e})")

        if self.curr == self.getval("size"):
            self.completed = 1
            self.setval("completed", 1)


class Singledown:
    """
    Class for downloading a whole file in a single chunk.
    """

    def __init__(self, url, path, stop, error, headers):
        """
        Initializes the Singledown object.

        Parameters:
            url (str): The URL of the file to download.
            path (str): The path to save the downloaded file.
            stop (threading.Event): Event to stop the download.
            error (threading.Event): Event to indicate an error occurred.
            headers (dict): User headers to be used in the download request.
        """
        self.curr = 0  # current size of downloaded file
        self.completed = 0  # whether the download is complete
        self.url = url  # url of the file
        self.path = path  # path to save the file
        self.stop = stop  # event to stop the download
        self.error = error  # event to indicate an error occurred
        self.headers = headers  # user headers

    def worker(self):
        """
        Download a whole file in a single chunk.
        """
        flag = True
        try:
            # download part
            with requests.get(
                self.url, stream=True, timeout=20, headers=self.headers
            ) as r, open(self.path, "wb") as file:
                for chunk in r.iter_content(1048576):  # 1MB
                    if chunk:
                        file.write(chunk)
                        self.curr += len(chunk)
                    if not chunk or self.stop.is_set() or self.error.is_set():
                        flag = False
                        break
        except Exception as e:
            self.error.set()
            time.sleep(1)
            print(f"Error in thread {self.id}: ({e.__class__.__name__}: {e})")
        if flag:
            self.completed = 1
