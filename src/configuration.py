"""Configuración tipada y fail-closed para CicadaPort.

La resolución aplica la precedencia contractual:

    CLI explícita > entorno > archivo JSON explícito > defaults controlados

No existe lectura implícita de archivos globales. Este módulo no crea archivos,
no corrige permisos, no genera secretos y no integra gestores externos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from src.operations import (
    OperationalConfig,
    PATH_ENVIRONMENT,
    PATH_ROLES,
    resolve_operational_config,
)
from src.security_values import (
    ProtectedValue,
    ValueClass,
    ValueState,
    safe_serialize_value,
)


CONTRACT = "CSEV-CICADAPORT-6.2-001"
CONTRACT_VERSION = 1
MAX_EXPLICIT_CONFIG_BYTES = 64 * 1024

SOURCE_CLI = "cli"
SOURCE_ENVIRONMENT = "environment"
SOURCE_FILE = "file"
SOURCE_DEFAULT = "default"
SOURCE_MISSING = "missing"

_MISSING = object()


class FieldType(str, Enum):
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    PATH = "PATH"
    CHOICE = "CHOICE"


class ConfigurationError(ValueError):
    """Error seguro de resolución sin incorporar el valor rechazado."""

    def __init__(
        self,
        message: str,
        *,
        field_name: str | None = None,
        source: str | None = None,
        state: ValueState = ValueState.INVALID,
        classification: ValueClass | None = None,
    ) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.source = source
        self.state = state
        self.classification = classification

    def to_safe_dict(self) -> dict[str, str | None]:
        return {
            "classification": (
                None
                if self.classification is None
                else self.classification.value
            ),
            "field": self.field_name,
            "message": str(self),
            "source": self.source,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class ConfigField:
    name: str
    field_type: FieldType
    classification: ValueClass = ValueClass.PUBLIC
    environment: str | None = None
    default: Any = field(
        default=_MISSING,
        repr=False,
    )
    required: bool = False
    allow_empty: bool = False
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("El nombre del campo debe ser alfanumérico.")
        if self.field_type is FieldType.CHOICE and not self.choices:
            raise ValueError("Un campo CHOICE requiere alternativas.")
        if self.field_type is not FieldType.CHOICE and self.choices:
            raise ValueError("choices solo se admite para campos CHOICE.")
        if (
            self.minimum is not None or self.maximum is not None
        ) and self.field_type is not FieldType.INTEGER:
            raise ValueError("Los límites solo se admiten en INTEGER.")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum no puede exceder maximum.")
        if (
            self.classification is ValueClass.FORBIDDEN
            and self.default is not _MISSING
        ):
            raise ValueError("Un campo FORBIDDEN no admite default.")


@dataclass(frozen=True, repr=False)
class ResolvedField:
    name: str
    field_type: FieldType
    classification: ValueClass
    state: ValueState
    source: str
    _value: Any = field(repr=False)

    def __repr__(self) -> str:
        return (
            "ResolvedField("
            f"name={self.name!r}, "
            f"type={self.field_type.value!r}, "
            f"classification={self.classification.value!r}, "
            f"state={self.state.value!r}, "
            f"source={self.source!r}, "
            f"value={safe_serialize_value(self._value, self.classification)!r}"
            ")"
        )

    def reveal(self) -> Any:
        """Entrega el valor al consumidor interno de forma explícita."""

        return self._value

    def protected(self) -> ProtectedValue:
        if self.classification not in {
            ValueClass.SENSITIVE,
            ValueClass.SECRET,
        }:
            raise ConfigurationError(
                f"El campo {self.name} no requiere ProtectedValue.",
                field_name=self.name,
                source=self.source,
                state=self.state,
                classification=self.classification,
            )
        if not isinstance(self._value, str):
            raise ConfigurationError(
                f"El campo {self.name} no es textual.",
                field_name=self.name,
                source=self.source,
                state=self.state,
                classification=self.classification,
            )
        return ProtectedValue(
            self.name,
            self.classification,
            self._value,
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "source": self.source,
            "state": self.state.value,
            "type": self.field_type.value,
            "value": safe_serialize_value(
                self._value,
                self.classification,
            ),
        }


@dataclass(frozen=True, repr=False)
class ResolvedConfiguration:
    fields: Mapping[str, ResolvedField]
    explicit_file: Path | None
    explicit_file_assessment: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fields",
            MappingProxyType(dict(self.fields)),
        )
        if self.explicit_file_assessment is not None:
            object.__setattr__(
                self,
                "explicit_file_assessment",
                MappingProxyType(
                    dict(self.explicit_file_assessment)
                ),
            )

    def __repr__(self) -> str:
        return (
            "ResolvedConfiguration("
            f"fields={self.to_safe_dict()['fields']!r}, "
            f"explicit_file={str(self.explicit_file)!r}"
            ")"
        )

    def field(self, name: str) -> ResolvedField:
        try:
            return self.fields[name]
        except KeyError as error:
            raise ConfigurationError(
                f"Campo de configuración desconocido: {name}.",
                field_name=name,
            ) from error

    def get(self, name: str) -> Any:
        return self.field(name).reveal()

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "explicit_file": (
                None
                if self.explicit_file is None
                else str(self.explicit_file)
            ),
            "explicit_file_assessment": (
                None
                if self.explicit_file_assessment is None
                else dict(self.explicit_file_assessment)
            ),
            "fields": {
                name: resolved.to_safe_dict()
                for name, resolved in sorted(self.fields.items())
            },
        }


@dataclass(frozen=True, repr=False)
class TaskConfiguration:
    typed: ResolvedConfiguration
    operational: OperationalConfig

    def __repr__(self) -> str:
        return (
            "TaskConfiguration("
            f"typed={self.typed!r}, "
            f"operational_profile={self.operational.profile!r}"
            ")"
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema": "cicadaport-task-6-2-configuration-v1",
            "contract": CONTRACT,
            "contract_version": CONTRACT_VERSION,
            "typed": self.typed.to_safe_dict(),
            "operational": self.operational.to_dict(),
            "secret_storage": "not_performed",
            "secret_generation": "not_performed",
            "external_secret_manager_integration": "not_performed",
        }


def _schema_mapping(
    schema: Sequence[ConfigField],
) -> dict[str, ConfigField]:
    output: dict[str, ConfigField] = {}
    environments: dict[str, str] = {}
    for item in schema:
        if item.name in output:
            raise ValueError(f"Campo duplicado en el esquema: {item.name}.")
        output[item.name] = item
        if item.environment is not None:
            previous = environments.get(item.environment)
            if previous is not None:
                raise ValueError(
                    "Variable de entorno duplicada en el esquema: "
                    f"{item.environment} ({previous}, {item.name})."
                )
            environments[item.environment] = item.name
    return output


def _candidate_state(value: Any) -> ValueState:
    if value is _MISSING:
        return ValueState.MISSING
    if value is None:
        return ValueState.EMPTY
    if isinstance(value, str) and not value.strip():
        return ValueState.EMPTY
    return ValueState.PRESENT


def _configuration_error(
    field_spec: ConfigField,
    source: str,
    message: str,
    *,
    state: ValueState = ValueState.INVALID,
) -> ConfigurationError:
    return ConfigurationError(
        message,
        field_name=field_spec.name,
        source=source,
        state=state,
        classification=field_spec.classification,
    )


def _coerce_boolean(
    field_spec: ConfigField,
    source: str,
    value: Any,
) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise _configuration_error(
        field_spec,
        source,
        f"El campo {field_spec.name} no es BOOLEAN válido.",
    )


def _coerce_integer(
    field_spec: ConfigField,
    source: str,
    value: Any,
) -> int:
    if isinstance(value, bool):
        raise _configuration_error(
            field_spec,
            source,
            f"El campo {field_spec.name} no es INTEGER válido.",
        )
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise _configuration_error(
            field_spec,
            source,
            f"El campo {field_spec.name} no es INTEGER válido.",
        ) from error
    if (
        field_spec.minimum is not None
        and result < field_spec.minimum
    ):
        raise _configuration_error(
            field_spec,
            source,
            f"El campo {field_spec.name} queda bajo el mínimo permitido.",
        )
    if (
        field_spec.maximum is not None
        and result > field_spec.maximum
    ):
        raise _configuration_error(
            field_spec,
            source,
            f"El campo {field_spec.name} excede el máximo permitido.",
        )
    return result


def _coerce_value(
    field_spec: ConfigField,
    source: str,
    value: Any,
) -> Any:
    if field_spec.field_type is FieldType.BOOLEAN:
        return _coerce_boolean(field_spec, source, value)
    if field_spec.field_type is FieldType.INTEGER:
        return _coerce_integer(field_spec, source, value)
    if field_spec.field_type is FieldType.STRING:
        if not isinstance(value, str):
            raise _configuration_error(
                field_spec,
                source,
                f"El campo {field_spec.name} debe ser STRING.",
            )
        return value
    if field_spec.field_type is FieldType.PATH:
        if not isinstance(value, (str, os.PathLike)):
            raise _configuration_error(
                field_spec,
                source,
                f"El campo {field_spec.name} debe ser PATH.",
            )
        raw = os.fspath(value)
        if "\x00" in raw:
            raise _configuration_error(
                field_spec,
                source,
                f"El campo {field_spec.name} contiene un byte NUL.",
            )
        return Path(raw)
    if field_spec.field_type is FieldType.CHOICE:
        if not isinstance(value, str):
            raise _configuration_error(
                field_spec,
                source,
                f"El campo {field_spec.name} debe ser CHOICE.",
            )
        normalized = value.strip()
        if normalized not in field_spec.choices:
            raise _configuration_error(
                field_spec,
                source,
                f"El campo {field_spec.name} no pertenece al conjunto permitido.",
            )
        return normalized
    raise _configuration_error(
        field_spec,
        source,
        f"El tipo del campo {field_spec.name} no está soportado.",
    )


def _read_explicit_json_config(
    path_value: str | os.PathLike[str],
    *,
    schema: Mapping[str, ConfigField],
    effective_uid: int | None,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(
            "El archivo explícito de configuración debe ser absoluto.",
            source=SOURCE_FILE,
        )

    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ConfigurationError(
            "No fue posible inspeccionar el archivo explícito de configuración.",
            source=SOURCE_FILE,
        ) from error

    if stat.S_ISLNK(metadata.st_mode):
        raise ConfigurationError(
            "El archivo explícito de configuración no puede ser un symlink.",
            source=SOURCE_FILE,
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(
            "El archivo explícito de configuración debe ser regular.",
            source=SOURCE_FILE,
        )
    if metadata.st_size > MAX_EXPLICIT_CONFIG_BYTES:
        raise ConfigurationError(
            "El archivo explícito de configuración excede el límite.",
            source=SOURCE_FILE,
        )

    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o022:
        raise ConfigurationError(
            "El archivo explícito de configuración no puede ser escribible "
            "por grupo u otros.",
            source=SOURCE_FILE,
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        current = os.fstat(descriptor)
        if (
            current.st_dev != metadata.st_dev
            or current.st_ino != metadata.st_ino
        ):
            raise ConfigurationError(
                "El archivo explícito cambió durante la inspección.",
                source=SOURCE_FILE,
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            document = json.load(stream)
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            "El archivo explícito de configuración no es JSON UTF-8 válido.",
            source=SOURCE_FILE,
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if not isinstance(document, dict):
        raise ConfigurationError(
            "El archivo explícito de configuración debe contener un objeto JSON.",
            source=SOURCE_FILE,
        )

    unknown = sorted(set(document) - set(schema))
    if unknown:
        raise ConfigurationError(
            "Claves desconocidas en el archivo explícito: "
            + ", ".join(unknown),
            source=SOURCE_FILE,
        )

    secret_present = any(
        key in document
        and schema[key].classification is ValueClass.SECRET
        for key in schema
    )
    if secret_present:
        if mode & 0o077:
            raise ConfigurationError(
                "Un archivo con campos SECRET debe ser privado para el propietario.",
                source=SOURCE_FILE,
                classification=ValueClass.SECRET,
            )
        if (
            effective_uid is not None
            and metadata.st_uid != effective_uid
        ):
            raise ConfigurationError(
                "El propietario del archivo con campos SECRET no coincide "
                "con el UID efectivo.",
                source=SOURCE_FILE,
                classification=ValueClass.SECRET,
            )

    return (
        dict(document),
        path,
        {
            "exists": True,
            "is_regular": True,
            "mode": f"{mode:#05o}",
            "owner_uid": metadata.st_uid,
            "secret_fields_present": secret_present,
            "symlink": False,
        },
    )


def resolve_configuration(
    schema: Sequence[ConfigField],
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    explicit_file: str | os.PathLike[str] | None = None,
    effective_uid: int | None = None,
) -> ResolvedConfiguration:
    """Resuelve un esquema sin crear, escribir ni corregir archivos."""

    schema_by_name = _schema_mapping(schema)
    cli = dict(cli_overrides or {})
    environment = dict(os.environ if environ is None else environ)

    unknown_cli = sorted(set(cli) - set(schema_by_name))
    if unknown_cli:
        raise ConfigurationError(
            "Overrides CLI desconocidos: " + ", ".join(unknown_cli),
            source=SOURCE_CLI,
        )

    file_values: dict[str, Any] = {}
    file_path: Path | None = None
    file_assessment: dict[str, Any] | None = None
    if explicit_file is not None:
        file_values, file_path, file_assessment = (
            _read_explicit_json_config(
                explicit_file,
                schema=schema_by_name,
                effective_uid=(
                    os.geteuid()
                    if effective_uid is None
                    else effective_uid
                ),
            )
        )

    resolved: dict[str, ResolvedField] = {}

    for name, field_spec in schema_by_name.items():
        if name in cli:
            raw = cli[name]
            source = SOURCE_CLI
        elif (
            field_spec.environment is not None
            and field_spec.environment in environment
        ):
            raw = environment[field_spec.environment]
            source = SOURCE_ENVIRONMENT
        elif name in file_values:
            raw = file_values[name]
            source = SOURCE_FILE
        elif field_spec.default is not _MISSING:
            raw = field_spec.default
            source = SOURCE_DEFAULT
        else:
            raw = _MISSING
            source = SOURCE_MISSING

        state = _candidate_state(raw)

        if field_spec.classification is ValueClass.FORBIDDEN:
            if state is not ValueState.MISSING:
                raise _configuration_error(
                    field_spec,
                    source,
                    f"El campo {name} está prohibido por contrato.",
                    state=ValueState.INVALID,
                )
            resolved[name] = ResolvedField(
                name=name,
                field_type=field_spec.field_type,
                classification=field_spec.classification,
                state=ValueState.MISSING,
                source=SOURCE_MISSING,
                _value=None,
            )
            continue

        if state is ValueState.MISSING:
            if field_spec.required:
                raise _configuration_error(
                    field_spec,
                    source,
                    f"El campo obligatorio {name} está ausente.",
                    state=ValueState.MISSING,
                )
            resolved[name] = ResolvedField(
                name=name,
                field_type=field_spec.field_type,
                classification=field_spec.classification,
                state=ValueState.MISSING,
                source=SOURCE_MISSING,
                _value=None,
            )
            continue

        if state is ValueState.EMPTY:
            if not field_spec.allow_empty:
                raise _configuration_error(
                    field_spec,
                    source,
                    f"El campo {name} está vacío.",
                    state=ValueState.EMPTY,
                )
            coerced = "" if raw is None else raw
        else:
            coerced = _coerce_value(field_spec, source, raw)

        resolved[name] = ResolvedField(
            name=name,
            field_type=field_spec.field_type,
            classification=field_spec.classification,
            state=state,
            source=source,
            _value=coerced,
        )

    return ResolvedConfiguration(
        fields=resolved,
        explicit_file=file_path,
        explicit_file_assessment=file_assessment,
    )


DEFAULT_SCHEMA: tuple[ConfigField, ...] = (
    ConfigField(
        "operation_profile",
        FieldType.CHOICE,
        environment="CICADAPORT_OPERATION_PROFILE",
        default="local",
        choices=("local", "managed"),
    ),
    *tuple(
        ConfigField(
            role,
            FieldType.PATH,
            environment=PATH_ENVIRONMENT[role],
        )
        for role in PATH_ROLES
    ),
    ConfigField(
        "log_level",
        FieldType.CHOICE,
        environment="CICADAPORT_LOG_LEVEL",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    ),
    ConfigField(
        "diagnostics_enabled",
        FieldType.BOOLEAN,
        environment="CICADAPORT_DIAGNOSTICS_ENABLED",
        default=False,
    ),
    ConfigField(
        "strict_environment_validation",
        FieldType.BOOLEAN,
        environment="CICADAPORT_STRICT_ENVIRONMENT_VALIDATION",
        default=True,
    ),
    ConfigField(
        "root_required",
        FieldType.BOOLEAN,
        classification=ValueClass.FORBIDDEN,
        environment="CICADAPORT_ROOT_REQUIRED",
    ),
    ConfigField(
        "raw_socket_capability",
        FieldType.BOOLEAN,
        classification=ValueClass.FORBIDDEN,
        environment="CICADAPORT_RAW_SOCKET_CAPABILITY",
    ),
    ConfigField(
        "external_secret_manager",
        FieldType.STRING,
        classification=ValueClass.FORBIDDEN,
        environment="CICADAPORT_EXTERNAL_SECRET_MANAGER",
    ),
)


def resolve_task_configuration(
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    explicit_file: str | os.PathLike[str] | None = None,
    effective_uid: int | None = None,
) -> TaskConfiguration:
    """Resuelve configuración tipada y compone el layout congelado de 6.1."""

    environment = dict(os.environ if environ is None else environ)
    typed = resolve_configuration(
        DEFAULT_SCHEMA,
        cli_overrides=cli_overrides,
        environ=environment,
        explicit_file=explicit_file,
        effective_uid=effective_uid,
    )

    profile_field = typed.field("operation_profile")
    profile = profile_field.reveal()

    path_overrides = {
        role: typed.field(role).reveal()
        for role in PATH_ROLES
        if typed.field(role).state is not ValueState.MISSING
    }

    operational_base = resolve_operational_config(
        profile=profile,
        overrides=path_overrides,
        environ=environment,
    )

    sources: dict[str, str] = {
        "profile": profile_field.source,
    }
    for role in PATH_ROLES:
        field_value = typed.field(role)
        sources[role] = (
            SOURCE_DEFAULT
            if field_value.state is ValueState.MISSING
            else field_value.source
        )

    operational = OperationalConfig(
        profile=operational_base.profile,
        paths=operational_base.paths,
        sources=sources,
    )

    return TaskConfiguration(
        typed=typed,
        operational=operational,
    )


def deterministic_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
