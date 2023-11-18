# pypdl

pypdl is a Python library for downloading files from the internet. It provides features such as multi-threaded downloads, retry download incase of failure and option to continue downloading using a different url if necessary, progress tracking, pause/resume functionality and many more.

## Installation

To install the pypdl, run the following command:

```
pip install pypdl
```

## Usage

### Basic Usage

To download a file using the pypdl, simply create a new `Downloader` object and call its `start` method, passing in the URL of the file to be downloaded and the path where it should be saved:

```python
from pypdl import Downloader

dl = Downloader()
dl.start('http://example.com/file.txt', 'file.txt')
```

### Advanced Usage

The `Downloader` object provides additional options for advanced usage:

```python
dl.start(
    url='http://example.com/file.txt',  # URL of the file to download
    filepath='file.txt',  # path to save the downloaded file
    num_connections=10,  # number of connections to use for a multi-threaded download
    display=True,  # whether to display download progress
    multithread=True,  # whether to use multi-threaded download
    block=True,  # whether to block until the download is complete
    retries=0,  # number of times to retry the download in case of an error
    retry_func=None,  # function to call to get a new download URL in case of an error
)
```

The `num_connections` option specifies the number of threads to use for a multi-threaded download. The default value is 10.

The `display` option specifies whether to display download progress. The default value is `True`.

The `multithread` option specifies whether to use multi-threaded download. The default value is `True`.

The `block` option specifies whether to block until the download is complete. The default value is `True`.

The `retries` option specifies the number of times to retry the download in case of an error. The default value is 0.

The `retry_func` option specifies a function to call to get a new download URL in case of an error.

### Example

Here is an example that demonstrates how to use pypdl library to download a file from the internet:

```python
from pypdl import Downloader

def main():
    # create a new downloader object
    dl = Downloader()

    # Use custom headers to set user-agent
    dl.headers = {"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0"}
    # Use custom proxies
    dl.proxies = {
                    "http": "http://10.10.1.10:3128",
                    "https": "https://10.10.1.10:1080",
                }
    # Use authentication for proxy
    dl.auth = ("user","pass")

    # start the download
    dl.start(
        url='https://speed.hetzner.de/100MB.bin',
        filepath='100MB.bin',
        num_connections=10,
        display=True,
        multithread=True,
        block=True,
        retries=3,
        retry_func=None,
    )

if __name__ == '__main__':
    main()
```

This example downloads a large file from the internet using 10 threads and displays the download progress. If the download fails, it will retry up to 3 times. we are aso using a custom header to set user-agent

Another example of using a custom stop event and printing the progress to console:

```python
from pypdl import Downloader
from threading import Event

# create a custom stop event
stop = Event()

# create a downloader object
dl = Downloader(stop)

# start the download process
# block=False so we can print the progress
# display=False so we can print the progress ourselves
dl.start('https://example.com/file.zip', 'file.zip', num_connections=8,block=False,display=False)

# print the progress
while dl.progress != 70:
  print(dl.progress)

# stop the download process
stop.set() # can also be done by calling d.stop()

#do something
#...

# resume the download process
dl.start('https://example.com/file.zip', 'file.zip', num_connections=8,block=False,display=False)

# print rest of the progress
while dl.progress != 100:
  print(dl.progress)

```

This example we create a custom **stop event** and pass it to the **Downloader** object. We then start the download process and print the progress to console. We then stop the download process and do something else. After that we resume the download process and print the rest of the progress to console. This can be used to create a pause/resume functionality.

## API Reference

### `Downloader()`

The `Downloader` class represents a file downloader that can download a file from a given URL to a specified file path. The class supports both single-threaded and multi-threaded downloads and many other features like retry download incase of failure and option to continue downloading using a different url if necessary, pause/resume functionality, progress tracking etc.

#### Parameters

-   `StopEvent`: An optional parameter to set custom a stop event.
-   `header`: An optional parameter to set custom header. (Note: Never use custom "range" header if using multithread = True)
-   `proxies`: An optional parameter to set custom proxies.
-   `auth`: An optional parameter to set authentication for proxies.

