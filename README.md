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

dl = Pypdl(allow_reuse=False, logger=default_logger("Pypdl"), max_concurrent: int = 1)
dl.start(
    url=None,
    file_path=None,
    tasks=None,
    multisegment=True,
    segments=10,
    overwrite=True,
    etag=True,
    retries=0,
    display=True,
    clear_terminal=True,
    block=True,
    **kwargs
)
```

Each option is explained below:
- `allow_reuse`: Whether to allow reuse of existing Pypdl object for the next download. The default value is `False`.
- `logger`: A logger object to log messages. The default value is a custom `Logger` with the name *Pypdl*.
- `max_concurrent`: The maximum number of concurrent downloads. The default value is 1.
- `url`: This can either be the URL of the file to download or a function that returns the URL.
- `file_path`: An optional path to save the downloaded file. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it; otherwise, the file is downloaded into the given path.
- `tasks`: A list of tasks to be downloaded. Each task is a dictionary with the following keys:
    - `url` (required): The URL of the file to download.
    - Optional keys (The default value is set by the `Pypdl` start method):
        - `file_path`: path to save the downloaded file.
        - `multisegment`: Whether to use multi-segmented download.
        - `segments`: The number of segments the file should be divided into for multi-segmented download.
        - `overwrite`: Whether to overwrite the file if it already exists.
        - `etag`: Whether to validate the ETag before resuming downloads.
        - `retries`: The number of times to retry the download in case of an error.
    - Additonal supported keyword arguments of `Pypdl` start method.
    
- `multisegment`: Whether to use multi-segmented download. The default value is `True`.
- `segments`: The number of segments the file should be divided into for multi-segmented download. The default value is 10.
- `overwrite`: Whether to overwrite the file if it already exists. The default value is `True`.
- `etag`: Whether to validate the ETag before resuming downloads. The default value is `True`.
- `retries`: The number of times to retry the download in case of an error. The default value is 0.
- `display`: Whether to display download progress and other optional messages. The default value is `True`.
- `clear_terminal`: Whether to clear the terminal before displaying the download progress. The default value is `True`.
- `block`: Whether to block until the download is complete. The default value is `True`.

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

### Examples

Here is an example that demonstrates how to use pypdl library to download a file using headers, proxy and timeout:

```py
import aiohttp
from pypdl import Pypdl

def main():
    # Using headers
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"}
    # Using proxy
    proxy = "http://user:pass@some.proxy.com"
    # Using timeout
    timeout = aiohttp.ClientTimeout(sock_read=20)

    # create a new pypdl object
    dl = Pypdl(headers=headers, proxy=proxy, timeout=timeout)

    # start the download
    dl.start(
        url='https://speed.hetzner.de/100MB.bin',
        file_path='100MB.bin',
        segments=10,
        display=True,
        multisegment=True,
        block=True,
        retries=3,
        etag=True,
    )

if __name__ == '__main__':
    main()
```

This example downloads a file from the internet using 10 segments and displays the download progress. If the download fails, it will retry up to 3 times. we are also using headers, proxy and timeout, For more info regarding these parameters refer [API reference](https://github.com/mjishnu/pypdl?tab=readme-ov-file#pypdl-1)

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
future = dl.start('https://example.com/file.zip', segments=8,block=False,display=False)

# print the progress
while dl.progress != 70:
  print(dl.progress)

# stop the download process
dl.stop() 

#do something
#...

# resume the download process
future = dl.start('https://example.com/file.zip', segments=8,block=False,display=False)

# print rest of the progress
while not d.completed:
  print(dl.progress)

# get the result, calling result() on future is essential when block=False so everything is properly cleaned up
result = future.result()

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
res = dl.start(dynamic_url, block=True) 

# validate hash
if res.validate_hash(correct_hash,'sha256'):
    print('Hash is valid')
else:
    print('Hash is invalid')

# scenario where block = False --> returns a AutoShutdownFuture object
mirror_urls = ['https://example.com/file2.zip', 'https://example.com/file1.zip']

mirror_func = lambda: mirror_urls.pop(0) 

# retry download with different url if current fails
future = dl.start(mirror_func, block=False,retries=2)

# do something
# ...

# It is essential to call result() on future when block=False so everything is properly cleaned up
res = future.result()
# validate hash
if dl.completed:
  if res.validate_hash(correct_hash,'sha256'):
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
    
    # get the size of the file and add it to size list
    size.append(dl.size)

    # do something 

    while not dl.completed:
        print(dl.progress)

print(size)
# shutdown the downloader, this is essential when allow_reuse is enabled
dl.shutdown()

```


An example of downloading multiple files concurrently:

