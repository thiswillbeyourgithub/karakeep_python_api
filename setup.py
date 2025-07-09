import re
import os
from setuptools import find_packages, setup

with open("README.md", "r") as readme:
    long_description = readme.read()

setup(
    name="karakeep_python_api",
    version="1.2.3",
    description="Community python client for the Karakeep API.",  # Simplified description
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/thiswillbeyourgithub/karakeep_python_api/",
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    license="GPLv3",
    keywords=[
        "rss",
        "karakeep",
        "hoarder",
        "data-hoarding",
        "python",
        "api",
        "feeds",
        "openapi",
    ],
    python_requires=">=3.9",
    install_requires=[
        "requests >= 2.32.3",
        "loguru >= 0.7.3",
        "pydantic >= 2.0",  # For data validation and modeling based on datatypes.py
        "click >= 8.0",  # For the CLI
    ],
    extras_require={
        "dev": [
            # "openapi-pydantic >= 0.5.1", # For generating datatypes.py from OpenAPI spec
            "beartype >= 0.20.2",  # Optional runtime type checking
            "pytest >= 8.3.4",
            "build >= 1.2.2.post1",
            "twine >= 6.1.0",
            "bumpver >= 2024.1130",
        ],
    },
    entry_points={
        "console_scripts": [
            "karakeep=karakeep_python_api.__main__:cli",
        ],
    },
)
