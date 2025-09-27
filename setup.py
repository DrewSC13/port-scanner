from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="portscanner-pro",
    version="2.0.0",
    author="Security Team",
    author_email="security@example.com",
    description="Escáner de puertos profesional para auditorías de seguridad",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Security",
        "Topic :: System :: Networking",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "portscanner=main:main",
        ],
    },
)