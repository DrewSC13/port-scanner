# Contrato de layout operacional de CicadaPort

- Identificador: `OPLAYOUT-CICADAPORT-6.1-001`
- Versión: `1.0-CANDIDATE`
- Contrato superior: `OPBASE-CICADAPORT-6.1-001`
- Base material: `9bf31cf39f7ec8e85d83e8a892b2291dd5737ef3`
- Estado: `IN_MATERIAL_IMPLEMENTATION`

## 1. Alcance

Este contrato define la resolución determinista de configuración, rutas,
permisos, diagnóstico y soporte. No crea directorios, no cambia permisos, no
abre sockets, no resuelve DNS y no ejecuta motores nativos.

La implementación se ubica en `src/operations.py`, coherente con la estructura
real del paquete (`src.*`). La ruta exploratoria
`src/cicadaport/operations.py` queda descartada porque introduciría un paquete
anidado inexistente.

## 2. Precedencia

```text
override explícito
  > variable de entorno CICADAPORT_*
  > valor por defecto del perfil
```

Perfiles válidos:

- `local`: operación sin privilegios basada en `HOME` y XDG;
- `managed`: layout administrado bajo `/etc`, `/var`, `/run` y `/opt`.

## 3. Variables

```text
CICADAPORT_OPERATION_PROFILE
CICADAPORT_CONFIG_DIR
CICADAPORT_STATE_DIR
CICADAPORT_ARTIFACT_DIR
CICADAPORT_LOG_DIR
CICADAPORT_RUNTIME_DIR
CICADAPORT_INSTALL_DIR
```

Todas las rutas deben ser absolutas. `artifact_dir` debe permanecer dentro de
`state_dir`. La validación rechaza rutas duplicadas, bytes NUL, expansión de
usuarios ajenos y symlinks existentes.

## 4. Layout local

```text
$XDG_CONFIG_HOME/cicadaport
$XDG_STATE_HOME/cicadaport
$XDG_STATE_HOME/cicadaport/artifacts
$XDG_STATE_HOME/cicadaport/logs
$XDG_RUNTIME_DIR/cicadaport
$XDG_DATA_HOME/cicadaport
```

Cuando una variable XDG no existe se usa la ubicación equivalente bajo
`HOME`. El runtime cae en `state_dir/runtime`, no en un directorio temporal
global.

## 5. Layout administrado

```text
/etc/cicadaport
/var/lib/cicadaport
/var/lib/cicadaport/artifacts
/var/log/cicadaport
/run/cicadaport
/opt/cicadaport
```

El contrato solo resuelve e inspecciona estas rutas. Su aprovisionamiento
pertenece a una fase de instalación explícitamente autorizada.

## 6. Permisos

- estado, artefactos, logs y runtime: privados, equivalentes a `0700`;
- configuración: propietario con lectura/ejecución y sin acceso de otros;
- instalación: sin escritura para grupo u otros;
- directorios sensibles existentes: propiedad del UID efectivo;
- symlinks: rechazados de forma fail-closed.

Una ruta ausente es válida como contrato, pero no queda marcada como lista.

## 7. Privilegios y red

```text
ROOT_REQUIRED=false
CAP_NET_RAW_REQUIRED=false
PRIVILEGED_CONTAINER_REQUIRED=false
RAW_SOCKET_CAPABILITY=false
EXTERNAL_NETWORK=false
DNS_RESOLUTION=false
```

## 8. Soporte

La observación del host se registra separadamente. Solo se declara soportado:

```text
Linux
x86_64
Python 3.10-3.13
Ubuntu 22.04 y 24.04 en CI
```

Observar Python 3.14, ARM64, Windows o macOS no amplía la matriz.

## 9. Acciones de despliegue

`install`, `validate`, `update`, `rollback` y `diagnose` son acciones
independientes. Solo `validate` y `diagnose` son necesariamente libres de
mutaciones; las demás requieren autorización explícita.

## 10. Barreras

```text
EXISTING_PUBLIC_CONTRACT_CHANGES=0
NEW_NETWORK_CAPABILITIES=0
DIRECTORY_CREATION_BY_VALIDATOR=0
PUSH=NOT_AUTHORIZED
MERGE_TO_MAIN=NOT_AUTHORIZED
TAG_CREATION=NOT_AUTHORIZED
RELEASE_PUBLICATION=NOT_AUTHORIZED
PACKAGE_PUBLICATION=NOT_AUTHORIZED
```
