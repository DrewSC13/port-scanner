# CicadaPort 3.0.0-rc.2 enterprise release-candidate gate

| Layer | Candidate support |
| --- | --- |
| Operating system | Ubuntu 22.04 and Ubuntu 24.04 |
| Architecture | Linux x86_64 |
| Python | 3.10, 3.11, 3.12, 3.13 |
| Rust | 1.97.1 |
| Go | 1.26.5 |
| Wheel | Linux x86_64 with mandatory native engines |
| Source distribution | Python, Rust and Go sources |
| Network tests | Loopback only |
| Public contracts | JSONL v1; service evidence v2 |

Windows, macOS, ARM64 and Python 3.14 are explicitly unsupported in RC2.

The candidate build produces a Linux wheel, a source distribution, CycloneDX
1.6 SBOM, build identity manifest, component inventory and SHA-256 manifests.
Wheel and sdist must install in fresh environments outside the checkout and
pass native loopback smoke tests. The complete artifact set must be reproducible
and bound to signed SLSA/Sigstore attestations in CI.

`3.0.0-rc.2` is prepared under `EIVRC-CICADAPORT-5.6-001`. Implementation and
CI artifact upload do not authorize `main` integration, a `v3.0.0-rc.2` tag,
GitHub Release publication or package publication. Those operations require a
separate Phase F authorization.
