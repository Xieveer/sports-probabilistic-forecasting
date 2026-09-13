"""Проверка полноты локального bronze-кэша Smart Tables без сетевых вызовов."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1
ATTEMPTS_FILENAME = ".bronze_attempts.json"


@dataclass(frozen=True)
class BronzeProfile:
    """Профиль обязательных и необязательных файлов bronze."""

    name: str
    version: int
    required_components: tuple[str, ...]
    optional_components: tuple[str, ...]

    @property
    def components(self) -> tuple[str, ...]:
        """Вернуть все компоненты профиля в детерминированном порядке."""
        return self.required_components + self.optional_components


WINNER_BASELINE_PROFILE = BronzeProfile(
    name="winner_baseline",
    version=1,
    required_components=("card.json", "stat_all.json"),
    optional_components=(
        "stat_first.json",
        "stat_second.json",
        "chart_all.json",
        "chart_first.json",
        "chart_second.json",
        "similar.json",
    ),
)


@dataclass(frozen=True)
class BronzeComponentState:
    """Наблюдаемое состояние одного файла bronze без содержимого payload."""

    name: str
    exists: bool
    size_bytes: int
    written_at: str | None
    last_attempt_status: str
    error_kind: str | None

    @property
    def is_complete(self) -> bool:
        """Признак валидного JSON-envelope успешного ответа API."""
        return self.last_attempt_status == "complete"


@dataclass(frozen=True)
class BronzeMatchState:
    """Полнота bronze одного матча в рамках профиля."""

    match_id: int
    components: tuple[BronzeComponentState, ...]

    def component(self, name: str) -> BronzeComponentState:
        """Вернуть состояние компонента по имени."""
        return next(item for item in self.components if item.name == name)

    def is_train_ready(self, profile: BronzeProfile) -> bool:
        """Проверить полноту required-компонентов профиля."""
        return all(self.component(name).is_complete for name in profile.required_components)

    def has_missing_optional(self, profile: BronzeProfile) -> bool:
        """Проверить, что хотя бы один optional-компонент неполон."""
        return any(not self.component(name).is_complete for name in profile.optional_components)


@dataclass(frozen=True)
class BronzeManifest:
    """Версионируемый read-only снимок полноты bronze-кэша."""

    manifest_version: int
    profile_name: str
    profile_version: int
    generated_at: str
    matches: tuple[BronzeMatchState, ...]

    @property
    def train_ready_match_ids(self) -> tuple[int, ...]:
        """Вернуть ID матчей с полным required-набором."""
        profile = _profile_from_manifest(self)
        return tuple(item.match_id for item in self.matches if item.is_train_ready(profile))

    @property
    def missing_required_match_ids(self) -> tuple[int, ...]:
        """Вернуть ID матчей, которым не хватает required-компонентов."""
        ready = set(self.train_ready_match_ids)
        return tuple(item.match_id for item in self.matches if item.match_id not in ready)

    @property
    def optional_only_match_ids(self) -> tuple[int, ...]:
        """Вернуть train-ready матчи с неполным optional-набором."""
        profile = _profile_from_manifest(self)
        return tuple(
            item.match_id
            for item in self.matches
            if item.is_train_ready(profile) and item.has_missing_optional(profile)
        )

    @property
    def component_coverage(self) -> dict[str, float]:
        """Вернуть долю валидных файлов по каждому компоненту."""
        if not self.matches:
            return dict.fromkeys(_profile_from_manifest(self).components, 0.0)
        return {
            name: sum(item.component(name).is_complete for item in self.matches) / len(self.matches)
            for name in _profile_from_manifest(self).components
        }

    @property
    def train_ready_coverage(self) -> float:
        """Вернуть долю матчей с полным required-набором."""
        return len(self.train_ready_match_ids) / len(self.matches) if self.matches else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать manifest без bronze payload."""
        return asdict(self)


def scan_bronze_cache(raw_root: Path, *, profile: BronzeProfile) -> BronzeManifest:
    """Просканировать match-каталоги и классифицировать файлы без HTTP.

    Args:
        raw_root: Каталог с подкаталогами numeric ``match_id``.
        profile: Профиль required/optional компонентов.

    Returns:
        Версионируемый снимок completeness без содержимого файлов.
    """
    match_dirs = (
        sorted(
            (path for path in raw_root.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda p: int(p.name),
        )
        if raw_root.is_dir()
        else []
    )
    matches = tuple(_scan_match(match_dir, profile) for match_dir in match_dirs)
    return BronzeManifest(
        manifest_version=MANIFEST_VERSION,
        profile_name=profile.name,
        profile_version=profile.version,
        generated_at=datetime.now(UTC).isoformat(),
        matches=matches,
    )


def write_manifest(manifest: BronzeManifest, output_path: Path) -> None:
    """Записать manifest atomically, не сохраняя payload API.

    Args:
        manifest: Снимок полноты.
        output_path: Целевой JSON-файл manifest.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)


def record_attempt(
    match_dir: Path,
    component_name: str,
    *,
    status: str,
    error_kind: str | None,
) -> None:
    """Записать безопасный outcome сетевой попытки без response payload.

    Args:
        match_dir: Каталог одного ``match_id``.
        component_name: Имя bronze-файла.
        status: Статус последней попытки (``complete`` или ``failed``).
        error_kind: Нормализованный безопасный тип ошибки.
    """
    match_dir.mkdir(parents=True, exist_ok=True)
    attempts = _read_attempts(match_dir)
    attempts[component_name] = {
        "last_attempt_status": status,
        "error_kind": error_kind,
        "attempted_at": datetime.now(UTC).isoformat(),
    }
    output_path = match_dir / ATTEMPTS_FILENAME
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps({"version": 1, "components": attempts}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(output_path)


def _scan_match(match_dir: Path, profile: BronzeProfile) -> BronzeMatchState:
    attempts = _read_attempts(match_dir)
    return BronzeMatchState(
        match_id=int(match_dir.name),
        components=tuple(
            _scan_component(match_dir / name, name, attempts.get(name))
            for name in profile.components
        ),
    )


def _read_attempts(match_dir: Path) -> dict[str, dict[str, str | None]]:
    path = match_dir / ATTEMPTS_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    components = payload.get("components") if isinstance(payload, dict) else None
    if not isinstance(components, dict):
        return {}
    return {
        str(name): value
        for name, value in components.items()
        if isinstance(value, dict)
        and value.get("last_attempt_status") in {"complete", "failed"}
        and (value.get("error_kind") is None or isinstance(value.get("error_kind"), str))
    }


def _scan_component(
    path: Path, name: str, attempt: dict[str, str | None] | None
) -> BronzeComponentState:
    if not path.is_file():
        if attempt is not None and attempt["last_attempt_status"] == "failed":
            return BronzeComponentState(name, False, 0, None, "failed", attempt.get("error_kind"))
        return BronzeComponentState(name, False, 0, None, "missing", None)
    stat = path.stat()
    written_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return BronzeComponentState(name, True, stat.st_size, written_at, "invalid", "invalid_json")
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return BronzeComponentState(
            name, True, stat.st_size, written_at, "invalid", "invalid_envelope"
        )
    return BronzeComponentState(name, True, stat.st_size, written_at, "complete", None)


def _profile_from_manifest(manifest: BronzeManifest) -> BronzeProfile:
    if (
        manifest.profile_name == WINNER_BASELINE_PROFILE.name
        and manifest.profile_version == WINNER_BASELINE_PROFILE.version
    ):
        return WINNER_BASELINE_PROFILE
    raise ValueError(f"Неизвестный профиль bronze manifest: {manifest.profile_name!r}")
