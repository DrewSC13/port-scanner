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
| `DT-01` | `--engine`, `--banner-engine` y los alias de selección. | El contrato `CIPE-CICADAPORT-3.2.8-001` aprobó retirarlos de la CLI: Rust y Go permanecen como invariantes internas y las opciones históricas deben terminar con código `2` antes de actividad de red. | Implementación en el Subhito 3.2.8; el cierre solo se materializa con CI verde y la etiqueta firmada `subhito-3.2.8`. |
| `DT-02` | Invocación nativa histórica mediante `--host`, `--ports` y variantes heredadas. | Los puentes Python usan `--request-stdin`; las rutas históricas permanecen para compatibilidad interna. | Definir su ventana de soporte y el criterio verificable de retirada. |
| `DT-03` | Implementaciones Python de escaneo y banners. | Permanecen como referencia interna y soporte de pruebas, sin selección pública. | Definir si se conservan, se aíslan como fixtures o se retiran en una versión mayor. |
| `DT-04` | Proyección temporal `is_open`. | El contrato canónico usa estados y evidencia, pero mantiene `is_open` para consumidores anteriores. | Establecer política de compatibilidad, migración y versionado contractual. |
| `DT-05` | Versionado de aplicación y estado de release. | La aplicación declara `2.2.0`, mientras la política de seguridad indica que aún no existe una release lista para producción. | Definir SemVer, changelog, release candidate y soporte de artefactos. |
| `DT-06` | Matriz de plataformas declarada. | La documentación menciona Linux, Windows y macOS; el cierre exige evidencia reproducible de las plataformas realmente soportadas. | Formalizar la matriz de soporte y sus comprobaciones mínimas. |

## Secuencia restante del Hito 3

Los subhitos siguientes están `DEFINED` y **no están autorizados**. Su numeración
establece el orden previsto; cualquier cambio requiere actualizar esta hoja de
ruta mediante un commit documental firmado.

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

El Subhito 3.2.9 permanece bloqueado hasta que Git demuestre el estado
`CLOSED_FROZEN` de este subhito.

### Subhito 3.2.9 — Consolidación de la invocación nativa

**Estado:** `DEFINED`
**Dependencia:** 3.2.8 `CLOSED_FROZEN`.

Objetivo:

- resolver `DT-02`;
- declarar `--request-stdin` como única interfaz contractual de los puentes;
- decidir y ejecutar, cuando corresponda, la retirada controlada de argumentos
  nativos históricos;
- mantener validación estricta, JSONL determinista y diagnósticos por `stderr`.

No se autoriza anticipadamente la retirada de compatibilidad. El contrato del
subhito deberá demostrar consumidores afectados, estrategia de transición y
pruebas directas de Rust y Go.

### Subhito 3.2.10 — Estabilización del contrato canónico de resultados

**Estado:** `DEFINED`
**Dependencia:** 3.2.9 `CLOSED_FROZEN`.

Objetivo:

- resolver `DT-03` y `DT-04`;
- definir el papel definitivo de las implementaciones Python internas;
- estabilizar estados, razones, evidencia y proyecciones de compatibilidad;
- decidir si el contrato v1 permanece vigente o requiere una migración
  versionada;
- preservar la lectura de reportes y contratos soportados durante cualquier
  transición aprobada.

No se presupone un contrato v2 ni la eliminación de `is_open`; ambas decisiones
deben surgir del contrato provisional y de una matriz de compatibilidad.

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

La única acción habilitada es completar, validar e integrar el Subhito 3.2.8
bajo `CIPE-CICADAPORT-3.2.8-001`. Su cierre exige CI verde y la etiqueta firmada
`subhito-3.2.8`.

El Subhito 3.2.9 permanece `DEFINED` y no está autorizado. No debe iniciarse
mientras el Subhito 3.2.8 no esté materialmente `CLOSED_FROZEN`.
