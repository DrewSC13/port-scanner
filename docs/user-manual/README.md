# Manual de Usuario de CicadaPort

## 1. Presentación y alcance

CicadaPort es una herramienta de auditoría autorizada con Python como
orquestador, Rust como motor TCP obligatorio y Go como motor de banners.

TASK 4 ofrece sesiones persistentes reproducibles, reanudables y observables.
SUBTASK 4.5 integra múltiples objetivos y endpoints con CLI y TUI sin cambiar
los contratos v1.

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

Flujo heredado:

```bash
cicadaport 127.0.0.1 -p 80,443
```

Crear una sesión multiobjetivo:

```bash
cicadaport 127.0.0.1 --target 127.0.0.2   -p 80,443 --session-dir ./sesion
```

Reanudar:

```bash
cicadaport --resume --session-dir ./sesion
```

Abrir o reanudar en TUI:

```bash
cicadaport 127.0.0.1 --target 127.0.0.2   -p 80,443 --session-dir ./sesion --tui

cicadaport --resume --session-dir ./sesion --tui
```

## 6. Referencia del CLI

Opciones públicas de sesión:

- `--session-dir DIR`: crea o identifica una sesión persistente;
- `--resume`: carga el plan confirmado en `DIR`;
- `--print-plan`: imprime `ScanPlan` canónico sin ejecutar red;
- `--events-jsonl ARCHIVO`: crea un stream público de eventos v1;
- `--tui`: presenta la misma sesión mediante el dashboard.

La creación admite objetivos posicionales, `--target`, `--target-file` y
exclusiones. `--resume` no admite overrides del plan persistido.

## 7. Objetivos y exclusiones

El parser actual admite objetivos individuales, listas, rangos, CIDR, archivos
y exclusiones, sujeto al alcance autorizado.

## 8. Puertos y perfiles

Los perfiles `safe`, `standard`, `deep` y `custom` permanecen sin cambios. Los
contratos internos de sesión normalizan puertos únicos entre 1 y 65535.

## 9. Concurrencia y timeouts

`threads` es el presupuesto global. `target_workers` limita los endpoints
activos y nunca puede superar endpoints, threads ni el valor solicitado.

```text
effective_target_workers=min(target_workers,endpoints,threads)
workers_per_endpoint=max(1,threads//effective_target_workers)
```

Cada endpoint conserva el timeout y los puertos del plan canónico.

## 10. Banners

Go continúa siendo el motor obligatorio cuando `--banner-grab` está activo. Un
plan sin banners conserva `banner_engine=null`.

## 11. TUI

El TUI admite flujo heredado y sesiones persistentes.

En una sesión muestra:

- `session_id`, estado, checkpoint y ruta;
- endpoints totales, completados, fallidos y pendientes;
- objetivo y dirección activos;
- progreso agregado y resultados.

Controles:

- `F5`: inicia o reanuda la misma sesión;
- `Ctrl+X`: cancelación cooperativa y persistida;
- `Q` o `F10`: solicita cancelación antes de cerrar si hay trabajo activo.

El plan persistido no puede editarse desde el TUI.

## 12. Planes de ejecución

El `ScanPlan` v1 se genera antes de ejecutar red. Puede contener múltiples
objetivos solicitados y múltiples endpoints IPv4/IPv6.

Todos los objetivos deben resolver correctamente. Un fallo de resolución
impide crear la sesión. El fingerprint permanece inmutable durante todas las
reanudaciones.

## 13. Checkpoints

La sesión usa un checkpoint global con un `EndpointProgress` por endpoint.
Cada resultado, banner, error o transición genera una secuencia global
monotónica.

Las generaciones son inmutables y `CURRENT.json` se reemplaza atómicamente.
La lectura verifica SHA-256, manifiesto, identidad de sesión y fingerprint.

## 14. Reanudación

La reanudación omite:

- endpoints completados;
- puertos ya confirmados;
- banners ya confirmados.

Los endpoints fallidos pueden reintentarse sin repetir trabajo de otros
endpoints. Una sesión `completed` es idempotente. Una sesión `failed` o
`cancelled` puede volver a `running`.

CLI:

```bash
cicadaport --resume --session-dir DIR
```

TUI:

```bash
cicadaport --resume --session-dir DIR --tui
```

## 15. Manifiestos

