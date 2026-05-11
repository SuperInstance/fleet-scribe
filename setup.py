from setuptools import setup, find_packages
setup(
    name="fleet-scribe",
    version="0.1.0",
    description="Download-and-try digital twin builder. Sits beside any app, builds a PLATO twin.",
    packages=find_packages(),
    entry_points={"console_scripts": ["scribe=fleet_scribe.scribe:cli"]},
    python_requires=">=3.8",
)
