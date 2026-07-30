# SAV2-CICADAPORT-5.2-002 — Escritura segura de artefactos v2

```text
VERSION=1.0-CANDIDATE
STATUS=NON_EXECUTABLE_PENDING_5.1_CLOSURE
```

## 1. Alcance

Unificar la escritura de reportes, eventos, bundles, exportaciones y manifiestos
bajo una única primitiva segura.

## 2. Invariantes

- root privado `0700`;
- archivo `0600` independiente del umask;
- archivo temporal en el mismo filesystem;
- creación exclusiva y rechazo de symlink;
- verificación de archivo regular y propietario;
- escritura completa, flush, `fsync`, rename y `fsync` de directorio;
- no sobrescribir por defecto;
- `--force` explícito, limitado y auditado;
- SHA-256 y tamaño registrados después de confirmar.

## 3. Representaciones

1. **Finding report:** información accionable y minimizada.
2. **Evidence bundle:** plan, cobertura, todos los estados, errores, motores,
   eventos, hashes e identidad de build.
3. **Executive summary:** agregados sin sustituir la evidencia.

## 4. Contenido hostil

- TXT/terminal: neutralizar controles y bidi;
- HTML: escape contextual, sin contenido activo;
- CSV: impedir interpretación de fórmulas;
- JSON: UTF-8 estricto y límites;
- nombres de archivo: allowlist y longitud acotada;
- datos crudos: base64 o archivo binario separado con hash.

## 5. Integridad superior

El bundle final debe admitir:

- manifiesto de archivos y hashes;
- firma de release o evidencia cuando la política lo requiera;
- timestamp y zona UTC;
- identidad del operador y autorización referenciada;
- versión, commit y hash de motores;
- política de retención aplicada.
