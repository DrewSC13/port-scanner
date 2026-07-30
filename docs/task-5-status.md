# Estado formal de TASK 5

```text
TASK_4=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
TASK_4_CLOSURE_COMMIT=bfaa7e6c2989dc923b418862ce9243e68e3f569c
TASK_4_SIGNED_TAG=task-4
TASK_5=IN_IMPLEMENTATION
TASK_5_BRANCH=feat/task-5-enterprise-engine-production-hardening
SUBTASK_5_1=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_5_1_COMMIT=045dabda6eea840e3cbe065407e7132d88ba9963
SUBTASK_5_1_CI_RUN=30506742043
SUBTASK_5_2=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_5_2_COMMIT=8ce44caebf90519867d0da7a53a0ec71372cd741
SUBTASK_5_2_CI_RUN=30548790956
SUBTASK_5_3=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
SUBTASK_5_3_COMMIT=7bac7fff3c2f0e14db74505923e0e5f64edc7eb7
SUBTASK_5_3_CI_RUN=30556210226
SUBTASK_5_4=IN_MATERIAL_IMPLEMENTATION
SUBTASK_5_4_BASE=7bac7fff3c2f0e14db74505923e0e5f64edc7eb7
SUBTASK_5_5=BLOCKED_NOT_STARTED
SUBTASK_5_6=BLOCKED_NOT_STARTED
```

## SUBTASK 5.1 — Arquitectura, contratos y baseline empresarial

La autorización de SUBTASK 5.1 permite exclusivamente:

- contratos candidatos de TASK 5 y de sus componentes v2;
- modelo de amenazas y arquitectura objetivo;
- instrumentación de benchmarks aislada del runtime público;
- medición reproducible sobre loopback;
- evidencia auditable y presupuestos de producción.

No autoriza modificaciones materiales en:

- `src/session*.py` ni el Session Store v1;
- `rust-core/`;
- `go-banner/`;
- CLI, TUI, reportes públicos ni workflows;
- contratos JSONL, sesión, resultados o eventos v1;
- versión pública `3.0.0-rc.1`.

## Entregables candidatos de 5.1

| Entregable | Identificador | Estado |
| --- | --- | --- |
| Contrato general TASK 5 | `CEPH-CICADAPORT-TASK-5-001` | CANDIDATE |
| Arquitectura objetivo | `ARCH-CICADAPORT-5.1-001` | CANDIDATE |
| Modelo de amenazas | `TM-CICADAPORT-5.1-001` | CANDIDATE |
| Baseline reproducible | `CEPH-CICADAPORT-5.1-BL-001` | EXECUTED_REVIEWED_PASS |
| Baseline suplementaria de recursos | `CEPH-CICADAPORT-5.1-RB-001` | EXECUTED_REVIEWED_PASS; RB-001_PRESERVED_CORRECTED |
| Session Store v2 | `SSV2-CICADAPORT-5.2-001` | CANDIDATE |
| Rust TCP Engine v2 | `RTEV2-CICADAPORT-5.3-001` | CANDIDATE |
| Go Service Evidence v2 | `GSEV2-CICADAPORT-5.4-001` | CANDIDATE |
| Artefactos seguros v2 | `SAV2-CICADAPORT-5.2-002` | CANDIDATE |

## Barrera de implementación

Ningún contrato candidato se vuelve ejecutable por su mera presencia. La
implementación funcional de 5.2, 5.3 o 5.4 exige:

1. baseline primaria y suplemento de recursos ejecutados;
2. evidencia hasheada y asociada al commit de 5.1;
3. revisión de resultados y presupuestos;
4. cierre firmado de SUBTASK 5.1;
5. autorización formal de la siguiente subtask.


## SUBTASK 5.2 — Cerrada y congelada

Session Store v2, migración v1→v2, recuperación transaccional y Secure Artifact
Writer quedaron cerrados y congelados sobre
`8ce44caebf90519867d0da7a53a0ec71372cd741`, con CI remoto `30548790956` en
estado `success`. Las incidencias `AC-001`, `FV-001` y `CV-001` están cerradas.

## SUBTASK 5.3 — Cerrada y congelada

Rust TCP Engine v2 quedó cerrado y congelado sobre
`7bac7fff3c2f0e14db74505923e0e5f64edc7eb7`, con CI remoto `30556210226` en
estado `success`. Se preservan `tcp_connect`, el contrato público v1 y las
barreras contra técnicas raw.

## SUBTASK 5.4 — Implementación material autorizada

Alcance activo:

- streaming incremental de un resultado por endpoint concluido;
- concurrencia y canales acotados con backpressure;
- cancelación determinista ante cierre del consumidor;
- timeouts internos por conexión, TLS, escritura, primer byte, lectura ociosa y
  duración total;
- lectura incremental limitada, hash y metadatos de truncamiento;
- evidencia TLS separando negociación, presencia y verificación;
- sanitización de terminal, controles bidi e invisibles;
- registro versionado con probes `passive` y `safe` habilitados por defecto;
- benchmark y aceptación exclusivamente sobre loopback.

Restricciones activas:

- SUBTASK 5.1, SUBTASK 5.2 y SUBTASK 5.3 permanecen cerradas y congeladas;
- `rust-core/` y Session Store v2 no pueden modificarse materialmente;
- `banner_request` y `banner_result` públicos permanecen en versión 1;
- no se añaden detección de vulnerabilidades ni probes `restricted` por defecto;
- SUBTASK 5.5 y SUBTASK 5.6 continúan bloqueadas;
- el cierre de 5.4 exige aceptación, validación integral, commit firmado, CI
  remoto verde y aprobación formal del Arquitecto del Proyecto.
