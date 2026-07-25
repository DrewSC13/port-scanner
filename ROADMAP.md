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
| `DT-05` | Versionado de aplicación y estado de release. | La aplicación declara `2.2.0`, mientras la política de seguridad indica que aún no existe una release lista para producción. | Definir SemVer, changelog, release candidate y soporte de artefactos. |
| `DT-06` | Matriz de plataformas declarada. | La documentación menciona Linux, Windows y macOS; el cierre exige evidencia reproducible de las plataformas realmente soportadas. | Formalizar la matriz de soporte y sus comprobaciones mínimas. |

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

**Estado:** `IN_IMPLEMENTATION`
**Dependencia:** 3.2.9 `CLOSED_FROZEN`.
**Contrato aprobado:** `CCR-CICADAPORT-3.2.10-001`, versión `1.0-CANDIDATA`.
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

**Estado:** `DEFINED`
**Dependencia:** 3.2.10 `CLOSED_FROZEN`.

Objetivo:

- resolver `DT-05` y `DT-06`;
- unificar la versión declarada por CLI, empaquetado y documentación;
- adoptar una política SemVer y un changelog;
- definir la matriz real de plataformas y versiones de Python;
- verificar wheel, source distribution, binarios nativos, instalación aislada,
  política de seguridad y documentación de uso;
- establecer los criterios de una release candidate sin declarar producción
  antes de superar la puerta de salida.

### Subhito 3.2.12 — Auditoría de cierre y congelamiento del Hito 3

**Estado:** `DEFINED`
**Dependencia:** 3.2.8–3.2.11 `CLOSED_FROZEN`.

Objetivo:

- auditar contratos, documentación, empaquetado, seguridad, pruebas y CI;
- confirmar que toda deuda crítica está cerrada o clasificada;
- verificar que no existen rutas públicas contradictorias;
- producir la evidencia de cierre del Hito 3;
- congelar el resultado mediante commit y etiqueta firmados.

Este subhito no inicia el Hito 4.

## Dependencias

```text
3.2.7 Hoja de ruta
  └── 3.2.8 Interfaz pública especializada
        └── 3.2.9 Invocación nativa
              └── 3.2.10 Contrato canónico
                    └── 3.2.11 Release candidate
                          └── 3.2.12 Auditoría y cierre del Hito 3
```

No se autoriza ejecución paralela cuando un subhito depende de una decisión de
compatibilidad del anterior.

## Puerta de salida del Hito 3

El Hito 3 solo podrá proponerse para cierre cuando se demuestre, como mínimo:

1. todos los subhitos definidos como obligatorios están `CLOSED_FROZEN`;
2. no queda deuda crítica sin propietario, decisión o justificación;
3. los contratos públicos y nativos están versionados y documentados;
4. CLI, TUI, reportes y motores comparten el mismo modelo de resultados;
5. la cancelación no deja procesos nativos activos ni zombis persistentes;
6. los artefactos de distribución se construyen e instalan de forma aislada;
7. la matriz de Python, Rust, Go, Shell e integración está completamente verde;
8. las plataformas declaradas tienen evidencia o están limitadas explícitamente;
9. README, CONTRIBUTING, SECURITY, changelog y hoja de ruta son coherentes;
10. los commits de cierre y la etiqueta final están firmados y verificados;
11. las pruebas de red se ejecutan únicamente en loopback o alcance autorizado;
12. no se ha incorporado materialmente ninguna capacidad reservada al Hito 4.

## Barrera formal del Hito 4

El Hito 4 está `BLOCKED` y `NOT_STARTED`.

Permanecen fuera de alcance hasta una autorización formal independiente:

- descubrimiento de hosts;
- ICMP y ARP;
- sockets o paquetes raw;
- SYN scan;
- nuevas capacidades UDP;
- identificación activa de sistemas operativos;
- detección de vulnerabilidades;
- explotación, evasión o scripting ofensivo;
- escaneos externos o no autorizados.

Cerrar el Hito 3 no abre automáticamente el Hito 4. La apertura requerirá una
base congelada, un contrato provisional propio y una aprobación explícita del
Arquitecto del Proyecto.

## Gobierno de esta hoja de ruta

- Los hechos históricos deben estar respaldados por commits o etiquetas.
- Una propuesta futura debe permanecer marcada como `DEFINED` hasta recibir
  autorización.
- Los cambios de estado requieren evidencia verificable.
- Toda modificación de esta hoja debe ser atómica, firmada y pasar el CI.
- Un subhito funcional debe actualizar la documentación afectada en el mismo
  flujo de cierre.
- No se deben eliminar incidentes de CI fallidos que constituyan evidencia
  histórica de una regresión y su corrección.
- La hoja de ruta no sustituye el contrato provisional de cada subhito.

## Siguiente acción formal

La única acción habilitada es implementar y validar localmente el Subhito 3.2.10
bajo `CCR-CICADAPORT-3.2.10-001`, en la rama técnica autorizada y sin staging,
commit, push, integración o etiquetado.

Los Subhitos 3.2.11 y 3.2.12 permanecen `DEFINED` y bloqueados por dependencia.
El Hito 4 permanece `BLOCKED` y `NOT_STARTED`.
