# pypdl

pypdl is a Python library for downloading files from the internet. It provides features such as multi-segmented downloads, retry download in case of failure, option to continue downloading using a different URL if necessary, progress tracking, pause/resume functionality, checksum and many more.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
  - [Basic Usage](#basic-usage)
  - [Advanced Usage](#advanced-usage)
  - [Examples](#examples)
- [API Reference](#api-reference)
- [License](#license)
- [Contribution](#contribution)
- [Contact](#contact)

## Prerequisites

* Python 3.8 or later.

## Installation

To install the pypdl, run the following command:


```bash
pip install pypdl
```
## Usage

### Basic Usage

To download a file using the pypdl, simply create a new `Pypdl` object and call its `start` method, passing in the URL of the file to be downloaded:

```py
from pypdl import Pypdl

dl = Pypdl()
dl.start('http://example.com/file.txt')
```

### Advanced Usage

The `Pypdl` object provides additional options for advanced usage:

```py
from pypdl import Pypdl

dl = Pypdl(allow_reuse=False, logger=default_logger("Pypdl"))
dl.start(
    url='http://example.com/file.txt',
    file_path='file.txt',
    segments=10,
    display=True,
    multisegment=True,
    block=True,
    retries=0,
    mirror_func=None,
    etag=True,
    overwrite=False
)
```

Each option is explained below:
- `allow_reuse`: Whether to allow reuse of existing Pypdl object for next download. The default value is `False`.
- `logger`: A logger object to log messages. The default value is custom `Logger` with the name *Pypdl*.
- `url`: This can either be the URL of the file to download or a function that returns the URL.
- `file_path`: An optional path to save the downloaded file. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it  otherwise, the file is downloaded into the given path.
- `segments`: The number of segments the file should be divided in multi-segmented download. The default value is 10.
- `display`: Whether to display download progress and other optional messages. The default value is `True`.
- `multisegment`: Whether to use multi-segmented download. The default value is `True`.
- `block`: Whether to block until the download is complete. The default value is `True`.
- `retries`: The number of times to retry the download in case of an error. The default value is 0.
- `mirror_func`: A function to get a new download URL in case of an error.
- `etag`: Whether to validate etag before resuming downloads. The default value is `True`.
- `overwrite`: Whether to overwrite the file if it already exists. The default value is `False`.

### Examples

Here is an example that demonstrates how to use pypdl library to download a file using headers, proxies, timeout and authentication:

```py
import aiohttp
from pypdl import Pypdl

def main():
    # Using headers
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"}
    # Using proxies
    proxies = {
                    "http": "http://10.10.1.10:3128",
                    "https": "https://10.10.1.10:1080",
                }
    # Using authentication
    auth = ("user","pass")

    # Using timeout
    timeout = aiohttp.ClientTimeout(sock_read=20)

    # create a new pypdl object
    dl = Pypdl(headers=headers, proxies=proxies, timeout=timeout, auth=auth)

    # start the download
    dl.start(
        url='https://speed.hetzner.de/100MB.bin',
        file_path='100MB.bin',
        segments=10,
        display=True,
        multisegment=True,
        block=True,
        retries=3,
        mirror_func=None,
        etag=True,
    )

if __name__ == '__main__':
    main()
```

This example downloads a file from the internet using 10 segments and displays the download progress. If the download fails, it will retry up to 3 times. we are also using headers, proxies and authentication.

Another example of implementing pause resume functionality, printing the progress to console and changing log level to debug:

```py
from pypdl import Pypdl

# create a pypdl object
dl = Pypdl()

# changing log level to debug
dl.logger.setLevel('DEBUG')

# start the download process
# block=False so we can print the progress
# display=False so we can print the progress ourselves
dl.start('https://example.com/file.zip', segments=8,block=False,display=False)

# print the progress
while dl.progress != 70:
  print(dl.progress)

# stop the download process
dl.stop() 

#do something
#...

# resume the download process
dl.start('https://example.com/file.zip', segments=8,block=False,display=False)

# print rest of the progress
while not d.completed:
  print(dl.progress)

```

This example we start the download process and print the progress to console. We then stop the download process and do something else. After that we resume the download process and print the rest of the progress to console. This can be used to create a pause/resume functionality.

Another example of using hash validation with dynamic url:

```py
from pypdl import Pypdl

# Generate the url dynamically
def dynamic_url():
    return 'https://example.com/file.zip'

# create a pypdl object
dl = Pypdl()

# if block = True --> returns a FileValidator object
file = dl.start(dynamic_url, block=True) 

# validate hash
if file.validate_hash(correct_hash,'sha256'):
    print('Hash is valid')
else:
    print('Hash is invalid')

# scenario where block = False --> returns a AutoShutdownFuture object
file = dl.start(dynamic_url, block=False)

# do something
# ...

# validate hash
if dl.completed:
  if file.result().validate_hash(correct_hash,'sha256'):
      print('Hash is valid')
  else:
      print('Hash is invalid')
```
An example of using Pypdl object to get size of the files with `allow_reuse` set to `True` and custom logger:

```py
import logging
import time
from pypdl import Pypdl

urls = [
    'https://example.com/file1.zip',
    'https://example.com/file2.zip',
    'https://example.com/file3.zip',
    'https://example.com/file4.zip',
    'https://example.com/file5.zip',
]

# create a custom logger
logger = logging.getLogger('custom')

size = []

# create a pypdl object
dl = Pypdl(allow_reuse=True, logger=logger)

for url in urls:
    dl.start(url, block=False)

    # waiting for the size and other preliminary data to be retrived
    while dl.wait:
        time.sleep(0.1)
    
    # get the size of the file and add it to size list
    size.append(dl.size)

    # do something 

    while not dl.completed:
        print(dl.progress)

print(size)
# shutdown the downloader, this is essential when allow_reuse is enabled
dl.shutdown()

```


An example of using `PypdlFactory` to download multiple files concurrently:

```py
from pypdl import PypdlFactory

proxies = {"http": "http://10.10.1.10:3128", "https": "https://10.10.1.10:1080"}

# create a PypdlFactory object
factory = PypdlFactory(instances=5, allow_reuse=True, proxies=proxies)

# List of tasks to be downloaded. Each task is a tuple of (URL, {Pypdl arguments}).
# - URL: The download link (string).
# - {Pypdl arguments}: A dictionary of arguments supported by `Pypdl`.
tasks = [
    ('https://example.com/file1.zip', {'file_path': 'file1.zip'}),
    ('https://example.com/file2.zip', {'file_path': 'file2.zip'}),
    ('https://example.com/file3.zip', {'file_path': 'file3.zip'}),
    ('https://example.com/file4.zip', {'file_path': 'file4.zip'}),
    ('https://example.com/file5.zip', {'file_path': 'file5.zip'}),
]

# start the download process
results = factory.start(tasks, display=True, block=False)

# do something
# ...

# stop the download process
factory.stop()

# do something
# ...

# restart the download process
results = factory.start(tasks, display=True, block=True)

# print the results
for url, result in results:
    # validate hash
    if result.validate_hash(correct_hash,'sha256'):
        print(f'{url} - Hash is valid')
    else:
        print(f'{url} - Hash is invalid')

task2 = [
    ('https://example.com/file6.zip', {'file_path': 'file6.zip'}),
    ('https://example.com/file7.zip', {'file_path': 'file7.zip'}),
    ('https://example.com/file8.zip', {'file_path': 'file8.zip'}),
    ('https://example.com/file9.zip', {'file_path': 'file9.zip'}),
    ('https://example.com/file10.zip', {'file_path': 'file10.zip'}),
]

# start the download process
factory.start(task2, display=True, block=True)

# shutdown the downloader, this is essential when allow_reuse is enabled
factory.shutdown()
```
## API Reference

### `Pypdl()`

The `Pypdl` class represents a file downloader that can download a file from a given URL to a specified file path. The class supports both single-segmented and multi-segmented downloads and many other features like retry download incase of failure and option to continue downloading using a different url if necessary, pause/resume functionality, progress tracking etc.

#### Arguments
- `allow_reuse`: (bool, Optional) Whether to allow reuse of existing `Pypdl` object for next download. The default value is `False`.It's essential to use `shutdown()` method when `allow_reuse` is enabled to ensure efficient resource management.

- `logger`: (logging.Logger, Optional) A logger object to log messages. The default value is custom `Logger` with the name *Pypdl*.

- Supported Keyword Arguments:
    - `params`: Parameters to be sent in the query string of the new request. The default value is `None`.
    - `data`: The data to send in the body of the request. The default value is `None`.
    - `json`: A JSON-compatible Python object to send in the body of the request. The default value is `None`.
    - `cookies`: HTTP Cookies to send with the request. The default value is `None`.
    - `headers`: HTTP Headers to send with the request. The default value is `None`.
    - `auth`: An object that represents HTTP Basic Authorization. The default value is `None`.
    - `allow_redirects`: If set to False, do not follow redirects. The default value is `True`.
    - `max_redirects`: Maximum number of redirects to follow. The default value is `10`.
    - `proxy`: Proxy URL. The default value is `None`.
    - `proxy_auth`: An object that represents proxy HTTP Basic Authorization. The default value is `None`.
    - `timeout`: (default `aiohttp.ClientTimeout(sock_read=60)`): Override the session’s timeout. The default value is `aiohttp.ClientTimeout(sock_read=60)`.
    - `ssl`: SSL validation mode. The default value is `None`.
    - `proxy_headers`: HTTP headers to send to the proxy if the `proxy` parameter has been provided. The default value is `None`.

    For detailed information on each parameter, refer the [aiohttp documentation](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientSession.request). Please ensure that only the *supported keyword arguments* are used. Using unsupported or irrelevant keyword arguments may lead to unexpected behavior or errors.
    
#### Attributes

- `size`: The total size of the file to be downloaded, in bytes.
- `progress`: The download progress percentage.
- `speed`: The download speed, in MB/s.
- `time_spent`: The time spent downloading, in seconds.
- `current_size`: The amount of data downloaded so far, in bytes.
- `eta`: The estimated time remaining for download completion, in the format "HH:MM:SS".
- `remaining`: The amount of data remaining to be downloaded, in bytes.
- `failed`: A flag that indicates if the download failed.
- `completed`: A flag that indicates if the download is complete.
- `wait`: A flag indicating whether preliminary information (e.g., file size) has been retrieved.
- `logger`: The logger object used for logging messages.

#### Methods

- `start(url, file_path, segments=10, display=True, multisegment=True, block=True, retries=0, mirror_func=None, etag=False)`: Starts the download process.

    ##### Parameters

    - `url`: ((str, function), Required) This can either be the URL of the file to download or a function that returns the URL.
    - `file_path`: (str, Optional) The optional file path to save the download. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it; otherwise, the file is downloaded with the given name.
    - `segments`: (int, Optional) The number of segments the file should be divided into for multi-segmented download.
    - `display`: (bool, Optional) Whether to display download progress and other optional messages.
    - `multisegment`: (bool, Optional) Whether to use multi-segmented download.
    - `block`: (bool, Optional) Whether to block until the download is complete.
    - `retries`: (int, Optional) The number of times to retry the download in case of an error.
    - `mirror_func`: (function, Optional) A function to get a new download URL in case of an error.
    - `etag`: (bool, Optional) Whether to validate etag before resuming downloads.
    - `overwrite`: (bool, Optional) Whether to overwrite the file if it already exists.

    ##### Returns
    
    - `AutoShutdownFuture`: If `block` and `allow_reuse` is  set to `False`.
    - `concurrent.futures.Future`: If `block` is `False` and `allow_reuse` is `True`.
    - `FileValidator`: If `block` is `True` and the download is successful.
    - `None`: If `block` is `True` and the download fails.

- `stop()`: Stops the download process.
- `shutdown()`: Shuts down the downloader.

### `PypdlFactory()`

The `PypdlFactory` class manages multiple instances of the `Pypdl` downloader. It allows for concurrent downloads and provides progress tracking across all active downloads.

#### Arguments

- `instances`: (int, Optional) The number of `Pypdl` instances to create. The default value is 5.
- `allow_reuse`: (bool, Optional) Whether to allow reuse of existing `PypdlFactory` objects for next download. The default value is `False`. It's essential to use `shutdown()` method when `allow_reuse` is enabled to ensure efficient resource management.

- `logger`: (logging.Logger, Optional) A logger object to log messages. The default value is custom `Logger` with the name *PypdlFactory*.

- Supported Keyword Arguments:
    - `params`: Parameters to be sent in the query string of the new request. The default value is `None`.
    - `data`: The data to send in the body of the request. The default value is `None`.
    - `json`: A JSON-compatible Python object to send in the body of the request. The default value is `None`.
    - `cookies`: HTTP Cookies to send with the request. The default value is `None`.
    - `headers`: HTTP Headers to send with the request. The default value is `None`.
    - `auth`: An object that represents HTTP Basic Authorization. The default value is `None`.
    - `allow_redirects`: If set to False, do not follow redirects. The default value is `True`.
    - `max_redirects`: Maximum number of redirects to follow. The default value is `10`.
    - `proxy`: Proxy URL. The default value is `None`.
    - `proxy_auth`: An object that represents proxy HTTP Basic Authorization. The default value is `None`.
    - `timeout`: (default `aiohttp.ClientTimeout(sock_read=60)`): Override the session’s timeout. The default value is `aiohttp.ClientTimeout(sock_read=60)`.
    - `ssl`: SSL validation mode. The default value is `None`.
    - `proxy_headers`: HTTP headers to send to the proxy if the `proxy` parameter has been provided. The default value is `None`.

    For detailed information on each parameter, refer the [aiohttp documentation](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientSession.request). Please ensure that only the *supported keyword arguments* are used. Using unsupported or irrelevant keyword arguments may lead to unexpected behavior or errors.

#### Attributes

- `progress`: The overall download progress percentage across all active downloads.
- `speed`: The average download speed across all active downloads, in MB/s.
- `time_spent`: The total time spent downloading across all active downloads, in seconds.
- `current_size`: The total amount of data downloaded so far across all active downloads, in bytes.
- `total`: The total number of download tasks.
- `completed`: A list of tuples where each tuple contains the URL of the download and the result of the download.
- `failed`: A list of URLs for which the download failed.
- `remaining`: A list of remaining download tasks.
- `logger`: The logger object used for logging messages.

#### Methods

- `start(tasks, display=True, block=True)`: Starts the download process for multiple tasks.

    ##### Parameters

    - `tasks`: (list) A list of tasks to be downloaded. Each task is a tuple where the first element is the URL and the second element is an optional dictionary with keyword arguments for `Pypdl` start method.
    - `display`: (bool, Optional) Whether to display download progress and other messages. Default is True.
    - `block`: (bool, Optional) Whether to block the function until all downloads are complete. Default is True.

    ##### Returns

    - `AutoShutdownFuture`: If `block` and `allow_reuse` is  set to `False`.
    - `concurrent.futures.Future`: If `block` is `False` and `allow_reuse` is `True`.
    - `list`: If `block` is `True`. This is a list of tuples where each tuple contains the URL of the download and the result of the download.

- `stop()`: Stops all active downloads.
- `shutdown()`: Shuts down the factory.

### Helper Classes

#### `Basicdown()`

The `Basicdown` class is the base downloader class that provides the basic structure for downloading files.

##### Attributes

- `curr`: The current size of the downloaded file in bytes.
- `completed`: A flag that indicates if the download is complete.
- `interrupt`: A flag that indicates if the download was interrupted.
- `downloaded`: The total amount of data downloaded so far in bytes.

##### Methods

- `download(url, path, mode, session, **kwargs)`: Downloads data in chunks.

#### `Singledown()`

The `Singledown` class extends `Basicdown` and is responsible for downloading a whole file in a single segment.

##### Methods

- `worker(url, file_path, session, **kwargs)`: Downloads a whole file in a single segment.

#### `Multidown()`

The `Multidown` class extends `Basicdown` and is responsible for downloading a specific segment of a file.

##### Methods

- `worker(segment_table, id, session, **kwargs)`: Downloads a part of the file in multiple segments.

#### `FileValidator()`

The `FileValidator` class is used to validate the integrity of the downloaded file.

##### Parameters

- `path`: The path of the file to be validated.

##### Methods

- `calculate_hash(algorithm, **kwargs)`: Calculates the hash of the file using the specified algorithm. Returns the calculated hash as a string.

- `validate_hash(correct_hash, algorithm, **kwargs)`: Validates the hash of the file against the correct hash. Returns `True` if the hashes match, `False` otherwise.

  `calculate_hash` and `validate_hash` can support additional keyword arguments from the [hashlib module](https://docs.python.org/3/library/hashlib.html#hashlib.new).

#### `AutoShutdownFuture()`

The `AutoShutdownFuture` class is a wrapper for concurrent.futures.Future object that shuts down a list of associated executors when the result is retrieved.

##### Parameters

- `future`: The Future object to be wrapped.
- `executors`: The list of executors to be shut down when the result is retrieved.

##### Methods

- `result(timeout=None)`: Retrieves the result of the Future object and shuts down the executor. If the download was successful, it returns a `FileValidator` object; otherwise, it returns `None`.

## License

pypdl is licensed under the MIT License. See the [LICENSE](https://github.com/mjishnu/pypdl/blob/main/LICENSE) file for more details.

## Contribution

Contributions to pypdl are always welcome. If you want to contribute to this project, please fork the repository and submit a pull request.

## Contact

If you have any questions, issues, or feedback about pypdl, please open an issue on the [GitHub repository](https://github.com/mjishnu/pypdl).
