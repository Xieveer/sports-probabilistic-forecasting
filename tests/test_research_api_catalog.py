"""Проверки строгого контракта каталога исследованных API."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sports_forecast.research.contracts import DataSourceRecord


CATALOGS_DIRECTORY = Path(__file__).parents[1] / "docs" / "research" / "catalogs"


def _evidence() -> dict[str, str]:
    """Вернуть минимальное трассируемое доказательство API-наблюдения."""
    return {
        "reference": "https://example.invalid/evidence/lineups",
        "as_of": "2026-08-25T12:00:00Z",
        "evidence_level": "public_observation",
    }


def _legacy_source(**overrides: object) -> dict[str, object]:
    """Вернуть минимальную legacy-карточку источника для compatibility-проверки."""
    source: dict[str, object] = {
        "source_id": "public-lineups",
        "source": "Публичный lineup feed",
        "access_method": "public REST",
        "documentation": "https://example.invalid/docs",
        "known_endpoints": ["/lineups"],
        "entities": ["match", "lineup"],
        "available_fields": ["match_id", "published_at", "player_id"],
        "historical_depth": "один сезон подтверждён",
        "update_frequency": "нерегулярно",
        "temporal_availability": "нужно сверять published_at",
        "coverage": "NHL",
        "missingness": "неизвестна",
        "pagination": "неизвестна",
        "rate_limits": "неизвестны",
        "authentication": "не требуется по документации",
        "observed_access_restrictions": "не обнаружены",
        "reliability": "не проверена",
        "data_quality": "нужна валидация",
        "potential_leakage": "публикация после матча",
        "potential_research_value": "lineup signal",
        "known_problems": ["История неполна."],
        "last_verified": "2026-08-23",
    }
    source.update(overrides)
    return source


def _complete_source(**overrides: object) -> dict[str, object]:
    """Вернуть минимальную complete-карточку с доказанной связью endpoint и поля."""
    source = _legacy_source(
        catalog_completeness="complete",
        catalog_scope={
            "observed_endpoint_ids": ["lineups-by-match"],
            "unobserved_endpoint_ids": [],
            "field_coverage": "all_observed_fields",
            "limitations": "Все наблюдаемые поля этого endpoint описаны на дату проверки.",
        },
        api_endpoints=[
            {
                "endpoint_id": "lineups-by-match",
                "method": "GET",
                "path": "/lineups/{match_id}",
                "purpose": "Состав матча.",
                "parameters": [
                    {
                        "name": "match_id",
                        "location": "path",
                        "required": True,
                        "data_type": "integer",
                        "description": "Идентификатор матча.",
                    }
                ],
                "response_root": "$",
                "pagination": "Нет.",
                "access_restrictions": "Публичный read-only доступ.",
                "evidence": _evidence(),
            }
        ],
        api_fields=[
            {
                "field_id": "lineup-published-at",
                "endpoint_id": "lineups-by-match",
                "entity": "lineup",
                "json_path": "$.published_at",
                "data_type": "datetime",
                "nullable": False,
                "description": "Момент публикации состава в UTC.",
                "key_role": "none",
                "usage": "feature",
                "temporal_availability": "pre_event_if_timestamp_checked",
                "leakage_risk": "Использовать только если published_at не позднее allowed timestamp.",
                "units": "N/A",
                "domain": "ISO 8601 datetime в UTC.",
                "evidence": _evidence(),
            }
        ],
    )
    source.update(overrides)
    return source


def test_partial_source_record_keeps_legacy_catalog_readable() -> None:
    """Карточка v1 без глубокого каталога остаётся честно помеченной как partial."""
    record = DataSourceRecord.model_validate(_legacy_source())

    assert record.catalog_completeness == "partial"


def test_complete_source_requires_endpoint_and_field_semantics() -> None:
    """Нельзя выдать строковые списки за полный API-каталог."""
    with pytest.raises(ValidationError, match="api_endpoints"):
        DataSourceRecord.model_validate(_legacy_source(catalog_completeness="complete"))


def test_complete_source_links_field_to_endpoint_and_temporal_risk() -> None:
    """Полная карточка даёт scientist трассируемое и temporal-safe описание поля."""
    record = DataSourceRecord.model_validate(_complete_source())

    assert record.api_fields[0].endpoint_id == record.api_endpoints[0].endpoint_id
    assert record.api_fields[0].evidence.as_of.isoformat() == "2026-08-25T12:00:00+00:00"


@pytest.mark.parametrize(
    ("record_type", "record_index"),
    [("api_endpoints", 0), ("api_fields", 0)],
)
def test_complete_source_rejects_blank_endpoint_or_field_evidence(
    record_type: str, record_index: int
) -> None:
    """Complete-карточка не принимает пробелы вместо доказательства endpoint или поля."""
    source = _complete_source()
    records = source[record_type]
    assert isinstance(records, list)
    records[record_index]["evidence"] = "   "

    with pytest.raises(ValidationError, match="evidence"):
        DataSourceRecord.model_validate(source)


def test_complete_source_rejects_field_with_unknown_endpoint() -> None:
    """Поле complete-карточки обязано ссылаться на описанный endpoint."""
    source = _complete_source()
    fields = source["api_fields"]
    assert isinstance(fields, list)
    fields[0]["endpoint_id"] = "unknown-endpoint"

    with pytest.raises(ValidationError, match="неизвестные api_endpoints: unknown-endpoint"):
        DataSourceRecord.model_validate(source)


def test_complete_source_rejects_endpoint_without_described_fields() -> None:
    """Каждый endpoint complete-карточки должен иметь хотя бы одно field-level описание."""
    endpoints = _complete_source()["api_endpoints"]
    assert isinstance(endpoints, list)
    endpoints.append(
        {
            "endpoint_id": "teams",
            "method": "GET",
            "path": "/teams",
            "purpose": "Список команд.",
            "response_root": "$.data",
            "pagination": "Нет.",
            "access_restrictions": "Публичный read-only доступ.",
            "evidence": _evidence(),
        }
    )
    source = _complete_source(api_endpoints=endpoints)

    with pytest.raises(ValidationError, match="api_endpoints без api_fields: teams"):
        DataSourceRecord.model_validate(source)


@pytest.mark.parametrize(
    ("record_type", "field_name"),
    [
        ("api_endpoints", "purpose"),
        ("api_endpoints", "response_root"),
        ("api_endpoints", "pagination"),
        ("api_endpoints", "access_restrictions"),
        ("api_fields", "entity"),
        ("api_fields", "json_path"),
        ("api_fields", "data_type"),
        ("api_fields", "description"),
        ("api_fields", "leakage_risk"),
        ("api_fields", "units"),
        ("api_fields", "domain"),
    ],
)
def test_complete_source_rejects_blank_semantic_value(record_type: str, field_name: str) -> None:
    """Смысл complete-контракта не может подменяться пробелами."""
    source = _complete_source()
    records = source[record_type]
    assert isinstance(records, list)
    records[0][field_name] = "\t "

    with pytest.raises(ValidationError, match=field_name):
        DataSourceRecord.model_validate(source)


@pytest.mark.parametrize("field_name", ["name", "data_type", "description"])
def test_complete_source_rejects_blank_parameter_semantics(field_name: str) -> None:
    """Параметр endpoint также нуждается в явном описании, а не пробелах."""
    source = _complete_source()
    endpoints = source["api_endpoints"]
    assert isinstance(endpoints, list)
    parameters = endpoints[0]["parameters"]
    assert isinstance(parameters, list)
    parameters[0][field_name] = "  "

    with pytest.raises(ValidationError, match=field_name):
        DataSourceRecord.model_validate(source)


@pytest.mark.parametrize(
    ("record_type", "identifier"),
    [("api_endpoints", "endpoint_id"), ("api_fields", "field_id")],
)
def test_complete_source_rejects_duplicate_record_identifiers(
    record_type: str, identifier: str
) -> None:
    """Идентификатор должен однозначно связывать field dictionary и endpoint contract."""
    source = _complete_source()
    records = source[record_type]
    assert isinstance(records, list)
    records.append(copy.deepcopy(records[0]))

    with pytest.raises(ValidationError, match=f"duplicate {identifier}"):
        DataSourceRecord.model_validate(source)


@pytest.mark.parametrize("missing_key", ["as_of", "evidence_level"])
def test_complete_source_requires_structured_evidence(missing_key: str) -> None:
    """Evidence фиксирует дату и уровень уверенности, а не свободную строку."""
    source = _complete_source()
    endpoints = source["api_endpoints"]
    assert isinstance(endpoints, list)
    evidence = endpoints[0]["evidence"]
    assert isinstance(evidence, dict)
    evidence.pop(missing_key)

    with pytest.raises(ValidationError, match=f"evidence.*{missing_key}"):
        DataSourceRecord.model_validate(source)


@pytest.mark.parametrize("evidence_field", ["reference", "evidence_level"])
def test_complete_source_rejects_blank_structured_evidence(evidence_field: str) -> None:
    """У structured evidence обязательные строки не могут быть заглушкой из пробелов."""
    source = _complete_source()
    endpoints = source["api_endpoints"]
    assert isinstance(endpoints, list)
    evidence = endpoints[0]["evidence"]
    assert isinstance(evidence, dict)
    evidence[evidence_field] = " \t"

    with pytest.raises(ValidationError, match=f"evidence.*{evidence_field}"):
        DataSourceRecord.model_validate(source)


def test_complete_source_requires_units_and_domain_or_explicit_na() -> None:
    """Единицы и domain поля должны быть описаны или явно помечены N/A."""
    source = _complete_source()
    fields = source["api_fields"]
    assert isinstance(fields, list)
    fields[0].pop("units")
    fields[0].pop("domain")

    with pytest.raises(ValidationError, match="units|domain"):
        DataSourceRecord.model_validate(source)


def test_complete_source_requires_explicit_scope_of_observed_field_coverage() -> None:
    """Complete означает заявленный scope, а не неограниченное обещание схемы API."""
    source = _complete_source()
    source.pop("catalog_scope")

    with pytest.raises(ValidationError, match="catalog_scope"):
        DataSourceRecord.model_validate(source)


def test_complete_source_requires_scope_to_list_unobserved_endpoint_as_limitation() -> None:
    """Недоступный endpoint остаётся честным limitation, а не исчезает из complete-карточки."""
    source = _complete_source()
    endpoints = source["api_endpoints"]
    assert isinstance(endpoints, list)
    endpoints.append(
        {
            "endpoint_id": "injuries",
            "method": "GET",
            "path": "/injuries",
            "purpose": "Недоступный в исследовании injury feed.",
            "schema_status": "denied",
            "response_root": "Не наблюдался из-за отказа доступа.",
            "pagination": "Неизвестно без доступа.",
            "access_restrictions": "403; обход не выполнялся.",
            "evidence": _evidence(),
        }
    )
    scope = source["catalog_scope"]
    assert isinstance(scope, dict)
    scope["unobserved_endpoint_ids"] = []

    with pytest.raises(ValidationError, match="unobserved_endpoint_ids.*injuries"):
        DataSourceRecord.model_validate(source)


def test_complete_source_rejects_field_without_scientific_use_or_temporal_safety() -> None:
    """Field-level record не готов для scientist, если usage, время и leakage все unknown."""
    source = _complete_source()
    fields = source["api_fields"]
    assert isinstance(fields, list)
    fields[0].update(
        usage="unknown",
        temporal_availability="unknown",
        leakage_risk="unknown",
    )

    with pytest.raises(ValidationError, match="usage.*temporal_availability.*leakage_risk"):
        DataSourceRecord.model_validate(source)


def test_complete_source_allows_honest_single_unknown_as_documented_limitation() -> None:
    """Одно unknown допускается, когда другие свойства делают ограничение применимым."""
    source = _complete_source()
    fields = source["api_fields"]
    assert isinstance(fields, list)
    fields[0]["usage"] = "unknown"

    record = DataSourceRecord.model_validate(source)

    assert record.api_fields[0].usage == "unknown"


def _assert_without_placeholder_values(value: object, location: str = "$") -> None:
    """Проверить отсутствие технических заглушек в сохранённой карточке."""
    placeholders = {"", "todo", "tbd", "placeholder", "заполнить"}
    if isinstance(value, dict):
        for key, nested_value in value.items():
            _assert_without_placeholder_values(nested_value, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            _assert_without_placeholder_values(nested_value, f"{location}[{index}]")
    elif isinstance(value, str):
        assert value.strip().casefold() not in placeholders, f"Заглушка в {location}"


def test_repository_catalog_cards_are_complete_and_have_no_placeholders() -> None:
    """Сохранённые NHL и Smart Tables карточки должны быть валидными handoff-артефактами."""
    catalog_paths = sorted(CATALOGS_DIRECTORY.glob("*.json"))
    assert catalog_paths, "Не найдены сохранённые JSON-карточки Research Mode."

    for catalog_path in catalog_paths:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert payload["catalog_completeness"] == "complete", catalog_path
        _assert_without_placeholder_values(payload)
        DataSourceRecord.model_validate(payload)
