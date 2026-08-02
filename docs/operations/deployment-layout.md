# CicadaPort — Layout y ciclo de despliegue

## Propósito

Esta guía separa el diagnóstico y la validación, que son de solo lectura, de
las operaciones mutables de instalación, actualización y rollback.

## Perfiles

### Local

Adecuado para una estación técnica autorizada sin privilegios. Usa rutas XDG
o sus equivalentes bajo `HOME`. No requiere `root`.

### Managed

Adecuado para un servicio Linux no privilegiado cuyos directorios fueron
aprovisionados previamente por una autoridad de instalación. La ejecución
ordinaria no necesita `root` ni `CAP_NET_RAW`.

## Fases

### 1. Install

- verifica plataforma y paquete;
- crea directorios únicamente mediante un instalador autorizado;
- asigna propietario de servicio;
- aplica permisos privados;
- no ejecuta escaneos.

### 2. Validate

- resuelve configuración;
- inspecciona rutas y permisos;
- rechaza symlinks;
- no crea directorios ni cambia modos;
- no consulta red externa.

### 3. Update

- valida previamente el artefacto;
- conserva el artefacto anterior;
- no mezcla migración de estado con sustitución binaria;
- requiere autorización explícita.

### 4. Rollback

- restaura un artefacto previamente verificado;
- conserva evidencia del fallo;
- no altera checkpoints de sesión;
- requiere autorización explícita.

### 5. Diagnose

- registra host observado;
- compara contra la matriz declarada;
- inspecciona readiness del layout;
- produce JSON determinista;
- no amplía soporte por inferencia.

## Readiness

Una configuración puede ser contractualmente válida aunque sus directorios
todavía no existan. `ready=true` exige que todas las rutas existan y cumplan
la política correspondiente.

## Compatibilidad

Este bloque no modifica CLI, TUI, Session Store v2, Secure Artifacts v2,
motores Rust/Go ni contratos JSONL. Los directorios de sesión explícitos
continúan funcionando sin redirección automática.

## Seguridad

No deben ubicarse estado, artefactos o logs en rutas compartidas, world-readable
o enlazadas simbólicamente. El módulo operacional no repara permisos
automáticamente: informa y falla de manera controlada.
