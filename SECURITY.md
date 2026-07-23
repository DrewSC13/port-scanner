# Security Policy

CicadaPort is intended only for systems you own or are explicitly authorized
to assess.

## Supported versions

The project is currently under active development and has not yet declared a
production-ready release.

| Version | Security fixes |
| --- | --- |
| `main` | Yes |
| Earlier commits, forks, or unmaintained releases | No |

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, discussion, pull
request, or proof-of-concept repository.

Use GitHub's private vulnerability reporting for this repository when it is
available. Include:

- the affected commit or version;
- the affected component: Python, Rust, Go, Bash, packaging, or CI;
- reproducible steps using only local or explicitly authorized targets;
- the security impact and expected behavior;
- a minimal proof of concept with secrets and personal data removed.

If private vulnerability reporting is unavailable, open a public issue that
only requests a private contact channel. Do not include vulnerability details
in that issue.

Reports will be assessed before a disclosure or release date is agreed. Please
allow maintainers a reasonable opportunity to investigate and correct the
problem before public disclosure.

## Out of scope

- scanning third-party systems without explicit authorization;
- social engineering, denial of service, or destructive testing;
- reports that only show an outdated dependency without a reachable impact;
- vulnerabilities in an operating system or external service not caused by
  CicadaPort.
