# Procedimiento de aceptación de SUBTASK 5.2

Contrato: `CEPH-CICADAPORT-5.2-ACCEPTANCE-001`.

La aceptación oficial se ejecuta mediante:

```bash
EVIDENCE_ROOT=/home/cicada/Development/GitHub/port-scanner-local-patches/task-5-2-evidence \
./scripts/run_task_5_2_acceptance.sh
```

Los casos de rendimiento se ejecutan en procesos aislados para que la carga
de una medición no altere la siguiente. El runner descubre la evidencia congelada más reciente
`task-5-1-baseline.json`, verifica su `SHA256SUMS` y genera un log completo con
ruta, SHA-256 y código de retorno. No abre red ni invoca los motores Rust/Go.

Debe comprobar:

1. suite focalizada del Store v2 y Secure Artifact Writer;
2. comparación v2 de 500 puertos contra la medición v1 congelada de 5.1;
3. speedup v2 de al menos `5x`;
4. ejecución sintética de los `65.535` puertos TCP en un máximo de `60 s`;
5. máximo de tres archivos SQLite y `64 MiB` para el rango completo;
6. latencia p95 de commits por lote no superior a `100 ms`;
7. confirmación balanced por `N=128` o `T=250 ms`, lo que ocurra primero;
8. cancelación controlada y persistida en un máximo de `1 s`;
9. recuperación real tras `SIGKILL`, rollback del cambio no confirmado y
   reanudación desde 128 hasta 256 resultados;
10. migración v1 read-only, idempotente y auditada;
11. reportes `0700/0600` y neutralización de controles hostiles;
12. JSON, Markdown, `SHA256SUMS` y log en modo `0600`;
13. integridad del staging y ausencia de cambios Rust/Go.

Los umbrales son puertas candidatas de SUBTASK 5.2 para Linux x86_64. No
constituyen todavía un SLA de producto ni reemplazan soak, chaos, power-loss o
pruebas sobre almacenamiento empresarial posteriores.

## Incidencia AC-001 — raíz compartida `/dev/shm`

La primera invocación del runner se detuvo antes de la aceptación porque intentó
aplicar `chmod 700` directamente sobre `/dev/shm`. Esa raíz compartida puede ser
escribible sin pertenecer al usuario y no debe cambiarse. El runner corregido crea
un subdirectorio privado y único bajo `/dev/shm` —o bajo el fallback de evidencia—,
solo modifica permisos sobre ese subdirectorio e inicializa el log antes de preparar
el área temporal. No se modificó Session Store v2, Secure Artifact Writer, Rust ni Go.

## Incidencia FV-001 — compatibilidad de lectores v1 y CSV endurecido

La primera validación integral posterior a la aceptación detectó cuatro regresiones:
tres lectores de compatibilidad v1 intentaban abrir `CURRENT.json` aunque la sesión
ya se persistía exclusivamente en SQLite v2, y una expectativa histórica de CSV
conservaba un BOM invisible que el contrato endurecido debe representar de forma
visible. La corrección hace que los lectores `SingleTargetCheckpointStore` y
`MultiTargetCheckpointStore` deleguen en v2 cuando existe `session-v2.sqlite3`,
sin materializar generaciones v1 ni degradar la migración. El importador v1 usa
ahora lectores explícitamente legados para evitar ciclos o fuentes desactualizadas.
La prueba CSV exige `\\ufeff` visible y ausencia del carácter BOM real. No se
modificaron Rust, Go ni la versión de los contratos públicos.
