#!/usr/bin/env python3
"""Execute no-argument static contracts using only the Python standard library."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
from pathlib import Path
import sys
from types import ModuleType
from typing import Callable


class StaticContractError(RuntimeError):
    """Raised when a static-contract module cannot be executed safely."""


TestFunction = Callable[[], None]


def load_contract_module(path: Path) -> ModuleType:
    resolved = path.resolve(strict=True)
    spec = importlib.util.spec_from_file_location(
        "cicadaport_static_contracts",
        resolved,
    )
    if spec is None or spec.loader is None:
        raise StaticContractError(
            f"Unable to load static-contract module: {resolved}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_tests(module: ModuleType) -> list[tuple[str, TestFunction]]:
    tests: list[tuple[str, TestFunction]] = []
    for name, candidate in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        if candidate.__module__ != module.__name__:
            continue
        parameters = inspect.signature(candidate).parameters
        if parameters:
            names = ", ".join(parameters)
            raise StaticContractError(
                f"Static contract {name} requires unsupported parameters: {names}"
            )
        tests.append((name, candidate))
    if not tests:
        raise StaticContractError("No static contract functions were discovered.")
    return tests


def run_tests(tests: list[tuple[str, TestFunction]]) -> None:
    for name, test in tests:
        try:
            test()
        except Exception as error:
            print(
                f"STATIC_CONTRACT_TEST={name}=FAIL:"
                f"{type(error).__name__}:{error}",
                file=sys.stderr,
            )
            raise
        print(f"STATIC_CONTRACT_TEST={name}=PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_module", type=Path)
    args = parser.parse_args()

    module = load_contract_module(args.contract_module)
    tests = discover_tests(module)
    run_tests(tests)

    print(f"STATIC_CONTRACT_TESTS={len(tests)}")
    print("STATIC_CONTRACTS=PASS")


if __name__ == "__main__":
    main()
