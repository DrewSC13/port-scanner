# Contrato de configuración, secretos y validación de entorno

- Identificador: `CSEV-CICADAPORT-6.2-001`
- Versión: `1.0-CANDIDATE`
- Contrato superior: `PRODOPS-CICADAPORT-TASK-6-001`
- Base material: `e718652829bfc915bed18da5b97d66f24bdfa553`
- Estado: `IN_MATERIAL_IMPLEMENTATION`

## 1. Alcance

Este contrato define resolución tipada de configuración, clasificación segura
de valores, redacción de diagnósticos y validación observacional del entorno.

No almacena ni genera secretos. No integra gestores externos. No instala
dependencias, no crea directorios operacionales, no corrige permisos, no abre
sockets y no solicita red externa.

## 2. Precedencia

```text
CLI explícita
  > variable de entorno declarada
  > archivo JSON explícitamente indicado
  > default controlado
```

Un valor vacío en una fuente de mayor precedencia no permite fallback. Se
registra como `EMPTY` y falla si el campo no lo admite.

No existe búsqueda implícita de archivos globales.

## 3. Formato de archivo

El único formato candidato es JSON UTF-8 con un objeto en la raíz.

Barreras:

- ruta absoluta;
- archivo regular;
- symlinks rechazados;
- máximo 64 KiB;
- sin escritura para grupo u otros;
- si contiene un campo `SECRET`, modo privado para el propietario y UID
  coincidente;
- claves desconocidas rechazadas;
- ninguna creación o corrección automática.

La elección de JSON conserva compatibilidad con Python 3.10–3.13 sin añadir
dependencias de parsing.

## 4. Estados

```text
MISSING
EMPTY
PRESENT
INVALID
```

Ausencia, vacío y valor inválido son estados diferentes. Los mensajes de error
incluyen nombre, fuente, estado y clasificación, nunca el valor rechazado.

## 5. Clasificaciones

```text
PUBLIC
SENSITIVE
SECRET
FORBIDDEN
```

- `PUBLIC`: serialización permitida.
- `SENSITIVE`: serialización como `<REDACTED_SENSITIVE>`.
- `SECRET`: serialización como `<REDACTED_SECRET>`.
- `FORBIDDEN`: presencia rechazada fail-closed.

Los contenedores protegidos son transitorios, no persistentes, y su `repr`,
`str` y comparación no exponen el valor.

## 6. Composición con SUBTASK 6.1

`src/configuration.py` reutiliza `src/operations.py` por composición. No replica
la normalización de rutas, la política de permisos ni la matriz de soporte.

El contrato congelado `OPLAYOUT-CICADAPORT-6.1-001` no se modifica.

## 7. Validación del entorno

La validación observa:

- intérprete y virtualenv;
- Python 3.10–3.13;
- dependencias locales;
- toolchains locales;
- layout operacional;
- soporte declarado.

No existe fallback silencioso al Python global. La ruta ejecutable dentro de
`.venv` se conserva lexicalmente y no se resuelve al destino final del symlink.

Los comandos de versión se ejecutan sin shell, con timeout y variables offline.

## 8. Barreras

```text
SECRET_STORAGE=NOT_PERFORMED
SECRET_GENERATION=NOT_PERFORMED
EXTERNAL_SECRET_MANAGER_INTEGRATION=NOT_PERFORMED
IMPLICIT_GLOBAL_CONFIG_DISCOVERY=FORBIDDEN
DEPENDENCY_INSTALLATION=FORBIDDEN
OPERATIONAL_DIRECTORY_CREATION=FORBIDDEN
PERMISSION_CORRECTION=FORBIDDEN
EXTERNAL_NETWORK=NOT_REQUESTED
NEW_NETWORK_CAPABILITIES=0
PUBLIC_CONTRACT_CHANGES=0
PUSH=NOT_AUTHORIZED
MERGE_TO_MAIN=NOT_AUTHORIZED
TAG_CREATION=NOT_AUTHORIZED
RELEASE_PUBLICATION=NOT_AUTHORIZED
PACKAGE_PUBLICATION=NOT_AUTHORIZED
```
