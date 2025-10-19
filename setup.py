#!/usr/bin/env python3
"""
Setup script for WinSCP Manager
"""

from setuptools import setup, find_packages
import os

# Read the contents of README file
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

# Read requirements
with open(os.path.join(this_directory, 'requirements.txt'), encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='winscp-manager',
    version='1.0.0',
    author='Pandiyaraj Karuppasamy',
    description='A comprehensive Python application for managing WinSCP/SFTP file operations with scheduling',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/Pandiyarajk/winscp_tools',
    project_urls={
        'Bug Reports': 'https://github.com/Pandiyarajk/winscp_tools/issues',
        'Source': 'https://github.com/Pandiyarajk/winscp_tools',
        'Documentation': 'https://github.com/Pandiyarajk/winscp_tools/blob/main/README.md',
    },
    packages=find_packages(),
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: OS Independent',
        'Environment :: Console',
        'Environment :: X11 Applications',
    ],
    python_requires='>=3.7',
    install_requires=requirements,
    extras_require={
        'dev': [
            'pytest>=7.4.0',
            'pytest-cov>=4.1.0',
            'black>=23.7.0',
            'flake8>=6.1.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'winscp-manager=main:main',
        ],
    },
    include_package_data=True,
    package_data={
        'winscp_manager': ['*.ini'],
    },
    keywords='winscp sftp ftp file-transfer scheduler automation',
    license='MIT',
    zip_safe=False,
)
