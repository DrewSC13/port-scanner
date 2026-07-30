# CicadaPort Technical Roadmap

## Propósito y autoridad

Este documento consolida el estado técnico alcanzado por CicadaPort y define la
secuencia propuesta para completar el Hito 3. Fue creado bajo el Subhito 3.2.7,
con base en `main@ebfe148b13072c1ace0f1983cf5518225d963a82` y en la etiqueta
firmada `subhito-3.2.6`.

La hoja de ruta es normativa para el orden y las dependencias del trabajo, pero
no autoriza por sí sola una implementación. Cada subhito requiere un contrato
provisional, aprobación expresa, rama propia, pruebas locales, CI verde,
integración controlada y una etiqueta firmada. La fuente definitiva del estado
de cierre es Git: un subhito solo es `CLOSED_FROZEN` cuando existe su etiqueta
anotada y firmada, publicada y verificada contra el commit correspondiente.

## Estados de trabajo

| Estado | Significado |
| --- | --- |
| `DEFINED` | El objetivo, las dependencias y los límites están documentados, pero no autorizados. |
| `AUTHORIZED` | Existe aprobación formal para abrir el subhito desde una base concreta. |
| `IN_IMPLEMENTATION` | La rama autorizada contiene trabajo aún no consolidado. |
| `CANDIDATE` | La implementación y las pruebas locales están completas, pendientes de integración o cierre. |
| `CLOSED_FROZEN` | El trabajo está integrado, el CI está verde y una etiqueta firmada congela el resultado. |
| `BLOCKED` | Falta una precondición formal o técnica. |
| `OUT_OF_SCOPE` | La materia no pertenece al alcance vigente. |

## Base técnica congelada

| Subhito | Resultado consolidado | Referencia | Estado |
| --- | --- | --- | --- |
| 3.2.4 | Flujo especializado con Python como orquestador, Rust obligatorio para TCP y Go obligatorio para banners. | `subhito-3.2.4` → `b899db3` | `CLOSED_FROZEN` |
| 3.2.5 | Orquestación multiobjetivo, resolución independiente, fallos aislados y presupuesto global de concurrencia. | `subhito-3.2.5` → `7e34602` | `CLOSED_FROZEN` |
| 3.2.6 | Monitorización multiobjetivo en TUI, progreso global, cancelación cooperativa y consolidación visual de sesiones. | `subhito-3.2.6` → `ebfe148` | `CLOSED_FROZEN` |
| 3.2.7 | Hoja de ruta técnica, deuda transitoria y criterios de cierre del Hito 3. | `subhito-3.2.7` → `92777f5` | `CLOSED_FROZEN` |

La arquitectura pública congelada es:

```text
Python → Rust → Python → Go → Python
```

Reglas vigentes:

- Python valida, resuelve, orquesta, presenta y persiste.
- Rust ejecuta obligatoriamente el escaneo TCP.
- Go captura banners únicamente cuando la fase se solicita.
- La CLI y el TUI consumen `ScanOrchestrator`; la presentación no duplica red.
- `--threads` es un presupuesto global y `--target-workers` limita objetivos
  simultáneos.
- Cada dirección resuelta conserva identidad, evidencia y reporte propio.
- Los fallos parciales no eliminan resultados correctos.
- La cancelación debe terminar y recolectar todos los procesos nativos.
- Las pruebas de red del proyecto se limitan a loopback o a sistemas con
  autorización expresa.

## Inventario de deuda transitoria

Las siguientes materias existen en el estado congelado. Su presencia no implica
que deban eliminarse de inmediato; cada una requiere una decisión compatible y
probada.

