# Implementación candidata — Rust TCP Engine v2

```text
IMPLEMENTATION=RTEV2-CICADAPORT-5.3-IMP-001
VERSION=1.0-CANDIDATE
BASE=8ce44caebf90519867d0da7a53a0ec71372cd741
PUBLIC_CONTRACT_VERSION=1
NETWORK_TECHNIQUE=tcp_connect
GO_ENGINE_CHANGES=0
```

## Objetivo

Reemplazar la cola global protegida por `Mutex` y la resolución DNS ejecutada
por puerto por un flujo incremental con resolución única, índice atómico de
trabajo y canal de resultados acotado. La implementación mantiene el contrato
público `scan_request`/`port_result` v1 y no añade técnicas de red.

## Flujo material

1. La solicitud stdin se limita a 8 MiB y se valida con
   `deny_unknown_fields`.
2. Los puertos se normalizan y los workers quedan acotados a 512 y al número
   real de puertos.
3. El objetivo se resuelve exactamente una vez antes de iniciar workers.
4. Los workers reclaman índices mediante `AtomicUsize`; no existe una cola
   global con `Mutex`.
5. Los resultados atraviesan un `sync_channel` con capacidad máxima 1024,
   proporcionando backpressure al productor.
6. El hilo escritor emite JSONL incremental y telemetría separada.
7. Un error de stdout o telemetría activa la cancelación cooperativa, cierra el
   receptor y desbloquea productores pendientes.
8. La finalización exige exactamente un resultado por puerto solicitado.

## Límites y seguridad

- memoria de resultados O(workers + capacidad del canal), no O(puertos);
- máximo 512 workers y 1024 resultados pendientes;
- stdin máximo 8 MiB;
- diagnósticos nativos truncados a 512 bytes con frontera UTF-8 segura;
- una IP congelada por invocación;
- sin banners, raw sockets, SYN scan ni red externa en la aceptación;
- stdout reservado para JSONL contractual y stderr para diagnóstico.

## Compatibilidad

El contrato público continúa en versión 1. `target` conserva la identidad
solicitada y `address` contiene la IP resuelta una sola vez. El orden del
streaming no es contractual; la capa Python continúa validando unicidad,
completitud y coherencia antes de consolidar resultados.
