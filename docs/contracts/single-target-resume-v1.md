# Contrato candidato de checkpoint y reanudación monoobjetivo v1

```text
CONTRACT_ID=CRMO-CICADAPORT-4.2-001
CONTRACT_VERSION=1.0-CANDIDATA
TASK=4
SUBTASK=4.2
STATUS=IN_IMPLEMENTATION
PRIMARY_DELIVERABLE=WORKING_SOFTWARE
BASE_COMMIT=8229202c5c9ea508961039fdf6de432aeb76f212
BASE_TREE=bfb3398ccc3c238f6818a016aecf53a98f13d4b4
```

## 1. Propósito

Este contrato añade persistencia local y reanudación real para una sesión con un
único objetivo y un único endpoint resuelto. Se apoya exclusivamente en los
modelos versionados cerrados en SUBTASK 4.1:

- `ScanPlan` v1;
- `EndpointProgress` v1;
- `SessionCheckpoint` v1;
- `SessionManifest` v1.

No cambia sus campos, versiones ni semántica. Tampoco modifica los contratos
nativos JSONL v1 de Rust y Go.

## 2. Alcance autorizado

La implementación admite:

- una sesión local;
- un objetivo solicitado;
- un endpoint IPv4 o IPv6 resuelto;
- puertos TCP del plan inmutable;
- checkpoint después de cada resultado de puerto confirmado;
- checkpoint después de cada banner abierto confirmado;
- recuperación tras cancelación o fallo controlado;
- rechazo de corrupción, versión incompatible o plan diferente;
- reanudación idempotente que no repite trabajo confirmado;
- integración programática con Rust y Go mediante adaptadores internos.

Quedan fuera:

- sesiones multiobjetivo;
- cancelación u orquestación multiobjetivo;
- opciones públicas `--resume` o `--session-dir`;
- eventos JSONL públicos;
- `--print-plan`;
- cambios en TUI, Rust, Go o CI;
- descubrimiento de hosts y técnicas raw.

## 3. Invariante monoobjetivo

Un plan aceptado por esta capa debe cumplir simultáneamente:

```text
len(requested_targets)=1
len(resolved_targets)=1
target_workers=1
tcp_engine=rust
```

La capa rechaza cualquier ampliación implícita a varios objetivos o endpoints.

## 4. Estructura local del almacén

Cada sesión usa un directorio dedicado con permisos restrictivos:

```text
<session-dir>/
├── CURRENT.json
├── checkpoint-00000000000000000000.json
├── manifest-00000000000000000000.json
├── checkpoint-00000000000000000001.json
├── manifest-00000000000000000001.json
└── ...
```

Las generaciones son inmutables. `CURRENT.json` es el único puntero mutable y
se reemplaza atómicamente después de confirmar los documentos de la nueva
generación.

## 5. Contrato de `CURRENT.json`

Campos exactos:

```json
{
  "store_version": 1,
  "record_type": "single_target_checkpoint_pointer",
  "session_id": "UUID canónico",
  "sequence": 4,
  "plan_fingerprint": "SHA-256",
  "checkpoint_file": "checkpoint-00000000000000000004.json",
  "checkpoint_sha256": "SHA-256",
  "manifest_file": "manifest-00000000000000000004.json",
  "manifest_sha256": "SHA-256"
}
```

Invariantes:

- no se admiten campos ausentes o desconocidos;
- no se admiten claves JSON duplicadas;
- `store_version` debe ser `1`;
- el UUID debe usar representación canónica;
- todos los hashes deben ser hexadecimales SHA-256 en minúsculas;
- los nombres de generación deben corresponder exactamente a `sequence`;
- los archivos referenciados deben ser regulares y no symlinks;
- los documentos deben residir directamente dentro del almacén.

## 6. Confirmación atómica

La persistencia ejecuta esta secuencia:

1. serializa `SessionCheckpoint` con JSON determinista;
2. deriva y serializa `SessionManifest`;
3. escribe cada generación en un archivo temporal del mismo directorio;
4. aplica `flush` y `fsync` al contenido;
5. publica la generación mediante un enlace duro atómico sin sobrescritura;
6. sincroniza el directorio;
7. construye `CURRENT.json` con hashes y nombres exactos;
8. escribe y sincroniza un puntero temporal;
9. sustituye `CURRENT.json` mediante `os.replace()`;
10. vuelve a sincronizar el directorio.

Una interrupción antes del paso 9 puede dejar una generación huérfana, pero el
puntero confirmado continúa señalando la última generación válida. La carga no
elige automáticamente archivos huérfanos.

## 7. Monotonicidad

Dentro de una sesión confirmada:

```text
next_sequence=current_sequence+1
```

Se rechazan:

- regresiones de secuencia;
- saltos de más de una generación;
- cambio de `session_id`;
- cambio del fingerprint del plan;
- colisiones donde el mismo nombre contiene bytes diferentes.

Volver a persistir la misma generación con contenido idéntico es idempotente.

## 8. Verificación de carga

La carga:

1. lee `CURRENT.json` sin seguir symlinks;
2. valida estructura y versión del puntero;
3. lee checkpoint y manifiesto referenciados;
4. verifica ambos SHA-256;
5. reconstruye los modelos contractuales v1;
6. compara UUID, secuencia y fingerprint con el puntero;
7. vuelve a derivar el manifiesto desde el checkpoint;
8. exige igualdad contractual completa;
9. confirma el alcance monoobjetivo.

