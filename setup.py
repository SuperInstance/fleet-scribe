from setuptools import setup, find_packages

with open("README.md") as f:
    long_description = f.read()

setup(
    name="fleet-scribe",
    version="0.1.0",
    description="One command. Sits beside any app. Builds a PLATO twin.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/SuperInstance/fleet-scribe",
    packages=find_packages(),
    entry_points={"console_scripts": ["scribe=fleet_scribe.scribe:cli"]},
    python_requires=">=3.8",
    install_requires=[
        "plato-sdk>=1.8.9",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
