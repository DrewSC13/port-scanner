# SUBTASK 6.1 — Plan de auditoría del baseline operacional

## Identidad

```text
AUDIT=OPBASE-CICADAPORT-6.1-AUD-001
CONTRACT=OPBASE-CICADAPORT-6.1-BL-001
STATUS=INSTRUMENTED_PENDING_EXECUTION
```

## Superficie

La auditoría examina únicamente los seis archivos del primer bloque:

```text
docs/architecture/task-6-1-operational-architecture.md
docs/contracts/task-6-1-operational-baseline-candidate.md
docs/audits/task-6-1-operational-baseline.md
benchmarks/task_6_1_operational_baseline.py
scripts/run_task_6_1_operational_baseline.sh
tests/test_task_6_1_operational_baseline.py
```

## Pruebas

- sintaxis Python;
- pruebas focalizadas;
- ShellCheck y sintaxis Bash;
- ejecución `smoke`;
- validación del esquema;
- comprobación de permisos;
- verificación de `SHA256SUMS`;
- comparación del estado Git anterior y posterior;
- búsqueda negativa de sockets y capacidades raw.

## Criterios de aceptación

```text
FOCAL_TESTS=PASS
BASELINE_PROFILE=smoke|quick|full
EXTERNAL_NETWORK=DISABLED
EVIDENCE_HASHES=PASS
PRIVATE_PERMISSIONS=PASS
REPOSITORY_INTEGRITY=PASS
PRODUCTION_CODE_CHANGES=0
PUBLIC_CONTRACT_CHANGES=0
```

## Limitaciones

- El baseline no acredita disponibilidad ni SLO.
- Las latencias dependen del host y filesystem observados.
- No se infiere soporte desde una sola ejecución.
- No se ejecutan pruebas WAN ni red externa.
- La aceptación de este bloque no cierra SUBTASK 6.1.
