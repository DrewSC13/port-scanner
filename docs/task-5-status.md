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
SUBTASK_5_2=IN_MATERIAL_IMPLEMENTATION
SUBTASK_5_2_BASE=045dabda6eea840e3cbe065407e7132d88ba9963
SUBTASK_5_3=BLOCKED_NOT_STARTED
SUBTASK_5_4=BLOCKED_NOT_STARTED
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


## SUBTASK 5.2 — Implementación material autorizada

Alcance activo:

- Session Store v2 transaccional sobre SQLite WAL;
- persistencia incremental por `N=128` o `T=250 ms`;
- rango TCP completo, p95 de commits, cancelación y recuperación `SIGKILL`;
- migración read-only e idempotente desde stores v1;
- recuperación, auditoría y exportación portable;
- Secure Artifact Writer para reportes, eventos y bundles;
- pruebas y aceptación sin red externa.

Restricciones activas:

- SUBTASK 5.1 permanece cerrada y congelada;
- `rust-core/` y `go-banner/` no pueden modificarse;
- los contratos públicos v1 permanecen estables;
- SUBTASK 5.3 y posteriores continúan bloqueadas;
- el cierre de 5.2 requiere evidencia, commit firmado, CI verde y aprobación
  formal del Arquitecto del Proyecto.