```py
from pypdl import pypdl

proxy = "http://user:pass@some.proxy.com"

# create a pypdl object with max_concurrent set to 2
dl = pypdl(max_concurrent=2, allow_reuse=True, proxy=proxy)

# List of tasks to be downloaded..
tasks = [
    {'url':'https://example.com/file1.zip', 'file_path': 'file1.zip'},
    {'url':'https://example.com/file2.zip', 'file_path': 'file2.zip'},
    {'url':'https://example.com/file3.zip', 'file_path': 'file3.zip'},
    {'url':'https://example.com/file4.zip', 'file_path': 'file4.zip'},
    {'url':'https://example.com/file5.zip', 'file_path': 'file5.zip'},
]

# start the download process
results = dl.start(tasks=tasks, display=True, block=False)

# do something
# ...

# stop the download process
dl.stop()

# do something
# ...

# restart the download process
results = factory.start(tasks=tasks, display=True, block=True)

# print the results
for url, result in results:
    # validate hash
    if result.validate_hash(correct_hash,'sha256'):
        print(f'{url} - Hash is valid')
    else:
        print(f'{url} - Hash is invalid')

task2 = [
    {'url':'https://example.com/file6.zip', 'file_path': 'file6.zip'},
    {'url':'https://example.com/file7.zip', 'file_path': 'file7.zip'},
    {'url':'https://example.com/file8.zip', 'file_path': 'file8.zip'},
    {'url':'https://example.com/file9.zip', 'file_path': 'file9.zip'},
    {'url':'https://example.com/file10.zip', 'file_path': 'file10.zip'},
]

# start the download process
dl.start(tasks=task2, display=True, block=True)

# shutdown the downloader, this is essential when allow_reuse is enabled
dl.shutdown()
```
For more detailed info about parameters refer [API reference](https://github.com/mjishnu/pypdl?tab=readme-ov-file#pypdlfactory)
## API Reference

### `Pypdl()`

The `Pypdl` class represents a file downloader that can download a file from a given URL to a specified file path. The class supports both single-segmented and multi-segmented downloads and many other features like retry download incase of failure and option to continue downloading using a different url if necessary, pause/resume functionality, progress tracking etc.

#### Arguments
- `allow_reuse`: (bool, Optional) Whether to allow reuse of existing `Pypdl` object for next download. The default value is `False`.It's essential to use `shutdown()` method when `allow_reuse` is enabled to ensure efficient resource management.

- `logger`: (logging.Logger, Optional) A logger object to log messages. The default value is custom `Logger` with the name *Pypdl*.

- `max_concurrent`: (int, Optional) The maximum number of concurrent downloads. The default value is 1.

#### Attributes

- `size`: The total size of the file to be downloaded, in bytes.
- `current_size`: The amount of data downloaded so far, in bytes.
- `remaining_size`: The amount of data remaining to be downloaded, in bytes.
- `progress`: The download progress percentage.
- `speed`: The download speed, in MB/s.
- `time_spent`: The time spent downloading, in seconds.
- `eta`: The estimated time remaining for download completion, in seconds.
- `total_tasks`: The total number of tasks to be downloaded.
- `completed_tasks`: The number of tasks that have been completed.
- `task_progress`: The progress of all tasks.
- `completed`: A flag that indicates if the download is complete.
- `success`: A list of tasks that were successfully downloaded.
- `failed`: A list of tasks that failed to download.
- `logger`: A property that returns the logger if available.
- `is_idle`: A flag that indicates if the downloader is idle.

#### Methods

- `start(url=None,
file_path=None,
tasks=None,
multisegment=True,
segments=10,
overwrite=True,
etag=True,
retries=0,
display=True,
clear_terminal=True,
block=True
**kwargs)`: Starts the download process.

    ##### Parameters

    - `url`: This can either be the URL of the file to download or a function that returns the URL.
    - `file_path`: An optional path to save the downloaded file. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it; otherwise, the file is downloaded into the given path.
    - `tasks`: A list of tasks to be downloaded. Each task is a dictionary with the following keys:
        - `url` (required): The URL of the file to download.
        - Optional keys (The default value is set by the `Pypdl` start method):
            - `file_path`: path to save the downloaded file.
            - `multisegment`: Whether to use multi-segmented download.
            - `segments`: The number of segments the file should be divided into for multi-segmented download.
            - `overwrite`: Whether to overwrite the file if it already exists.
            - `etag`: Whether to validate the ETag before resuming downloads.
            - `retries`: The number of times to retry the download in case of an error.
        - Additonal supported keyword arguments of `Pypdl` start method.
        
    - `multisegment`: Whether to use multi-segmented download. The default value is `True`.
    - `segments`: The number of segments the file should be divided into for multi-segmented download. The default value is 10.
    - `overwrite`: Whether to overwrite the file if it already exists. The default value is `True`.
    - `etag`: Whether to validate the ETag before resuming downloads. The default value is `True`.
    - `retries`: The number of times to retry the download in case of an error. The default value is 0.
    - `display`: Whether to display download progress and other optional messages. The default value is `True`.
    - `clear_terminal`: Whether to clear the terminal before displaying the download progress. The default value is `True`.
    - `block`: Whether to block until the download is complete. The default value is `True`.

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

    ##### Returns
    
    - `AutoShutdownFuture`: If `block` and `allow_reuse` is  set to `False`.
    - `EFuture`: If `block` is `False` and `allow_reuse` is `True`.
    - `FileValidator`: If `block` is `True` and the download is successful.
    - `None`: If `block` is `True` and the download fails.

- `stop()`: Stops the download process.
- `shutdown()`: Shuts down the downloader.
- `set_allow_reuse(allow_reuse)`: Sets whether to allow reuse of existing `Pypdl` object for next download.
- `set_logger(logger)`: Sets the logger object to be used for logging messages.
- `set_max_concurrent(max_concurrent)`: Sets the maximum number of concurrent downloads.

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

#### `EFuture()`

The `EFuture` class is a wrapper for a `concurrent.futures.Future` object that integrates with an event loop to handle asynchronous operations.

##### Parameters

- `future`: The `Future` object to be wrapped.
- `loop`: The event loop that will be used to manage the `Future`.

##### Methods

- `result(timeout=None)`: Retrieves the result of the `Future` object. If the `Future` completes successfully, it returns the result; otherwise, it raises an exception.

## License

pypdl is licensed under the MIT License. See the [LICENSE](https://github.com/mjishnu/pypdl/blob/main/LICENSE) file for more details.

## Contribution

Contributions to pypdl are always welcome. If you want to contribute to this project, please fork the repository and submit a pull request.

## Contact

If you have any questions, issues, or feedback about pypdl, please open an issue on the [GitHub repository](https://github.com/mjishnu/pypdl).
