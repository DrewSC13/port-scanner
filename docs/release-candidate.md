# CicadaPort 3.0.0-rc.1 release-candidate gate

| Layer | Candidate support |
| --- | --- |
| Operating system | Ubuntu 22.04 and Ubuntu 24.04 |
| Architecture | Linux x86_64 |
| Python | 3.10, 3.11, 3.12, 3.13 |
| Rust | 1.97.1 |
| Go | 1.26.5 |
| Wheel | Linux x86_64 with native engines |
| Source distribution | Python, Rust and Go sources |
| Network tests | Loopback only |

Windows, macOS, ARM64 and Python 3.14 are explicitly unsupported in RC1.

The candidate build produces a Linux wheel, a source distribution,
`SHA256SUMS` and `COMPONENTS.json`. Wheel and sdist must install in fresh
environments outside the checkout and pass native loopback smoke tests.

`subhito-3.2.11` is the future technical-freeze tag; `v3.0.0-rc.1` is the
future user-facing prerelease tag. Neither is authorized by implementation.
