# Auditoría de aceptación — SUBTASK 5.4

```text
CONTRACT=GSEV2-CICADAPORT-5.4-001
STATUS=INSTRUMENTED_PENDING_OFFICIAL_EXECUTION
AUTHORIZED_BASE=7bac7fff3c2f0e14db74505923e0e5f64edc7eb7
NETWORK_SCOPE=LOOPBACK_ONLY
EXTERNAL_NETWORK=DISABLED
```

## Controles obligatorios

La aceptación oficial debe confirmar conjuntamente:

1. firma y base exactas, staging íntegro y superficies congeladas intactas;
2. `gofmt`, `go vet`, `go test -race` y build estático;
3. pruebas Go para streaming, cancelación, lectura limitada, sanitización, TLS
   veraz y registro de probes;
4. contrato público v1 con conjunto exacto de campos;
5. evidencia v2 por descriptor separado y cobertura uno-a-uno por puerto;
6. primer resultado antes de 250 ms con otro endpoint deliberadamente lento;
7. cancelación downstream en un segundo o menos;
8. backpressure con RSS máximo de 64 MiB, 128 FDs y 48 hilos;
9. throughput de 32 endpoints al menos igual al 15 % de la baseline v1
   congelada, considerando que cada resultado produce además evidencia v2;
10. artefactos privados, hasheados y verificables.

## Baseline congelada

La comparación usa `go_passive_loopback_32` de
`CEPH-CICADAPORT-5.1-BL-001`, cuya medición oficial fue aproximadamente
4.474,94 registros/s. El umbral de aceptación no pretende declarar paridad
absoluta: incorpora deliberadamente el coste de evidencia estructurada,
sanitización, hashing, lectura incremental y canal lateral v2.

## Exclusiones

No se ejecuta red externa, no se modifica el motor Rust ni el Session Store, no
se habilitan probes restringidos y no se realiza detección de vulnerabilidades.
El cierre exige posteriormente validación integral, commit firmado, CI remoto
en verde y aprobación formal del Arquitecto del Proyecto.