`SessionManifest` v1 se deriva del checkpoint global y resume:

- número de endpoints;
- endpoints exitosos y fallidos;
- puertos completados y abiertos;
- estado y secuencia de la sesión.

No se introducen formatos ni versiones nuevas.

## 16. Resultados y reportes

Se genera un reporte TXT, JSON, CSV o HTML por endpoint. En planes con más de
un endpoint debe utilizarse `report_dir`; una ruta `output` exacta se rechaza.

Una sesión fallida conserva reportes de endpoints que sí completaron. La
reanudación puede regenerarlos sin modificar el checkpoint.

## 17. Códigos de salida

```text
0=operación completada o plan impreso
1=fallo de ejecución, persistencia, integridad o compatibilidad
2=uso inválido o sesión finalizada con fallos parciales
130=cancelación cooperativa
```

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

- el plan debe resolverse completamente antes de crear la sesión;
- el TUI no permite editar el plan persistido;
- no existe migración entre versiones contractuales;
- los reportes continúan siendo individuales por endpoint;
- TASK 4 no incorpora raw scanning, host discovery ni escaneos externos;
- Rust, Go, bridges y eventos públicos v1 permanecen congelados.

## 20. Privacidad y datos

Los archivos de sesión no almacenan credenciales, pero sí pueden contener
objetivos, direcciones, puertos, estados, banners y diagnósticos. Trátalos como
evidencia de auditoría potencialmente sensible. El almacén usa permisos `0700`
y documentos `0600`; no debe ubicarse en una carpeta pública o compartida sin
controles adicionales.

## 21. Compatibilidad

```text
MANUAL_VERSION=1.0-TASK-4-DEFINITIVA
PRODUCT_VERSION=3.0.0-rc.1
BASE_COMMIT=77ad51f0751b29b510f574e750c1a3fa65db4a60
TASK=4
SUBTASK=4.5
TASK_STATUS=COMPLETED_CONSOLIDATED_CLOSED_FROZEN
MULTI_TARGET_RESUME=AVAILABLE_DEFINITIVE
MULTI_ENDPOINT_RESUME=AVAILABLE_DEFINITIVE
TUI_SESSION_INTEGRATION=AVAILABLE_DEFINITIVE
SINGLE_TARGET_SESSION=COMPATIBLE
LEGACY_CLI=COMPATIBLE
```

## 22. Historial evolutivo

| Manual | Producto | Task | Subtask | Cambio |
|---|---|---|---|---|
| `0.1-TASK-4.1` | `3.0.0-rc.1` | 4 | 4.1 | Contratos de sesión v1. |
| `0.2-TASK-4.2` | `3.0.0-rc.1` | 4 | 4.2 | Persistencia y reanudación monoobjetivo. |
| `0.3-TASK-4.3` | `3.0.0-rc.1` | 4 | 4.3 | Observabilidad nativa. |
| `0.4-TASK-4.4` | `3.0.0-rc.1` | 4 | 4.4 | CLI pública monoobjetivo. |
| `0.5-TASK-4.5` | `3.0.0-rc.1` | 4 | 4.5 | Convergencia multiobjetivo, multiendpoint y TUI. |

## 23. Preguntas frecuentes

**¿Puedo reanudar varios objetivos?** Sí. El checkpoint global conserva el
progreso de cada endpoint y solo reejecuta trabajo pendiente o fallido.

**¿Puedo usar la sesión en TUI?** Sí. `--session-dir` y `--resume` pueden
combinarse con `--tui`.

**¿F5 repite el escaneo completo?** No. Reanuda la misma sesión y una sesión
`completed` no ejecuta red.

**¿Cambian los contratos v1?** No. Plan, checkpoint, manifiesto, resultados
nativos y eventos públicos mantienen versión 1.

## 24. Glosario

- **Plan:** configuración efectiva e inmutable de una sesión.
- **Checkpoint:** snapshot validado del progreso.
- **Manifiesto:** resumen derivado y verificable de una sesión.
- **Fingerprint:** SHA-256 del JSON canónico del plan.
- **Generación:** pareja inmutable de checkpoint y manifiesto con una secuencia.
- **CURRENT.json:** puntero atómico a la última generación confirmada.
- **Reanudación idempotente:** continuación que omite trabajo ya confirmado.
