# Manual de Usuario de CicadaPort

## 1. Presentación y alcance

CicadaPort es una herramienta de auditoría autorizada con Python como
orquestador, Rust como motor TCP obligatorio y Go como motor de banners cuando
se solicita esa fase.

TASK 4 incorpora contratos, persistencia y observabilidad verificables. En
SUBTASK 4.4 la CLI pública integra sesiones monoobjetivo y monoendpoint sin
modificar esos formatos ni alterar el flujo heredado.

## 2. Seguridad y uso autorizado

Ejecuta CicadaPort únicamente sobre loopback, laboratorios propios o activos con
autorización expresa. TASK 4 no habilita descubrimiento activo, raw sockets,
SYN scan, detección de vulnerabilidades, explotación ni escaneos externos.

## 3. Requisitos

La RC1 verificada mantiene soporte en Linux x86_64, Ubuntu 22.04/24.04 y Python
3.10–3.13, con Rust 1.97.1 y Go 1.26.5.

## 4. Instalación

Consulta el README principal para instalar wheel, sdist o checkout y para
compilar los motores nativos obligatorios.

## 5. Inicio rápido

La interfaz pública continúa siendo `cicadaport`. Sin opciones de sesión, los
comandos existentes mantienen el flujo heredado.

Para crear una sesión:

```bash
cicadaport 127.0.0.1 -p 80,443 --session-dir ./sesion
```

Para reanudarla:

```bash
cicadaport --resume --session-dir ./sesion
```

## 6. Referencia del CLI

Usa `cicadaport --help` como fuente operativa. SUBTASK 4.4 añade:

- `--session-dir DIR`: crea o identifica una sesión monoobjetivo;
- `--resume`: carga el plan persistido en `--session-dir`;
- `--print-plan`: imprime el `ScanPlan` canónico sin ejecutar motores;
- `--events-jsonl ARCHIVO`: crea un stream público y exclusivo de eventos.

`--resume` no admite nuevos objetivos ni overrides del plan. Las opciones de
sesión no se combinan con TUI, multiobjetivo o multiendpoint.

## 7. Objetivos y exclusiones

El parser actual admite objetivos individuales, listas, rangos, CIDR, archivos
y exclusiones, sujeto al alcance autorizado.

## 8. Puertos y perfiles

Los perfiles `safe`, `standard`, `deep` y `custom` permanecen sin cambios. Los
contratos internos de sesión normalizan puertos únicos entre 1 y 65535.

## 9. Concurrencia y timeouts

`--threads` continúa siendo un presupuesto global y `--target-workers` limita
los objetivos simultáneos. `ScanPlan` registra los valores efectivos sin
multiplicarlos silenciosamente.

## 10. Banners

Go continúa siendo el motor obligatorio cuando `--banner-grab` está activo. Un
plan sin banners conserva `banner_engine=null`.

## 11. TUI

El TUI vigente conserva el flujo heredado. SUBTASK 4.4 no habilita creación,
reanudación, plan ni eventos de sesión desde `--tui`.

## 12. Planes de ejecución

`ScanPlan` v1 conserva una solicitud ya resuelta: objetivos, endpoints, puertos,
timeout, concurrencia, motores y salida. El modelo calcula un fingerprint
SHA-256 reproducible sobre JSON determinista.

## 13. Checkpoints

SUBTASK 4.2 añade un almacén local programático para una sesión y un endpoint.
Cada generación contiene un `SessionCheckpoint` y un `SessionManifest`; el
puntero `CURRENT.json` solo cambia después de escribir, sincronizar y verificar
la nueva generación. Los hashes SHA-256, las versiones, el fingerprint del plan
y la estructura completa se validan al cargar.

Los archivos se crean dentro de un directorio dedicado con permisos
restrictivos. Las generaciones confirmadas son inmutables y una generación
huérfana no sustituye la última confirmada.

## 14. Reanudación

La reanudación monoobjetivo está disponible mediante:

```bash
cicadaport --resume --session-dir DIR
```

El plan se carga exclusivamente del checkpoint persistido. La CLI rechaza
objetivos, puertos, perfiles, timeouts, reportes u otros parámetros que intenten
sustituirlo.

Rust recibe únicamente los puertos pendientes y Go procesa únicamente banners
pendientes de puertos abiertos. Una cancelación conserva el último progreso
confirmado. Reanudar una sesión `completed` no ejecuta red ni altera el
checkpoint.

`--print-plan` imprime JSON canónico y no crea una sesión. `--events-jsonl`
requiere creación o reanudación, usa una ruta nueva y registra eventos de ciclo,
motores, puertos y checkpoints en un stream separado.

## 15. Manifiestos