#### Attributes

-   `totalMB`: The total size of the file to be downloaded, in MB.
-   `progress`: The download progress percentage.
-   `speed`: The download speed, in MB/s.
-   `download_mode`: The download mode: single-threaded or multi-threaded.
-   `time_spent`: The time spent downloading, in seconds.
-   `doneMB`: The amount of data downloaded so far, in MB.
-   `eta`: The estimated time remaining for download completion, in the format "HH:MM:SS".
-   `remaining`: The amount of data remaining to be downloaded, in MB.
-   `Stop`: An event that can be used to stop the download process.
-   `headers`: A dictionary containing user headers.
-   `proxies`: A dictionary containing user proxies.
-   `auth`: A tuple containing authentication for proxies.
-   `Failed`: A flag that indicates if the download failed.

#### Methods

-   `start(url, filepath, num_connections=10, display=True, multithread=True, block=True, retries=0, retry_func=None)`: Starts the download process. Parameters:
    -   `url` (str): The download URL.
    -   `filepath` (str):  The optional file path to save the download. by default it uses the present working directory, If filepath a is directory then the file is downloaded into the it else the file is downloaded with the given name.
    -   `num_connections` (int): The number of connections to use for a multi-threaded download.
    -   `display` (bool): Whether to display download progress.
    -   `multithread` (bool): Whether to use multi-threaded download.
    -   `block` (bool): Whether to block until the download is complete.
    -   `retries` (int): The number of times to retry the download in case of an error.
    -   `retry_func` (function): A function to call to get a new download URL in case of an error.
-   `stop()`: Stops the download process.

### Helper Classes

#### `Multidown()`

The `Multidown` class represents a download worker that is responsible for downloading a specific part of a file in multiple chunks.

##### Parameters

-   `dic`: Dictionary that contains the download information.
-   `id`: ID of the download part.
-   `stop`: Stop event.
-   `error`: Error event.
-   `headers`: Custom headers.
-   `proxies`: Custom proxies.
-   `auth`: Authentication for proxies.

##### Attributes

-   `curr`: The current size of the downloaded file.
-   `completed`: Whether the download for this part is complete.
-   `id`: The ID of this download part.
-   `dic`: A dictionary containing download information for all parts.
-   `stop`: An event that can be used to stop the download process.
-   `error`: An event that can be used to signal an error.
-   `headers`: A dictionary containing user headers.
-   `proxies`: A dictionary containing user proxies.
-   `auth`: A tuple containing authentication for proxies.

##### Methods

-   `getval(key)`: Gets the value of a key from the dictionary.
-   `setval(key, val)`: Sets the value of a key in the dictionary.
-   `worker()`: Downloads a part of the file in multiple chunks.

#### `Singledown()`

The `Singledown` class represents a download worker that is responsible for downloading a whole file in a single chunk.

##### Parameters

-   `url`: Url of the file.
-   `path`: Path to save the file.
-   `stop`: Stop event.
-   `error`: Error event.
-   `headers`: User headers.
-   `proxies`: Custom proxies.
-   `auth`: Authentication for proxies.

##### Attributes

-   `curr`: The current size of the downloaded file.
-   `completed`: Whether the download is complete.
-   `url`: The URL of the file to download.
-   `path`: The path to save the downloaded file.
-   `stop`: Event to stop the download.
-   `error`: Event to indicate an error occurred.
-   `headers`: Custom user headers.
-   `proxies`: A dictionary containing user proxies.
-   `auth`: A tuple containing authentication for proxies.

##### Methods

-   `worker()`: Downloads a whole file in a single chunk.

## License

The `pypdl` library is distributed under the MIT License. See the [LICENSE](https://github.com/m-jishnu/pypdl/blob/main/LICENSE) file for more information.

## Contribution

Contributions are welcome! If you encounter any issues or have suggestions for improvements, please open an issue on the [GitHub repository](https://github.com/m-jishnu/pypdl).

## Contact

For any inquiries or questions, you can reach out to the author via email at [mjishnu@skiff.com](mailto:mjishnu@skiff.com).
