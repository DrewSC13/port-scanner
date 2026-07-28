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

`SessionCheckpoint` v1 valida snapshots en memoria. Todavía no escribe archivos
ni se conecta al orquestador. Rechaza versiones incompatibles, campos
inesperados, JSON corrupto, resultados incoherentes y cobertura incompleta de
puertos.

## 14. Reanudación

La reanudación real no está implementada en SUBTASK 4.1. No deben crearse
automatizaciones que dependan de `--resume` hasta que una SUBTASK posterior la
implemente, pruebe y documente.

## 15. Manifiestos

`SessionManifest` v1 deriva conteos, tiempos, motores y fingerprint desde un
checkpoint validado. No sustituye los reportes de escaneo existentes.

## 16. Resultados y reportes

TXT, JSON, CSV y HTML permanecen sin cambios. Los resultados internos de
checkpoint preservan el contrato canónico: `state`, `evidence.reason` e
`is_open` deben ser coherentes.

## 17. Códigos de salida

SUBTASK 4.1 no cambia códigos de salida ni manejo público de errores.

## 18. Solución de problemas

Un documento de sesión rechazado debe revisarse por versión, campos desconocidos,
UUID, timestamps UTC, puertos, endpoints, motores y coherencia de resultados.

## 19. Limitaciones conocidas

- no existe persistencia de checkpoints;
- no existe reanudación real;
- no existen opciones CLI de sesión;
- no existe integración TUI de sesión;
- no se modificaron Rust ni Go.

## 20. Privacidad y datos

Los modelos no almacenan credenciales. Los futuros archivos de sesión podrán
contener objetivos, direcciones, puertos y resultados, por lo que deberán
tratarse como información de auditoría potencialmente sensible.

## 21. Compatibilidad

```text
MANUAL_VERSION=0.1-TASK-4.1
PRODUCT_VERSION=3.0.0-rc.1
BASE_COMMIT=84dd1f1eafb684b5afccd7ad647781d8a5b4b459
TASK=4
SUBTASK=4.1
```

## 22. Historial evolutivo

| Manual | Producto | Task | Subtask | Cambio |
|---|---|---|---|---|
| `0.1-TASK-4.1` | `3.0.0-rc.1` | 4 | 4.1 | Modelos ejecutables de plan, checkpoint y manifiesto; sin integración pública. |

## 23. Preguntas frecuentes

**¿Ya puedo reanudar un escaneo?** No. SUBTASK 4.1 establece y prueba los
contratos internos; la ejecución reanudable se implementará después.

**¿Cambió el escaneo TCP?** No. Rust y los contratos JSONL v1 permanecen
intactos.

## 24. Glosario

- **Plan:** configuración efectiva e inmutable de una sesión.
- **Checkpoint:** snapshot validado del progreso.
- **Manifiesto:** resumen derivado y verificable de una sesión.
- **Fingerprint:** SHA-256 del JSON canónico del plan.
