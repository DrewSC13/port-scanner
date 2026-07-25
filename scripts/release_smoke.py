#!/usr/bin/env python3
"""Prueba funcional del paquete instalado fuera del checkout."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import version as distribution_version
from pathlib import Path
import os
import socket
import subprocess
import sys
import sysconfig
import tempfile
import threading

import src
from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.contracts import BANNER_CONTRACT_VERSION, SCAN_CONTRACT_VERSION
from src.native import PACKAGE_NATIVE_DIR
from src.version import __version__


def start_server(payload: bytes = b"") -> tuple[int, threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                if payload:
                    connection.sendall(payload)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, thread


def main() -> None:
    package_root = Path(src.__file__).resolve().parent
    cwd = Path.cwd().resolve()
    if cwd == package_root or cwd in package_root.parents:
        raise AssertionError("La prueba debe ejecutarse fuera del checkout.")
    if distribution_version("portscanner-pro") != __version__:
        raise AssertionError("La versión instalada no coincide con src.version.")

    rust_path = PACKAGE_NATIVE_DIR / "rust-core"
    go_path = PACKAGE_NATIVE_DIR / "go-banner"
    for binary in (rust_path, go_path):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise AssertionError(f"Binario instalado no ejecutable: {binary}")

    rust_port, rust_server = start_server()
    rust_results = RustScannerBridge().scan(
        "127.0.0.1", [rust_port], timeout=1.0, workers=1
    )
    rust_server.join(timeout=5)
    rust_result = rust_results[0]
    if rust_result["state"] != "open" or rust_result["is_open"] is not True:
        raise AssertionError(f"Resultado Rust inesperado: {rust_result}")
    if rust_result["contract_version"] != SCAN_CONTRACT_VERSION:
        raise AssertionError("Rust alteró la versión contractual.")

    banner_text = "CICADAPORT-RC-BANNER"
    go_port, go_server = start_server((banner_text + "\r\n").encode("ascii"))
    go_results = GoBannerBridge().grab_banners(
        "127.0.0.1", [go_port], timeout=1.0
    )
    go_server.join(timeout=5)
    go_result = go_results[0]
    if banner_text not in (go_result.get("banner") or ""):
        raise AssertionError(f"Resultado Go inesperado: {go_result}")
    if go_result["contract_version"] != BANNER_CONTRACT_VERSION:
        raise AssertionError("Go alteró la versión contractual.")

    scripts_directory = Path(sysconfig.get_path("scripts"))
    if scripts_directory != Path(sys.executable).parent:
        raise AssertionError(
            "El directorio de scripts no coincide con el entorno Python activo: "
            f"{scripts_directory} != {Path(sys.executable).parent}"
        )
    expected = f"CicadaPort {__version__}"
    for name in ("cicadaport", "portscanner"):
        completed = subprocess.run(
            [str(scripts_directory / name), "--version"],
            text=True,
            capture_output=True,
            check=True,
        )
        if completed.stdout.strip() != expected:
            raise AssertionError(f"Versión inesperada para {name}.")

    cicadaport = scripts_directory / "cicadaport"
    subprocess.run([str(cicadaport), "--help"], stdout=subprocess.DEVNULL, check=True)

    with tempfile.TemporaryDirectory(prefix="cicadaport-installed-cli-") as directory:
        cli_port, cli_server = start_server()
        completed = subprocess.run(
            [
                str(cicadaport), "127.0.0.1", "-p", str(cli_port),
                "--no-banner-grab", "--report-dir", directory,
            ],
            cwd=directory,
            text=True,
            capture_output=True,
            check=True,
        )
        cli_server.join(timeout=5)
        if "Puertos abiertos: 1" not in completed.stdout:
            raise AssertionError("La CLI instalada no confirmó el puerto loopback abierto.\n" + completed.stdout)

    import_module("src.tui")
    print(f"Installed release smoke: OK | version={__version__}")


if __name__ == "__main__":
    main()
