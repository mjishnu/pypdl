# pypdl

pypdl is a Python library for downloading files from the internet. It provides features such as multi-threaded downloads, retry download in case of failure, option to continue downloading using a different URL if necessary, progress tracking, pause/resume functionality, checksum and many more.

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

To download a file using the pypdl, simply create a new `Downloader` object and call its `start` method, passing in the URL of the file to be downloaded:

```py
from pypdl import Downloader

dl = Downloader()
dl.start('http://example.com/file.txt')
```

### Advanced Usage

The `Downloader` object provides additional options for advanced usage:

```py
dl.start(
    url='http://example.com/file.txt',
    file_path='file.txt',
    segments=10,
    display=True,
    multithread=True,
    block=True,
    retries=0,
    mirror_func=None,
    etag=True
)
```

Each option is explained below:

- `url`: The URL of the file to download.
- `file_path`: An optional path to save the downloaded file. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it  otherwise, the file is downloaded into the given path.
- `segments`: The number of segments the file should be divided in multi-threaded download. The default value is 10.
- `display`: Whether to display download progress and other optional messages. The default value is `True`.
- `multithread`: Whether to use multi-threaded download. The default value is `True`.
- `block`: Whether to block until the download is complete. The default value is `True`.
- `retries`: The number of times to retry the download in case of an error. The default value is 0.
- `mirror_func`: A function to get a new download URL in case of an error.
- `etag`: Whether to validate etag before resuming downloads. The default value is `True`.

### Examples

Here is an example that demonstrates how to use pypdl library to download a file using headers, proxies and authentication:

```py
from pypdl import Downloader

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

    # create a new downloader object
    dl = Downloader(headers=headers, proxies=proxies, auth=auth)

    # start the download
    dl.start(
        url='https://speed.hetzner.de/100MB.bin',
        file_path='100MB.bin',
        segments=10,
        display=True,
        multithread=True,
        block=True,
        retries=3,
        mirror_func=None,
        etag=True,
    )

if __name__ == '__main__':
    main()
```

This example downloads a file from the internet using 10 threads and displays the download progress. If the download fails, it will retry up to 3 times. we are also using headers, proxies and authentication.

Another example of implementing pause resume functionality and printing the progress to console:

```py
from pypdl import Downloader
from threading import Event

# create a downloader object
dl = Downloader()

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

Another example of using hash validation:

```py
from pypdl import Downloader

# create a downloader object
dl = Downloader()

# if block = True --> returns a FileValidator object
file = dl.start('https://example.com/file.zip', block=True) 

# validate hash
if file.validate_hash(correct_hash,'sha256'):
    print('Hash is valid')
else:
    print('Hash is invalid')

# if block = False --> returns a AutoShutdownFuture object
file = dl.start('https://example.com/file.zip', block=False)

# do something
# ...

# validate hash
if dl.completed:
  if file.result().validate_hash(correct_hash,'sha256'):
      print('Hash is valid')
  else:
      print('Hash is invalid')
