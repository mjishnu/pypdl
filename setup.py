from setuptools import setup, find_packages

VERSION = '0.1.0'
DESCRIPTION = 'A Download Manager for python'
LONG_DESCRIPTION = 'A python concurrent python downloader with resume capablities.'

# Setting up
setup(
    name="pypdl",
    version=VERSION,
    author="m-jishnu",
    author_email="<jishnum499@gmail.com>",
    description=DESCRIPTION,
    long_description_content_type="text/markdown",
    long_description=LONG_DESCRIPTION,
    packages=find_packages(),
    install_requires=['requests','reprint'],
    keywords=['python', 'downloader', 'concurrent-downloader', 'parrel-downloader', 'download manager', 'fast-downloader'],
    classifiers=[
        "Development Status: 3 - Alpha",
        "Intended Audience: Developers",
        "Programming Language: Python3",
        "Operating System: Linux",
        "Operating System: MacOS",
        "Operating System: Windows",
    ]
)