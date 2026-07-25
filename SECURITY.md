# Security Policy

CicadaPort is intended only for systems you own or are explicitly authorized
to assess. Every expanded target, range, CIDR entry and target-file record
must remain inside the authorized scope.

## Supported versions

CicadaPort `3.0.0-rc.1` is a release candidate, not a production-ready
release. Verified support is limited to Linux x86_64 on Ubuntu 22.04 and
Ubuntu 24.04 with Python 3.10 through 3.13.

| Version | Security fixes | Release state |
| --- | --- | --- |
| `main` | Yes | Active development |
| `3.0.0-rc.1` | Yes while current | Prerelease |
| Earlier commits or unmaintained releases | No | Unsupported |

Windows, macOS, ARM64 and Python 3.14 are not supported by RC1.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, discussion,
pull request or proof-of-concept repository. Use GitHub private vulnerability
reporting when available and include the affected commit/version, component,
authorized reproduction, impact and sanitized proof of concept.

If private reporting is unavailable, open a public issue requesting a private
contact channel without including vulnerability details.

## Out of scope

- unauthorized third-party scanning;
- social engineering, denial of service or destructive testing;
- dependency-version reports without reachable impact;
- flaws in external systems not caused by CicadaPort.