| Código | Materia observada | Estado actual | Decisión pendiente |
| --- | --- | --- | --- |
| `DT-01` | `--engine`, `--banner-engine` y los alias de selección. | Resuelto en el Subhito 3.2.8: la CLI no expone selectores, Rust y Go permanecen como invariantes internas y las opciones históricas terminan con código `2` antes de actividad de red. | Cerrado y congelado mediante `subhito-3.2.8` sobre `f69c0bfc0e48ac84845c5c556561bc02e3f5b7d1`. |
| `DT-02` | Invocación nativa histórica mediante `--host`, `--ports` y variantes heredadas. | El contrato `CINV-CICADAPORT-3.2.9-001` aprobó retirar las rutas históricas y consolidar `--request-stdin` como única interfaz operativa; `--help` permanece como operación informativa. | Implementación en el Subhito 3.2.9; el cierre exige códigos `0/1/2`, rechazo previo a `stdin` y red, CI verde y la etiqueta firmada `subhito-3.2.9`. |
| `DT-03` | Implementaciones Python de escaneo y banners. | Decisión aprobada en `CCR-CICADAPORT-3.2.10-001`: `ScanResult` y el ciclo externo permanecen como núcleo; TCP, UDP y banners Python se conservan como referencia interna, pruebas y paridad. | Implementar sin selección pública, fallback, deprecación ni retirada en `2.2.0`. |
| `DT-04` | Proyección temporal `is_open`. | Decisión aprobada en `CCR-CICADAPORT-3.2.10-001`: permanece el contrato v1; `state` es la fuente de verdad e `is_open` su proyección derivada. | Centralizar invariantes, migrar consumidores internos a `state` y preservar el campo persistido. |
| `DT-05` | Versionado de aplicación y estado de release. | Decisión aprobada en `CRC-CICADAPORT-3.2.11-001`: SemVer, `3.0.0rc1`/`3.0.0-rc.1`, fuente única y changelog. | Implementar y validar sin publicar todavía la prerelease. |
| `DT-06` | Matriz de plataformas declarada. | Decisión aprobada en `CRC-CICADAPORT-3.2.11-001`: Linux x86_64, Ubuntu 22.04/24.04, Python 3.10-3.13, Rust 1.97.1 y Go 1.26.5. | Windows, macOS, ARM64 y Python 3.14 quedan no soportados en RC1. |

## Secuencia restante del Hito 3

Los subhitos se ejecutan de forma estrictamente secuencial. Cada sección declara
su base, contrato y estado verificable; ningún subhito dependiente puede comenzar
antes del cierre firmado del anterior.

### Subhito 3.2.8 — Consolidación de la interfaz pública especializada

**Estado verificable:** `CLOSED_FROZEN` únicamente cuando exista y se haya
verificado la etiqueta firmada `subhito-3.2.8`; hasta entonces el estado se
determina por la evidencia disponible como `IN_IMPLEMENTATION` o `CANDIDATE`.
**Contrato aprobado:** `CIPE-CICADAPORT-3.2.8-001`, versión `1.0-CANDIDATA`.
**Base autorizada:** `main@92777f5241fcad1bbc86d2b7735d4c2a538ed64f`
y `subhito-3.2.7`.

Decisión autorizada:

- retirar `--engine` y `--banner-engine` del parser público;
- retirar `auto`, `python`, `rust` y `go` como elecciones públicas de motor;
- consolidar `cicadaport` como identidad canónica de la ayuda;
- conservar Rust como motor TCP público obligatorio;
- conservar Go como motor obligatorio cuando `--banner-grab` está habilitado;
- mantener metadatos internos de motor y rechazar solicitudes programáticas
  incompatibles antes de cualquier actividad de red;
- mantener las implementaciones Python internas fuera de la selección pública;
- no modificar contratos JSONL, versiones, formatos de reporte, entry points ni
  invocaciones nativas históricas.

Criterios mínimos de aceptación:

- la ayuda pública no expone selectores de motor;
- los puntos de entrada muestran la identidad canónica `cicadaport`;
- las opciones históricas terminan con código `2` antes de resolver objetivos;
- Rust y Go permanecen como únicos motores públicos efectivos, sin fallback;
- perfiles, TUI y reportes conservan metadatos internos coherentes;
- README, CONTRIBUTING, pruebas y scripts reflejan la migración;
- validación local completa, commit firmado y CI completamente verde;
- cierre mediante la etiqueta anotada y firmada `subhito-3.2.8`.

La dependencia del Subhito 3.2.9 quedó satisfecha mediante la etiqueta firmada
`subhito-3.2.8` sobre `f69c0bfc0e48ac84845c5c556561bc02e3f5b7d1`.

### Subhito 3.2.9 — Consolidación de la invocación nativa

