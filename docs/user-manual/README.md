# Manual de Usuario de CicadaPort

## 1. Presentación y alcance

CicadaPort es una herramienta de auditoría autorizada con Python como
orquestador, Rust como motor TCP obligatorio y Go como motor de banners cuando
se solicita esa fase.

Este manual evoluciona con TASK 4. En SUBTASK 4.1 se incorporaron contratos
internos ejecutables para planes, checkpoints y manifiestos. **Todavía no existe
una opción pública para guardar o reanudar sesiones.** Esa integración pertenece
a SUBTASK posteriores y no debe inferirse de los modelos internos.

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

La interfaz pública vigente continúa siendo `cicadaport`. SUBTASK 4.1 no añade
opciones CLI y no altera los comandos existentes.

## 6. Referencia del CLI

Usa `cicadaport --help` como fuente operativa. Las opciones de sesión y
reanudación no están disponibles todavía.

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

El TUI vigente no se modifica en SUBTASK 4.1 y todavía no muestra checkpoints o
sesiones reanudadas.

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

La reanudación monoobjetivo está disponible mediante la API interna
`SingleTargetSessionRunner`. No existe todavía una opción pública `--resume`.
El runner entrega al motor Rust únicamente los puertos pendientes, confirma un
checkpoint después de cada resultado y omite los puertos ya completados.

Cuando se solicitaron banners, Go procesa únicamente puertos abiertos aún no
contabilizados. Una cancelación conserva el progreso confirmado y una llamada
posterior a `resume()` continúa desde ese estado. Reanudar una sesión ya
`completed` no ejecuta red ni altera el checkpoint.

## 15. Manifiestos

`SessionManifest` v1 deriva conteos, tiempos, motores y fingerprint desde un
checkpoint validado. No sustituye los reportes de escaneo existentes.

## 16. Resultados y reportes

TXT, JSON, CSV y HTML permanecen sin cambios. Los resultados internos de
checkpoint preservan el contrato canónico: `state`, `evidence.reason` e
`is_open` deben ser coherentes.

## 17. Códigos de salida

SUBTASK 4.2 no cambia códigos de salida públicos. La API programática distingue
checkpoint ausente, corrupción, incompatibilidad, persistencia, alcance y fallo
de ejecución mediante excepciones específicas.

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

- la persistencia y reanudación solo están disponibles mediante API interna;
- no existen todavía `--resume` ni `--session-dir`;
- no existe reanudación multiobjetivo;
- no existe integración TUI de sesión;
- no existen eventos JSONL públicos ni `--print-plan`;
- Rust y Go no fueron modificados.

## 20. Privacidad y datos

Los archivos de sesión no almacenan credenciales, pero sí pueden contener
objetivos, direcciones, puertos, estados, banners y diagnósticos. Trátalos como
evidencia de auditoría potencialmente sensible. El almacén usa permisos `0700`
y documentos `0600`; no debe ubicarse en una carpeta pública o compartida sin
controles adicionales.

## 21. Compatibilidad

```text
MANUAL_VERSION=0.2-TASK-4.2
PRODUCT_VERSION=3.0.0-rc.1
BASE_COMMIT=8229202c5c9ea508961039fdf6de432aeb76f212
TASK=4
SUBTASK=4.2
PUBLIC_CLI_RESUME=NOT_AVAILABLE
PROGRAMMATIC_SINGLE_TARGET_RESUME=AVAILABLE
```

## 22. Historial evolutivo

| Manual | Producto | Task | Subtask | Cambio |
|---|---|---|---|---|
| `0.1-TASK-4.1` | `3.0.0-rc.1` | 4 | 4.1 | Modelos ejecutables de plan, checkpoint y manifiesto; sin integración pública. |
| `0.2-TASK-4.2` | `3.0.0-rc.1` | 4 | 4.2 | Persistencia atómica y reanudación monoobjetivo programática; CLI aún no expuesta. |

## 23. Preguntas frecuentes

**¿Ya puedo reanudar un escaneo?** Programáticamente, sí, para una sesión con
un objetivo mediante `SingleTargetSessionRunner`. Desde la CLI instalada,
todavía no: `--resume` y `--session-dir` permanecen fuera de la superficie
pública.

**¿Cambió el escaneo TCP?** No. Rust y los contratos JSONL v1 permanecen
intactos.

## 24. Glosario

- **Plan:** configuración efectiva e inmutable de una sesión.
- **Checkpoint:** snapshot validado del progreso.
- **Manifiesto:** resumen derivado y verificable de una sesión.
- **Fingerprint:** SHA-256 del JSON canónico del plan.
- **Generación:** pareja inmutable de checkpoint y manifiesto con una secuencia.
- **CURRENT.json:** puntero atómico a la última generación confirmada.
- **Reanudación idempotente:** continuación que omite trabajo ya confirmado.
