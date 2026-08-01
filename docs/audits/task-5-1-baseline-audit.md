# Auditoría candidata de baseline — SUBTASK 5.1

```text
AUDIT=CEPH-CICADAPORT-5.1-BL-001
VERSION=1.0-CANDIDATE
STATUS=EXECUTED_REVIEWED_PASS_RESOURCE_SUPPLEMENT_PENDING
NETWORK_SCOPE=LOOPBACK_ONLY
EXTERNAL_NETWORK=DISABLED
```

## 1. Objetivo

Medir por separado el comportamiento de la base v1 antes de cualquier cambio en
Session Store, Rust, Go o reportes. La baseline oficial debe ejecutarse en la
rama de TASK 5 con Python 3.13, Rust 1.97.1 y Go 1.26.5.

## 2. Instrumentación

`benchmarks/task_5_1_baseline.py` produce:

- JSON estructurado;
- resumen Markdown;
- `SHA256SUMS`;
- permisos `0700/0600` para su propia evidencia;
- metadata de host, Git y toolchains;
- mediciones de Rust con IP literal y hostname;
- mediciones Go con servidores pasivos loopback;
- crecimiento del Store v1 con snapshots sintéticos válidos;
- comprobación de permisos y controles terminales en reportes v1;
- hechos estáticos verificables del código.

El benchmark no acepta un objetivo remoto y no ejecuta descubrimiento, raw,
SYN, UDP ni probes externos.

## 3. Casos oficiales

### Rust

| Caso | Puertos | Target | Workers | Timeout |
| --- | ---: | --- | ---: | ---: |
| R-100 | 100 | 127.0.0.1 | 100 | 50 ms |
| R-1K | 1.000 | 127.0.0.1 | 256 | 50 ms |
| R-10K | 10.000 | 127.0.0.1 | 256 | 50 ms |
| RDNS-100 | 100 | localhost | 100 | 50 ms |
| RDNS-1K | 1.000 | localhost | 256 | 50 ms |

### Go

Servidores TCP pasivos controlados: 1, 8 y 32 puertos, un banner por conexión,
sin TLS y sin probe activo.

### Session Store v1

Sesiones sintéticas válidas de 10, 50, 100, 250 y 500 puertos. Cada caso parte
de un directorio nuevo y confirma estado inicial, un checkpoint por resultado y
estado terminal.

## 4. Hipótesis a verificar

| ID | Hipótesis |
| --- | --- |
| BL-01 | El Store v1 crea aproximadamente dos generaciones por secuencia. |
| BL-02 | Los bytes acumulados crecen superlinealmente al serializar el historial. |
| BL-03 | La persistencia domina el tiempo de una sesión loopback grande. |
| BL-04 | Rust resuelve DNS dentro de cada `scan_port` para hostnames v1. |
| BL-05 | Go acumula resultados y emite stdout solo después de ordenar. |
| BL-06 | Reportes v1 dependen del umask para permisos. |
| BL-07 | TXT v1 conserva controles ESC/BEL provenientes del banner. |

## 5. Evidencia estática ya confirmada

Sin ejecutar red externa, el código base muestra:

- Store generacional con checkpoint, manifiesto, pointer y `fsync`;
- persistencia dentro del callback de cada resultado monoobjetivo;
- carga y reconstrucción global bajo lock en batch;
- Rust con hilos bloqueantes, `Mutex<VecDeque>`, resolución por puerto y flush
  JSONL por resultado;
- Go con hasta 32 workers, acumulación, ordenamiento final, una lectura y TLS
  con verificación deshabilitada para observación;
- reporter con `open(..., "w")` sin `chmod`, `fsync` ni primitiva anti-symlink.

## 6. Criterios para aceptar la baseline

- toolchains exactas verificadas;
- base y tag firmados verificables;
- salida completa con `TASK_5_1_BASELINE=PASS`;
- tres artefactos y hashes coincidentes;
- ningún objetivo fuera de loopback;
- staging sin cambios funcionales;
- resultados revisados antes de fijar presupuestos de 5.2–5.4.

## 7. Estado

La baseline oficial primaria fue ejecutada el 30 de julio de 2026 y revisada
con resultado PASS. La cadena de custodia de JSON, Markdown, log y
`SHA256SUMS` fue verificada. El suplemento `CEPH-CICADAPORT-5.1-RB-001`
permanece pendiente para medir RSS, FDs, hilos, terminación y primera salida
antes del cierre candidato. Ninguna proyección incluida en el JSON se considera
prueba de aceptación; la prueba de 65.535 puertos se definirá después de
corregir el Store.