```

## API Reference

### `Downloader()`

The `Downloader` class represents a file downloader that can download a file from a given URL to a specified file path. The class supports both single-threaded and multi-threaded downloads and many other features like retry download incase of failure and option to continue downloading using a different url if necessary, pause/resume functionality, progress tracking etc.

#### Keyword Arguments

- `params`: (dict, Optional) A dictionary, list of tuples or bytes to send as a query string. Default is None.
- `allow_redirects`: (bool, Optional) A Boolean to enable/disable redirection. Default is True.
- `auth`: (tuple, Optional) A tuple to enable a certain HTTP authentication. Default is None.
- `cert`: (str or tuple, Optional) A String or Tuple specifying a cert file or key. Default is None.
- `cookies`: (dict, Optional) A dictionary of cookies to send to the specified url. Default is None.
- `headers`: (dict, Optional) A dictionary of HTTP headers to send to the specified url. Default is None.
- `proxies`: (dict, Optional) A dictionary of the protocol to the proxy url. Default is None.
- `timeout`: (number or tuple, Optional) A number, or a tuple, indicating how many seconds to wait for the client to make a connection and/or send a response. Default is 20 seconds.
- `verify`: (bool or str, Optional) A Boolean or a String indication to verify the servers TLS certificate or not. Default is True.

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

#### Methods

- `start(url, file_path, segments=10, display=True, multithread=True, block=True, retries=0, mirror_func=None, etag=False)`: Starts the download process.

    ##### Parameters

    - `url`: (str) The download URL.
    - `file_path`: (str, Optional) The optional file path to save the download. By default, it uses the present working directory. If `file_path` is a directory, then the file is downloaded into it; otherwise, the file is downloaded with the given name.
    - `segments`: (int, Optional) The number of segments the file should be divided into for multi-threaded download.
    - `display`: (bool, Optional) Whether to display download progress and other optional messages.
    - `multithread`: (bool, Optional) Whether to use multi-threaded download.
    - `block`: (bool, Optional) Whether to block until the download is complete.
    - `retries`: (int, Optional) The number of times to retry the download in case of an error.
    - `mirror_func`: (function, Optional) A function to get a new download URL in case of an error.
    - `etag`: (bool, Optional) Whether to validate etag before resuming downloads.

    ##### Returns
    
    - `AutoShutdownFuture`: If `block` is `False`.
    - `FileValidator`: If `block` is `True` and the download is successful.
    - `None`: If `block` is `True` and the download fails.

- `stop()`: Stops the download process.

### Helper Classes

#### `Basicdown()`

The `Basicdown` class is the base downloader class that provides the basic structure for downloading files.

##### Attributes

- `curr`: The current size of the downloaded file in bytes.
- `completed`: A flag that indicates if the download is complete.
- `id`: The ID of the current instance.
- `stop`: An event that can be used to stop the download process.
- `error`: An event that can be used to signal an error.

##### Methods

- `download(url, path, mode, **kwargs)`: Downloads data in chunks.

#### `Simpledown()`

The `Simpledown` class extends `Basicdown` and is responsible for downloading a whole file in a single segment.

##### Parameters

- `url`: Url of the file.
- `file_path`: Path to save the file.
- `stop`: Stop event.
- `error`: Error event.
- `**kwargs`: Additional keyword arguments.

##### Methods

- `worker()`: Downloads a whole file in a single segment.

#### `Multidown()`

The `Multidown` class extends `Basicdown` and is responsible for downloading a specific segment of a file.

##### Parameters

- `segement_table`: Dictionary that contains the download information.
- `segment_id`: ID of the download part.
- `stop`: Stop event.
- `error`: Error event.
- `**kwargs`: Additional keyword arguments.

##### Methods

- `worker()`: Downloads a part of the file in multiple segments.

#### `FileValidator()`

The `FileValidator` class is used to validate the integrity of the downloaded file.

##### Parameters

- `path`: The path of the file to be validated.

##### Methods

- `calculate_hash(algorithm, **kwargs)`: Calculates the hash of the file using the specified algorithm. Returns the calculated hash as a string.

- `validate_hash(correct_hash, algorithm, **kwargs)`: Validates the hash of the file against the correct hash. Returns `True` if the hashes match, `False` otherwise.

  `calculate_hash` and `validate_hash` can support additional keyword arguments from the [hashlib module](https://docs.python.org/3/library/hashlib.html#hashlib.new).

#### `AutoShutdownFuture()`

The `AutoShutdownFuture` class is a wrapper for concurrent.futures.Future object that shuts down the executor when the result is retrieved.

##### Parameters

- `future`: The Future object to be wrapped.
- `executor`: The executor to be shut down when the result is retrieved.

##### Methods

- `result(timeout=None)`: Retrieves the result of the Future object and shuts down the executor. If the download was successful, it returns a `FileValidator` object; otherwise, it returns `None`.

## License

pypdl is licensed under the MIT License. See the [LICENSE](https://github.com/mjishnu/pypdl/blob/main/LICENSE) file for more details.

## Contribution

Contributions to pypdl are always welcome. If you want to contribute to this project, please fork the repository and submit a pull request.

## Contact

If you have any questions, issues, or feedback about pypdl, please open an issue on the [GitHub repository](https://github.com/mjishnu/pypdl).
