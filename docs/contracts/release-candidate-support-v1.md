# CRC-CICADAPORT-3.2.11-001

Contract version: `1.0-CANDIDATA`

Authorized base:

- `main@5229329b05a354be953cd885ca46ea0a84b7cada`
- signed tag `subhito-3.2.10`
- annotated object `05fc501745bcf203941ab591738e388de93cf454`

## DT-05

- The application follows Semantic Versioning.
- Python metadata uses `3.0.0rc1`; human SemVer uses `3.0.0-rc.1`.
- `src/version.py` is the only programmatic version source.
- `SCAN_CONTRACT_VERSION` and `BANNER_CONTRACT_VERSION` remain `1`.
- RC1 is a prerelease and not a production declaration.
- `v3.0.0-rc.1` requires separate authorization.

## DT-06

RC1 supports only Linux x86_64, Ubuntu 22.04/24.04, Python 3.10-3.13,
Rust 1.97.1 and Go 1.26.5. Windows, macOS, ARM64 and Python 3.14 are not
supported by this candidate.

## Distribution invariants

- The wheel contains both mandatory native executables.
- The sdist contains all Python, Rust and Go sources needed to build it.
- Installed execution does not depend on checkout-relative binaries.
- Rust remains mandatory for public TCP scanning.
- Go remains mandatory when banners are requested.
- No public engine selector or Python fallback is introduced.
- All automated network checks use loopback.
