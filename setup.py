from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in mobilepos/__init__.py
from mobilepos import __version__ as version

setup(
	name="mobilepos",
	version=version,
	description="pos for mobile applications",
	author="Kossivi Amouzou",
	author_email="dodziamouzou@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
