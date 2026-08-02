# Arquitectura de configuración y validación de entorno

## Objetivo

SUBTASK 6.2 añade una capa operacional segura sobre el layout congelado de 6.1.
La arquitectura se divide para evitar mezclar resolución, secretos, inspección
del host y aprovisionamiento.

## Componentes

### `src/security_values.py`

Responsable de:

- clasificaciones `PUBLIC`, `SENSITIVE`, `SECRET` y `FORBIDDEN`;
- estados `MISSING`, `EMPTY`, `PRESENT` e `INVALID`;
- representación protegida;
- comparación explícita sin exposición;
- redacción de canarios conocidos y patrones de alta señal;
- serialización segura.

No genera ni persiste secretos.

### `src/configuration.py`

Responsable de:

- esquema tipado;
- precedencia CLI > entorno > JSON explícito > default;
- coerción determinista;
- rechazo de claves desconocidas;
- lectura segura con `O_NOFOLLOW` cuando está disponible;
- validación de tamaño, tipo, propietario y permisos;
- errores sin valores;
- composición con `src.operations`.

No busca archivos globales ni modifica el filesystem.

### `src/environment_validation.py`

Responsable de:

- confirmar virtualenv sin resolver el symlink final del intérprete;
- observar Python, dependencias y toolchains;
- ejecutar únicamente comandos locales de versión;
- preservar la matriz de soporte de 6.1;
- inspeccionar el layout sin crearlo;
- producir diagnósticos deterministas y seguros.

No instala ni descarga componentes.

### Validator de SUBTASK 6.2

`scripts/validate_task_6_2_configuration_environment.sh` aplica:

- changeset exacto;
- compilación sin bytecode;
- Bash y ShellCheck;
- escaneo de primitivas de red;
- escaneo de mutaciones prohibidas;
- pruebas focalizadas;
- canarios de no filtración;
- diagnóstico del entorno del proyecto;
- integridad post-ejecución;
- evidencia externa con manifiesto relativo.

## Flujo de datos

```text
CLI / environ / JSON explícito / defaults
                |
                v
      resolución tipada y estados
                |
                +--> serialización segura
                |
                v
    composición con layout de SUBTASK 6.1
                |
                v
  observación de Python, dependencias y toolchains
                |
                v
       diagnóstico sin aprovisionamiento
```

## Decisiones de seguridad

1. Un valor vacío bloquea el fallback.
2. Un campo prohibido falla por presencia, sin evaluar su contenido.
3. Los errores nunca incorporan valores rechazados.
4. Un archivo con secretos exige privacidad para el propietario.
5. La representación segura es la única salida diagnóstica.
6. El host observado nunca amplía la matriz soportada.
7. La validación no crea, corrige, instala ni descarga.
8. El código de 6.1 se consume por composición y permanece congelado.