`SessionManifest` v1 deriva conteos, tiempos, motores y fingerprint desde un
checkpoint validado. No sustituye los reportes de escaneo existentes.

## 16. Resultados y reportes

TXT, JSON, CSV y HTML permanecen sin cambios. Los resultados internos de
checkpoint preservan el contrato canónico: `state`, `evidence.reason` e
`is_open` deben ser coherentes.

## 17. Códigos de salida

```text
0=operación completada o plan impreso
1=fallo de ejecución, persistencia, integridad o compatibilidad
2=uso inválido de CLI
130=cancelación cooperativa
```

Los errores detectables durante el preflight se producen antes de ejecutar los
motores nativos.

## 18. Solución de problemas

Si una sesión no carga, revisa en este orden:

1. que `CURRENT.json` sea un archivo regular y UTF-8 válido;
2. que sus nombres de generación coincidan con `sequence`;
3. que los SHA-256 coincidan;
4. que checkpoint y manifiesto sean versión 1;
5. que el manifiesto vuelva a derivarse exactamente del checkpoint;
6. que el fingerprint corresponda al plan esperado;
7. que el plan tenga un objetivo, un endpoint y `target_workers=1`.

No edites manualmente una generación para intentar repararla. Conserva la
evidencia y clasifica la divergencia.

## 19. Limitaciones conocidas

- las sesiones públicas son exclusivamente monoobjetivo y monoendpoint;
- no existe reanudación multiobjetivo;
- no existe integración TUI de sesión;
- los eventos públicos requieren creación o reanudación de sesión;
- no existe migración entre versiones de contratos;
- Rust y Go conservan sus contratos JSONL y el canal interno separado;
- TASK 4 no habilita raw scanning, host discovery ni escaneos externos.

## 20. Privacidad y datos

Los archivos de sesión no almacenan credenciales, pero sí pueden contener
objetivos, direcciones, puertos, estados, banners y diagnósticos. Trátalos como
evidencia de auditoría potencialmente sensible. El almacén usa permisos `0700`
y documentos `0600`; no debe ubicarse en una carpeta pública o compartida sin
controles adicionales.

## 21. Compatibilidad

```text
MANUAL_VERSION=0.4-TASK-4.4
PRODUCT_VERSION=3.0.0-rc.1
BASE_COMMIT=c27eecde9bd1227ad108367f55d74abf950d6587
TASK=4
SUBTASK=4.4
PUBLIC_CLI_RESUME=AVAILABLE_CANDIDATE
PROGRAMMATIC_SINGLE_TARGET_RESUME=AVAILABLE
TUI_RESUME=NOT_AVAILABLE
MULTI_TARGET_RESUME=NOT_AVAILABLE
```

## 22. Historial evolutivo

| Manual | Producto | Task | Subtask | Cambio |
|---|---|---|---|---|
| `0.1-TASK-4.1` | `3.0.0-rc.1` | 4 | 4.1 | Modelos ejecutables de plan, checkpoint y manifiesto; sin integración pública. |
| `0.2-TASK-4.2` | `3.0.0-rc.1` | 4 | 4.2 | Persistencia atómica y reanudación monoobjetivo programática; CLI aún no expuesta. |
| `0.3-TASK-4.3` | `3.0.0-rc.1` | 4 | 4.3 | Observabilidad nativa Rust y Go mediante canal interno separado. |
| `0.4-TASK-4.4` | `3.0.0-rc.1` | 4 | 4.4 | CLI monoobjetivo para plan, creación, reanudación y eventos JSONL. |

## 23. Preguntas frecuentes

**¿Ya puedo reanudar un escaneo?** Sí, para una sesión monoobjetivo mediante
`cicadaport --resume --session-dir DIR`. La CLI carga el plan persistido y
rechaza objetivos u overrides durante la reanudación.

**¿Puedo revisar el plan sin escanear?** Sí. `--print-plan` imprime el
`ScanPlan` canónico y no crea una sesión ni ejecuta motores.

**¿Cambió el escaneo TCP?** No. `port_result` v1 permanece intacto.
`--events-jsonl` proyecta observabilidad de sesión en un archivo separado.

**¿Funciona con TUI o múltiples objetivos?** No. Esas superficies permanecen
fuera de SUBTASK 4.4.

## 24. Glosario

- **Plan:** configuración efectiva e inmutable de una sesión.
- **Checkpoint:** snapshot validado del progreso.
- **Manifiesto:** resumen derivado y verificable de una sesión.
- **Fingerprint:** SHA-256 del JSON canónico del plan.
- **Generación:** pareja inmutable de checkpoint y manifiesto con una secuencia.
- **CURRENT.json:** puntero atómico a la última generación confirmada.
- **Reanudación idempotente:** continuación que omite trabajo ya confirmado.