**Estado verificable:** `CLOSED_FROZEN` únicamente cuando exista y se haya
verificado la etiqueta firmada `subhito-3.2.9`; hasta entonces el estado se
determina por la evidencia disponible como `IN_IMPLEMENTATION` o `CANDIDATE`.
**Contrato aprobado:** `CINV-CICADAPORT-3.2.9-001`, versión `1.0-CANDIDATA`.
**Base autorizada:** `main@f69c0bfc0e48ac84845c5c556561bc02e3f5b7d1`
y `subhito-3.2.8`.

Decisión autorizada:

- retirar de Rust `--host`, `--ports`, `--ports-stdin`, `--timeout` y
  `--workers`;
- retirar de Go `--host`, `--ports` y `--timeout`;
- declarar `--request-stdin` como única interfaz operativa contractual de ambos
  binarios y `--help` como única operación informativa adicional;
- usar código `0` para éxito o ayuda, `1` para fallos contractuales o de
  ejecución y `2` para uso inválido;
- rechazar argumentos retirados, desconocidos, posicionales o mezclados antes
  de leer `stdin` o iniciar actividad de red;
- mantener sin cambios los contratos JSONL v1, sus versiones, campos, estados,
  razones, evidencia, `is_open`, puentes Python, CLI, TUI, reportes,
  empaquetado, workflows y versión `2.2.0`.

Criterios mínimos de aceptación:

- las ayudas nativas muestran únicamente `--request-stdin` y `--help`;
- no permanece código ejecutable de las rutas históricas;
- Rust conserva streaming incremental y `flush` por cada `port_result`;
- Go conserva un `banner_result` JSONL por puerto y no emite arrays históricos;
- los puentes continúan usando exactamente `argv == ["--request-stdin"]`;
- las pruebas directas demuestran los códigos `0/1/2` y el rechazo previo a
  lectura de `stdin` y red;
- README y CONTRIBUTING documentan la migración desde `subhito-3.2.8`;
- validación local completa, commit firmado y CI completamente verde;
- cierre mediante la etiqueta anotada y firmada `subhito-3.2.9`.

El Subhito 3.2.10 permanece bloqueado hasta que Git demuestre el estado
`CLOSED_FROZEN` de este subhito.

### Subhito 3.2.10 — Estabilización del contrato canónico de resultados

**Estado:** `CLOSED_FROZEN`
**Dependencia:** 3.2.9 `CLOSED_FROZEN`.
**Contrato aprobado:** `CCR-CICADAPORT-3.2.10-001`, versión `1.0-CANDIDATA`.
**Cierre:** `main@5229329b05a354be953cd885ca46ea0a84b7cada`, etiqueta firmada `subhito-3.2.10`, objeto `05fc501745bcf203941ab591738e388de93cf454`.
**Base autorizada:** `main@a0bb081a0b8b1d14ff5432d469e68780b8813142`.

Decisiones autorizadas:

- conservar `ScanResult` y el ciclo de resultados externos como núcleo de
  producción;
- conservar TCP, UDP y banners Python como referencia interna, pruebas y
  paridad, sin selección pública ni fallback;
- mantener el contrato v1 y la versión de aplicación `2.2.0`;
- declarar `state` como fuente de verdad del estado;
- declarar `evidence.reason` como fuente de verdad de la razón;
- mantener `reason` e `is_open` como proyecciones obligatorias;
- decidir reportabilidad únicamente mediante `state == open`;
- preservar JSONL, reportes y contratos soportados.

La implementación no autoriza todavía staging, commit, push, integración,
etiquetado, apertura de 3.2.11, apertura de 3.2.12 ni inicio del Hito 4.

### Subhito 3.2.11 — Preparación de release candidate y soporte verificable

**Estado:** `CLOSED_FROZEN`
**Contrato:** `CRC-CICADAPORT-3.2.11-001`.
**Commit definitivo:** `9d3d75112a49e8608c4cb4619b244372c08ae077`.
**Etiqueta institucional:** `subhito-3.2.11`.
**Objeto de etiqueta:** `253730beb5a1a92d2a6f451fac186ac16ed5b1c8`.
**Release candidate:** `v3.0.0-rc.1`.
**GitHub prerelease:** `359906616`.

Resultado congelado:

