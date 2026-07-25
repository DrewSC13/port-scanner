# Contrato canónico de resultados v1

**Autoridad:** `CCR-CICADAPORT-3.2.10-001`, versión `1.0-CANDIDATA`
**Estado:** aprobado para implementación, pendiente de validación y cierre
**Base:** `main@a0bb081a0b8b1d14ff5432d469e68780b8813142`

## Fuente de verdad

- `state` es la fuente de verdad del estado de puerto.
- `evidence.reason` es la fuente de verdad de la razón.
- `reason` debe ser exactamente igual a `evidence.reason`.
- `is_open` se conserva en v1 únicamente como proyección derivada de `state`.
- un resultado es reportable únicamente cuando `state == open`.

## Proyección compatible

| `state` | `is_open` |
| --- | --- |
| `open` | `true` |
| `closed` | `false` |
| `filtered` | `false` |
| `unfiltered` | `null` |
| `open|filtered` | `null` |
| `closed|filtered` | `null` |

Las entradas heredadas sin `state` pueden adaptarse de forma explícita:
`true → open`, `false → closed`, `null → open|filtered`. Una entrada heredada
no equivale por sí sola a un registro JSONL nativo v1.

## DT-03

`ScanResult` y el ciclo de resultados externos de `PortScanner` son
infraestructura de producción. Las implementaciones Python de TCP, UDP y
banners permanecen como referencia interna, soporte de pruebas y paridad. No
son motores públicos, no son fallback y no se deprecian ni retiran en `2.2.0`.

## Compatibilidad

- `contract_version` permanece en `1`.
- Rust conserva `port_result` JSONL incremental.
- Go conserva `banner_result` v1 sin cambios.
- JSON conserva `is_open`.
- TXT, JSON, CSV, HTML, CLI y TUI seleccionan resultados mediante `state`.
- La invocación nativa `--request-stdin` permanece congelada.

## Límites

Este contrato no habilita descubrimiento de hosts, ICMP, ARP, técnicas raw,
SYN scan, nuevas modalidades UDP, vulnerabilidades, explotación, escaneo
externo, selectores públicos de motores, fallback Python, cambios de versión,
Subhito 3.2.11, Subhito 3.2.12 ni Hito 4.
