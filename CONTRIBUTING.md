# Contributing to CicadaPort

Thank you for helping improve CicadaPort. Contributions must preserve accurate
results, safe defaults, and the mandatory specialized flow implemented by
Python, Rust, and Go.

## Safety and authorization

Run network tests only against `127.0.0.1`, systems you own, or systems for
which you have explicit written authorization. Never add CI tests that depend
on public targets.

Security vulnerabilities must follow [SECURITY.md](SECURITY.md) and must not be
submitted through a public issue or pull request.

## Roadmap governance

[ROADMAP.md](ROADMAP.md) is the normative index for completed work, transitional
debt, dependencies, and the remaining Hito 3 sequence. A future entry marked
`DEFINED` is planning, not implementation authorization.

Roadmap changes must:

- distinguish frozen facts from proposals;
- preserve signed commit and tag references for closed subhitos;
- update status only when the required evidence exists;
- keep Hito 4 blocked until a separate formal authorization;
- remain atomic, signed, reviewable, and fully green in CI.

A functional subhito must update the affected documentation as part of its
controlled closing flow. Do not combine unrelated roadmap changes with
unapproved implementation work.

## Specialized public interface

The public CLI does not expose engine selectors. Contributions must preserve
these invariants:

- Rust is the mandatory public TCP engine.
- Go is the mandatory banner engine when `--banner-grab` is enabled.
- `--engine` and `--banner-engine` are not accepted public options.
- Legacy selector arguments must fail through `argparse` with exit code `2`
  before target resolution, binary preflight, network activity, or report
  creation.
- Programmatic requests must use the canonical internal values `rust` and `go`;
  incompatible values must fail before network activity.
- There is no silent fallback to the internal Python implementations.
- CLI, TUI, and reports must continue to expose the effective engine metadata.

## Development setup

Required toolchains:

- Python 3.10 or newer;
- stable Rust with `rustfmt` and Clippy;
- the Go version declared in `go-banner/go.mod`;
- Bash and ShellCheck.

Create a virtual environment and install development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Build the native engines:

```bash
./scripts/build_all.sh
```

## Required validation

Before every commit, run:

```bash
./scripts/test_all.sh
```

The full local validation must cover Python, Rust, Go, Bash, the bridges, the
localhost parity test, and both single-target and multi-target TUI contracts. A
commit must not be pushed while a required check is failing.

The focused commands used by CI are:

```bash
python -m pytest -v --cov=src --cov-report=term-missing
cargo fmt --manifest-path rust-core/Cargo.toml -- --check
cargo clippy --manifest-path rust-core/Cargo.toml --all-targets --all-features -- -D warnings
cargo test --manifest-path rust-core/Cargo.toml
go test -race ./...
bash -n scripts/*.sh
shellcheck scripts/*.sh
```

Run the Go commands from `go-banner/`.

## Result contract

- CLI and TUI must consume `ScanOrchestrator`; presentation code must not
  implement target parsing, resolution, concurrency, network scanning, banner
  capture, or report persistence.
- Single-target TUI sessions must dispatch through `ScanOrchestrator.run()`;
  multi-target TUI sessions must dispatch through `ScanOrchestrator.run_many()`.
- Every multi-target event rendered by the TUI must preserve the requested
  target and resolved address. Partial failures must remain isolated and visible.
- `safe`, `standard`, `deep`, and `custom` must remain deterministic and
  covered by tests.
- Cancellation must propagate to Python workers and native subprocesses.
- `PortScanner.results` contains one internal result for every requested port.
- Internal results may be open, closed, or filtered.
- Reportable results contain only entries where `is_open is True`.
- TXT, JSON, CSV, and HTML must apply the same reportable filter.
- Every CLI scan must display the complete ordered reportable result set.
- Automatic reports must be stored under `reports/` unless the user selects
  another report directory or supplies an explicit output path.
- Automatic report names must never overwrite an existing report.
- Internal Python fixtures and Rust must agree on open/closed states and
  statistics for the same deterministic localhost fixture.
- TCP scans must not send application payloads unless `--banner-grab` is set.
- Internal Python banner fixtures and Go must use the same TLS, probe,
  sanitization, and output-length policy.
- HTML must escape target and service data; CSV must neutralize formula cells.

Any change to this contract requires tests in the same commit.

## Commits and pull requests

- Start from an up-to-date `main`.
- Keep each commit atomic and independently green.
- Add a regression for every corrected defect.
- Do not commit generated reports, binaries, build directories, environments,
  caches, or credentials.
- Describe the behavior before and after the change in the pull request.
- Wait for the complete CI workflow to pass before merging.

Use clear commit messages such as:

```text
fix(scanner): enforce canonical result contract
test(integration): verify Python and Rust localhost parity
docs(project): add security and contribution policies
```
