# Contrato candidato de baseline operacional

```text
CONTRACT=OPBASE-CICADAPORT-6.1-BL-001
VERSION=1
STATUS=CANDIDATE
PARENT=OPBASE-CICADAPORT-6.1-001
AUTHORIZED_BASE=30ac1780239abe9a63d6a6dd47f101398b7bb33f
AUTHORIZED_BRANCH=feat/task-6-1-operational-architecture-baseline
```

## 1. Finalidad

Producir evidencia reproducible del host y de primitivas operativas locales
sin ejecutar capacidades de escaneo ni modificar código de producción.

## 2. Entradas

- repositorio local autorizado;
- perfil `smoke`, `quick` o `full`;
- directorio de salida externo al repositorio;
- toolchains disponibles en el host.

## 3. Perfiles acotados

| Perfil | Operaciones de I/O | Arranques Python | Ciclos FD |
| --- | ---: | ---: | ---: |
| `smoke` | 3 | 3 | 8 |
| `quick` | 10 | 10 | 32 |
| `full` | 25 | 25 | 64 |

Ningún perfil abre sockets o realiza conexiones.

## 4. Salidas

```text
task-6-1-operational-baseline.json
task-6-1-operational-baseline.md
SHA256SUMS
```

El directorio debe tener modo `0700`; los tres archivos, modo `0600`.

## 5. Esquema mínimo

El JSON debe contener:

- `record_type=task_6_1_operational_baseline`;
- `contract=OPBASE-CICADAPORT-6.1-BL-001`;
- `contract_version=1`;
- identidad Git;
- metadatos del host;
- matriz de soporte declarada y host observado por separado;
- política `external_network=disabled`;
- mediciones de I/O atómico, arranque de subprocess y ciclos FD;
- evaluación con checks booleanos;
- limitaciones explícitas.

## 6. Controles obligatorios

1. salida fuera del repositorio;
2. rechazo de directorios de evidencia enlazados simbólicamente;
3. permisos privados;
4. perfiles finitos;
5. red externa deshabilitada;
6. hashes verificables;
7. ausencia de cambios en el repositorio antes y después;
8. no ejecución de Rust, Go, Session Store ni escaneo;
9. separación entre host observado y matriz soportada;
10. retorno distinto de cero ante cualquier incumplimiento.

## 7. Exclusiones

```text
SOCKET_CREATION=FORBIDDEN
DNS_RESOLUTION=FORBIDDEN
RUST_ENGINE_EXECUTION=FORBIDDEN
GO_ENGINE_EXECUTION=FORBIDDEN
SCANNING=FORBIDDEN
PRODUCTION_CONFIGURATION_MUTATION=FORBIDDEN
SUPPORT_MATRIX_EXPANSION=FORBIDDEN
```
