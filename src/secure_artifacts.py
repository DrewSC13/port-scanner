"""Primitivas de escritura segura para artefactos persistentes de CicadaPort.

SUBTASK 5.2 centraliza aquí la creación de reportes, eventos y bundles.  La
implementación es deliberadamente local y basada en primitivas POSIX: directorios
privados, archivos privados, temporales en el mismo filesystem, fsync y rechazo
de symlinks.  El contenido crudo permanece en los contratos de sesión; las
representaciones orientadas a personas neutralizan controles terminales.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import stat
from typing import BinaryIO, TextIO


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
_BIDI_AND_INVISIBLE = frozenset(
    {
        0x061C,
        0x200B,
        0x200C,
        0x200D,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2060,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0xFEFF,
    }
)


class SecureArtifactError(RuntimeError):
    """Un artefacto no pudo confirmarse respetando la política de seguridad."""


class ArtifactExistsError(SecureArtifactError):
    """La ruta final ya existe y no se autorizó sobrescritura."""


@dataclass(frozen=True)
class ArtifactReceipt:
    """Prueba mínima de un archivo confirmado."""

    path: Path
    sha256: str
    size: int
    mode: int


def neutralize_text_controls(value: object) -> str:
    """Escapa controles C0/C1, ESC/BEL, bidi e invisibles peligrosos.

    Se conservan ``\n``, ``\r`` y ``\t`` para que TXT/CSV puedan mantener su
    estructura. Los demás caracteres se representan como secuencias ``\\u`` o
    ``\\U`` visibles y deterministas.
    """

    text = str(value)
    output: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character in {"\n", "\r", "\t"}:
            output.append(character)
        elif codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            output.append(f"\\u{codepoint:04x}")
        elif codepoint in _BIDI_AND_INVISIBLE:
            width = 4 if codepoint <= 0xFFFF else 8
            prefix = "u" if width == 4 else "U"
            output.append(f"\\{prefix}{codepoint:0{width}x}")
        else:
            output.append(character)
    return "".join(output)


def _open_flags(*, write: bool, exclusive: bool = False) -> int:
    flags = os.O_WRONLY if write else os.O_RDONLY
    if exclusive:
        flags |= os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_private_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_symlink():
        raise SecureArtifactError(f"El directorio {expanded} no puede ser un symlink.")
    try:
        expanded.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    except OSError as error:
        raise SecureArtifactError(
            f"No fue posible crear el directorio privado {expanded}."
        ) from error
    if expanded.is_symlink() or not expanded.is_dir():
        raise SecureArtifactError(f"{expanded} debe ser un directorio regular.")
    try:
        resolved = expanded.resolve(strict=True)
        os.chmod(resolved, PRIVATE_DIRECTORY_MODE)
    except OSError as error:
        raise SecureArtifactError(
            f"No fue posible proteger el directorio {expanded}."
        ) from error
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode != PRIVATE_DIRECTORY_MODE:
        raise SecureArtifactError(
            f"El directorio {resolved} no quedó en modo 0700 (modo={mode:04o})."
        )
    return resolved


def _ensure_private_descendant(root: Path, parent: Path) -> Path:
    """Crea componentes bajo ``root`` sin seguir symlinks ni salir del root."""

    try:
        relative = parent.relative_to(root)
    except ValueError as error:
        raise SecureArtifactError(
            "La ruta final queda fuera del root protegido."
        ) from error
    current = root
    for component in relative.parts:
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise SecureArtifactError(
                    f"El componente {current} debe ser un directorio regular."
                )
        else:
            try:
                current.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            except OSError as error:
                raise SecureArtifactError(
                    f"No fue posible crear el directorio privado {current}."
                ) from error
        try:
            os.chmod(current, PRIVATE_DIRECTORY_MODE)
        except OSError as error:
            raise SecureArtifactError(
                f"No fue posible proteger el directorio {current}."
            ) from error
        if stat.S_IMODE(current.stat().st_mode) != PRIVATE_DIRECTORY_MODE:
            raise SecureArtifactError(
                f"El directorio {current} no quedó en modo 0700."
            )
    return current.resolve(strict=True)


def _validate_final_path(path: Path, parent: Path) -> Path:
    if not path.name or path.name in {".", ".."}:
        raise SecureArtifactError("La ruta final requiere un nombre de archivo.")
    if path.parent != parent:
        raise SecureArtifactError("La ruta final queda fuera del directorio protegido.")
    if path.is_symlink():
        raise SecureArtifactError("La ruta final no puede ser un symlink.")
    return path


class SecureArtifactWriter:
    """Writer atómico y privado para un único root."""

    def __init__(self, root: str | Path) -> None:
        self.root = _ensure_private_directory(Path(root))

    def resolve(self, path_value: str | Path) -> Path:
        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        # Normaliza ``..`` de forma léxica antes de crear cualquier directorio.
        candidate = Path(os.path.abspath(candidate))
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise SecureArtifactError(
                "La ruta final queda fuera del root protegido."
            ) from error
        parent = _ensure_private_descendant(self.root, candidate.parent)
        final = parent / candidate.name
        return _validate_final_path(final, parent)

    def write_text(
        self,
        path_value: str | Path,
        content: str,
        *,
        overwrite: bool = False,
        newline: str | None = None,
    ) -> ArtifactReceipt:
        if not isinstance(content, str):
            raise SecureArtifactError("El contenido textual debe ser str.")
        if newline is not None:
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = content.replace("\n", newline)
        return self.write_bytes(
            path_value,
            content.encode("utf-8", errors="strict"),
            overwrite=overwrite,
        )

    def write_bytes(
        self,
        path_value: str | Path,
        content: bytes,
        *,
        overwrite: bool = False,
    ) -> ArtifactReceipt:
        if not isinstance(content, bytes):
            raise SecureArtifactError("El contenido binario debe ser bytes.")
        if len(content) > MAX_ARTIFACT_BYTES:
            raise SecureArtifactError("El artefacto excede el tamaño máximo autorizado.")

        final_path = self.resolve(path_value)
        parent = final_path.parent.resolve(strict=True)
        if final_path.exists() and not overwrite:
            raise ArtifactExistsError(f"El artefacto ya existe: {final_path}.")
        if final_path.is_symlink():
            raise SecureArtifactError("No se admite reemplazar un symlink.")

        temporary_path = parent / f".{final_path.name}.{secrets.token_hex(12)}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary_path,
                _open_flags(write=True, exclusive=True),
                PRIVATE_FILE_MODE,
            )
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())

            if overwrite:
                if final_path.exists() and final_path.is_symlink():
                    raise SecureArtifactError("No se admite reemplazar un symlink.")
                os.replace(temporary_path, final_path)
            else:
                try:
                    os.link(temporary_path, final_path, follow_symlinks=False)
                except FileExistsError as error:
                    raise ArtifactExistsError(
                        f"El artefacto ya existe: {final_path}."
                    ) from error
                os.unlink(temporary_path)

            os.chmod(final_path, PRIVATE_FILE_MODE)
            _fsync_directory(parent)
            data = final_path.read_bytes()
            if data != content:
                raise SecureArtifactError("La verificación posterior del artefacto falló.")
            return ArtifactReceipt(
                path=final_path.resolve(strict=True),
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                mode=stat.S_IMODE(final_path.stat().st_mode),
            )
        except (ArtifactExistsError, SecureArtifactError):
            raise
        except OSError as error:
            raise SecureArtifactError(
                f"No fue posible confirmar el artefacto {final_path}."
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def open_exclusive_text_stream(
        self,
        path_value: str | Path,
        *,
        buffering: int = 1,
    ) -> tuple[Path, TextIO]:
        """Crea un stream incremental privado, exclusivo y sin symlinks."""

        final_path = self.resolve(path_value)
        if final_path.exists() or final_path.is_symlink():
            raise ArtifactExistsError(f"El artefacto ya existe: {final_path}.")
        try:
            descriptor = os.open(
                final_path,
                _open_flags(write=True, exclusive=True),
                PRIVATE_FILE_MODE,
            )
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            _fsync_directory(final_path.parent)
        except OSError as error:
            raise SecureArtifactError(
                f"No fue posible crear el stream {final_path}."
            ) from error
        stream = os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            errors="strict",
            newline="\n",
            buffering=buffering,
        )
        return final_path.resolve(strict=True), stream


def secure_write_text(
    output_file: str | Path,
    content: str,
    *,
    overwrite: bool = False,
) -> ArtifactReceipt:
    path = Path(output_file).expanduser()
    return SecureArtifactWriter(path.parent).write_text(
        path,
        content,
        overwrite=overwrite,
    )
