from setuptools import setup, find_packages

VERSION = '0.0.9'
DESCRIPTION = 'A concurrent python download manager'
with open("README.md", "r") as f:
    LONG_DESCRIPTION = f.read()

setup(
    name="pypdl",
    version=VERSION,
    author="m-jishnu",
    author_email="<jishnum499@gmail.com>",
    description=DESCRIPTION,
    long_description_content_type="text/markdown",
    long_description=LONG_DESCRIPTION,
    url="https://github.com/m-jishnu/pypdl",
    license='MIT',
    classifiers={
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    },
    packages=find_packages(),
    install_requires=['requests','reprint'],
    keywords=['python', 'downloader', 'concurrent-downloader', 'parrel-downloader', 'download manager', 'fast-downloader'],
)