- SemVer `3.0.0-rc.1` (`3.0.0rc1` en Python) con fuente única;
- contratos JSONL v1 preservados;
- soporte RC1 limitado a Linux x86_64, Ubuntu 22.04/24.04 y Python 3.10-3.13;
- Rust 1.97.1 y Go 1.26.5;
- wheel, sdist, hashes, inventario e instalación aislada;
- etiquetas RC e institucional publicadas y verificadas.

### Subhito 3.2.12 — Auditoría de cierre y congelamiento del Hito 3

**Estado:** `COMPLETED_CONSOLIDATED_CLOSED_FROZEN`
**Contrato:** `ACCH-CICADAPORT-3.2.12-001`, versión `1.0-DEFINITIVA`.
**Commit definitivo:** `84dd1f1eafb684b5afccd7ad647781d8a5b4b459`.
**Árbol:** `b66830764e58622528781364f86f98f397f0489b`.
**Padre:** `9d3d75112a49e8608c4cb4619b244372c08ae077`.
**Etiqueta firmada:** `subhito-3.2.12`.
**Objeto de etiqueta:** `0029313e4108ef3864375861ab27f0938bd2008b`.

El Hito 3 queda cerrado y congelado. Las excepciones históricas aceptadas no se
extienden a commits posteriores.

## TASK 4 — Sesiones reproducibles, reanudables y observables

```text
TASK_4=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
CONTRACT=CSR-CICADAPORT-TASK-4-001
CONTRACT_VERSION=1.0-DEFINITIVA
BASE=main@84dd1f1eafb684b5afccd7ad647781d8a5b4b459
IMPLEMENTATION_BRANCH=feat/task-4-resumable-observable-sessions
IMPLEMENTATION_HEAD=77ad51f0751b29b510f574e750c1a3fa65db4a60
CLOSURE_REFERENCE=SIGNED_TAG:task-4
```

| Subtask | Resultado | Commit definitivo |
| --- | --- | --- |
| 4.1 | Contrato y núcleo de sesiones | `8229202c5c9ea508961039fdf6de432aeb76f212` |
| 4.2 | Checkpoint y reanudación monoobjetivo | `8ae89824b1a5b7d06f6fbb95fd9da19684b48e2e` |
| 4.3 | Observabilidad nativa Rust y Go | `c27eecde9bd1227ad108367f55d74abf950d6587` |
| 4.4 | Integración pública CLI monoobjetivo | `cbf92fdb599dba22606efe2a5038d17150a723fb` |
| 4.5 | Multiobjetivo, multiendpoint y TUI | `77ad51f0751b29b510f574e750c1a3fa65db4a60` |

Resultado consolidado:

- planes, checkpoints y manifiestos v1 reproducibles;
- persistencia y reanudación monoobjetivo y multiobjetivo;
- observabilidad nativa Rust/Go y eventos públicos proyectados;
- CLI y TUI sobre el mismo runtime de sesión;
- concurrencia global acotada y progreso independiente por endpoint;
- contratos nativos y canónicos v1 preservados;
- CI remoto #60 `Success` sobre el head funcional.

## Alcance excluido y congelado

TASK 4 no incorpora descubrimiento de hosts, ICMP, ARP, sockets o paquetes raw,
SYN scan, nuevas capacidades UDP, identificación activa de sistemas
operativos, detección de vulnerabilidades, explotación, evasión, scripting
ofensivo ni escaneo externo o no autorizado.

## Barrera formal de TASK 5

```text
TASK_5=BLOCKED_NOT_STARTED
```

La futura mejora empresarial de motores Rust y Go, el rediseño del almacén de
sesiones, los reportes seguros, la supply chain y las capacidades operativas
requieren contrato y autorización independientes. El cierre de TASK 4 no abre
TASK 5 automáticamente.

## Gobierno vigente

- Los hechos de cierre deben estar respaldados por commits y etiquetas firmadas.
- Toda integración debe ser lineal, verificable y con CI verde.
- Los contratos v1 congelados no se modifican de forma retroactiva.
- Las deudas transferidas se registran en la siguiente task sin reabrir TASK 4.
- Las pruebas de red se limitan a loopback, laboratorios propios o alcance
  expresamente autorizado.
