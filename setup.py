from pathlib import Path

from setuptools import find_packages, setup


PROJECT_ROOT = Path(__file__).resolve().parent
LONG_DESCRIPTION = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="portscanner-pro",
    version="2.2.0",
    author="Security Team",
    author_email="security@example.com",
    description="CicadaPort: escáner de puertos multi-engine para auditorías autorizadas",
    license="MIT",
    license_files=["LICENSE.md"],
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    packages=find_packages(include=["src", "src.*"]),
    py_modules=["config", "main"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Information Technology",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Security",
        "Topic :: System :: Networking",
    ],
    python_requires=">=3.10",
    install_requires=[
        "textual>=0.80",
    ],
    entry_points={
        "console_scripts": [
            "cicadaport=main:main",
            "portscanner=main:main",
        ],
    },
)