La carga no repara ni normaliza documentos corruptos.

## 9. Estados y transiciones

Transiciones operativas:

```text
created   -> running
running   -> running      # nuevo puerto o banner confirmado
running   -> completed
running   -> cancelled
running   -> failed
cancelled -> running      # reanudación
failed    -> running      # reintento explícito
completed -> completed    # lectura idempotente, sin ejecución
```

Cada transición confirmada incrementa `sequence` exactamente una vez.

## 10. Reanudación de puertos

Al reanudar:

- se carga el último checkpoint confirmado;
- opcionalmente se exige un `ScanPlan` con el mismo fingerprint;
- se limpia el error terminal previo al pasar a `running`;
- se entrega al executor únicamente `pending_ports`;
- cada callback validado mueve un puerto de pendiente a completado;
- el checkpoint se confirma antes de continuar;
- un puerto duplicado o no pendiente provoca fallo contractual;
- si el executor termina dejando puertos pendientes, la sesión pasa a `failed`.

Los puertos presentes en `completed_results` nunca se vuelven a ejecutar.

## 11. Reanudación de banners

Cuando `banner_grab=true`:

- solo se consideran puertos canónicamente `open`;
- Go continúa siendo el motor obligatorio;
- cada puerto se solicita por separado para poder confirmar progreso granular;
- `completed_banner_ports` identifica banners ya procesados;
- `captured`, `empty` y `error` representan una tentativa completada;
- una reanudación omite los banners ya confirmados;
- `completed` exige que todos los puertos abiertos estén contabilizados.

## 12. Adaptador nativo

`NativeSingleTargetExecutor` conserva el flujo especializado:

```text
Python -> Rust -> Python -> Go -> Python
```

Rust recibe exclusivamente los puertos pendientes. Cada resultado JSONL válido
se convierte a `ScanResult`, se asocia nuevamente con el objetivo solicitado y
se confirma en disco mediante el callback.

Go se invoca únicamente para puertos abiertos aún no contabilizados. No existe
fallback Python ni selector público de motor.

## 13. Cancelación y fallo

Una cancelación cooperativa o `KeyboardInterrupt`:

- conserva todos los resultados ya confirmados;
- mantiene pendientes los elementos no ejecutados;
- persiste estado `cancelled`;
- no marca el endpoint como fallido;
- permite reanudación posterior.

Un error de ejecución:

- conserva el progreso confirmado;
- persiste estado `failed`;
- registra `last_error` y `endpoint.error` con longitud acotada;
- no elimina ni reescribe generaciones anteriores.

## 14. Integridad y clasificación de errores

Errores diferenciados:

- `SessionCheckpointNotFoundError`: no existe sesión confirmada;
- `SessionCheckpointIntegrityError`: hash, puntero, symlink o manifiesto no
  coinciden;
- `SessionCheckpointCompatibilityError`: versión o plan incompatible;
- `SessionPersistenceError`: no fue posible confirmar una generación;
- `SingleTargetScopeError`: el plan excede el alcance monoobjetivo;
- `SessionExecutionError`: el executor incumplió o falló después de preservar
  estado.

## 15. Observabilidad mínima

Sin exponer todavía eventos públicos, el almacén permite auditar:

- UUID de sesión;
- fingerprint del plan;
- secuencia confirmada;
- estado de sesión;
- puertos completados y pendientes;
- puertos abiertos;
- banners contabilizados;
- error terminal;
- manifiesto derivado de cada generación.

## 16. Seguridad local

- el directorio se protege con modo `0700`;
- los documentos se crean con modo `0600`;
- no se siguen symlinks de puntero o generación;
- no se admiten subdirectorios en nombres de generación;
- no se atraviesan rutas fuera del almacén;
- no se almacenan credenciales;
- objetivos, direcciones y resultados deben tratarse como evidencia sensible.

## 17. Validación focalizada

La implementación candidata incluye pruebas para:

- round trip de checkpoint y manifiesto;
- generaciones huérfanas;
- corrupción de checkpoint y manifiesto;
- campos desconocidos y claves inválidas;
- symlinks;
- colisiones no idempotentes;
- secuencias regresivas o con saltos;
- versión incompatible;
- rechazo multiobjetivo;
- persistencia por resultado;
- cancelación y reanudación sin repetición;
- idempotencia de sesión completada;
- mismatch de fingerprint;
- resultados duplicados o incompletos;
- fallos controlados;
- banners solo en puertos abiertos;
- reanudación granular de banners;
- escaneo funcional limitado a `127.0.0.1`.

## 18. Estado de la superficie pública

```text
PUBLIC_CLI_RESUME=NOT_AVAILABLE
PUBLIC_SESSION_DIR_OPTION=NOT_AVAILABLE
PUBLIC_EVENTS_JSONL=NOT_AVAILABLE
PUBLIC_PRINT_PLAN=NOT_AVAILABLE
TUI_RESUME=NOT_AVAILABLE
MULTI_TARGET_RESUME=NOT_AVAILABLE
```

El runtime es software funcional programático. Su exposición pública requiere
SUBTASK posteriores y autorización independiente.
