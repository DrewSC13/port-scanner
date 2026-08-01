# RTEV2-CICADAPORT-5.3-001 — Rust TCP Engine v2

```text
VERSION=1.0-CANDIDATE
STATUS=NON_EXECUTABLE_PENDING_5.1_CLOSURE
TECHNIQUE=tcp_connect
```

## 1. Objetivo

Construir un motor TCP incremental, asíncrono, acotado y observable sin ampliar
todavía la técnica de red más allá de `tcp_connect` autorizado.

## 2. Solicitud v2 candidata

La solicitud separa identidad solicitada de dirección resuelta:

```json
{
  "contract_version": 2,
  "record_type": "scan_request",
  "target": "example.internal",
  "address": "192.0.2.10",
  "address_family": "ipv4",
  "ports": [22, 80, 443],
  "connect_timeout_ms": 500,
  "max_in_flight": 128,
  "connections_per_second": 500,
  "burst": 64
}
```

`address` debe ser una IP literal. Rust no resolverá DNS dentro del ciclo de
puertos. Un adaptador Python podrá proyectar solicitudes v1 durante la ventana
de compatibilidad.

## 3. Runtime

- reactor asíncrono y tareas ligeras;
- semaphore global y por endpoint;
- token bucket para tasa y burst;
- canal bounded de resultados;
- cancelación cooperativa y drenaje;
- memoria O(concurrencia), no O(puertos);
- orden no contractual durante streaming; orden final en consolidación.

## 4. Resultado y error

El contrato debe preservar el resultado canónico y añadir evidencia estructurada:

```text
phase
normalized_reason
native_error_kind
native_errno
retryable
attempt
elapsed_us
```

Los mensajes crudos se truncan y no son fuente de clasificación. La tabla de
mapeo errno/estado tendrá pruebas Linux deterministas.

## 5. Entrada y salida

- límite máximo de bytes de stdin;
- un único objeto JSON;
- límite de puertos y parámetros;
- JSONL incremental;
- buffering acotado y flush por política, no `fsync` por resultado;
- stdout reservado a contratos; stderr a diagnóstico truncado;
- telemetría separada y no fatal por defecto.

## 6. Identidad de build

Al iniciar debe poder emitir o responder una identidad verificable:

```text
engine_version
contract_versions
git_commit
target_triple
rustc_version
features
binary_sha256
```

El puente compara esa identidad con el manifiesto instalado antes de red.

## 7. Presupuestos a congelar con baseline

- throughput loopback por 100/1.000/10.000 puertos;
- diferencia IP literal frente a hostname v1;
- RSS y descriptores máximos;
- tiempo de cancelación;
- comportamiento con timeout/drop;
- rendimiento con telemetría habilitada y degradada.
