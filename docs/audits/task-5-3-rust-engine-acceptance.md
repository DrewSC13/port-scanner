# Auditoría candidata — Rust TCP Engine v2

```text
CONTRACT=CEPH-CICADAPORT-5.3-ACCEPTANCE-001
VERSION=1.0-CANDIDATE
STATUS=PENDING_OFFICIAL_EXECUTION
BASE=8ce44caebf90519867d0da7a53a0ec71372cd741
NETWORK_SCOPE=LOOPBACK_ONLY
EXTERNAL_NETWORK=DISABLED
```

## Controles obligatorios

- contrato público v1 sin campos añadidos ni eliminados;
- ausencia de cambios materiales en `go-banner/`;
- resolución del objetivo fuera de la ruta por puerto;
- índice atómico y canal síncrono acotado;
- primer resultado antes de finalizar la invocación;
- 10.000 resultados literales y 10.000 mediante `localhost`;
- ratio hostname/literal máximo de 1,35;
- throughput literal mínimo del 50 % de la baseline congelada de 5.1;
- RSS máximo 64 MiB;
- FDs máximos `workers + 64`;
- hilos máximos `workers + 8`;
- terminación dentro de un segundo con stdout sin consumir;
- evidencia JSON/Markdown privada y hasheada.

## Interpretación

La comparación contra baseline protege de regresiones severas, mientras que el
ratio hostname/literal verifica que la penalización observada en v1 por DNS por
puerto haya sido eliminada. La prueba de stdout no consumido fuerza
backpressure real y confirma que la memoria permanece acotada antes de la
cancelación.
