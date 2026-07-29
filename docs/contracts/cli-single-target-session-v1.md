# CLI monoobjetivo de sesiones v1

```text
CONTRACT_ID=CCSMO-CICADAPORT-4.4-001
CONTRACT_VERSION=1
STATUS=IMPLEMENTED_CANDIDATE
SCOPE=SINGLE_TARGET_SINGLE_ENDPOINT_CLI
```

La CLI expone `--session-dir`, `--resume`, `--print-plan` y
`--events-jsonl`. Sin esas opciones, el flujo heredado permanece intacto.

Reglas:

- creación: exactamente un objetivo, un endpoint y `target_workers=1`;
- reanudación: el plan se carga del checkpoint y no admite overrides;
- `--print-plan`: imprime `ScanPlan` canónico sin ejecutar motores;
- eventos: JSONL exclusivo, permisos `0600`, secuencia global monotónica;
- cada `checkpoint_confirmed` se emite después de `persist()`;
- TUI, multiobjetivo, multiendpoint, raw y host discovery quedan fuera;
- `ScanPlan`, checkpoint, manifiesto, bridges y motores nativos no cambian.

Eventos públicos: `session_started`, `session_resumed`, `engine_started`,
`port_completed`, `engine_completed`, `checkpoint_confirmed`,
`session_completed`, `session_cancelled` y `session_failed`.

Códigos: `0` éxito, `1` fallo de ejecución/integridad, `2` uso inválido y
`130` cancelación cooperativa.
