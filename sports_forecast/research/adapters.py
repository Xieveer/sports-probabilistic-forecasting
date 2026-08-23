"""Adapters raw isolated role calls к валидированным контрактам Research Mode."""

from __future__ import annotations

from typing import Protocol, TypeVar, cast

from pydantic import BaseModel, ValidationError

from sports_forecast.research.contracts import (
    ContextPackage,
    DataResearchResult,
    EvaluationNarrative,
    EvaluationResult,
    HypothesisProposal,
)


ResponseContract = TypeVar("ResponseContract", bound=BaseModel)


class RawRoleInvoker(Protocol):
    """Выполняет один isolated role call и возвращает только raw JSON."""

    def invoke(
        self,
        role: str,
        package: ContextPackage,
        retry_feedback: str | None,
    ) -> str: ...


class ValidatedRoleGateway:
    """Валидирует raw JSON и повторяет вызов с ошибкой контракта.

    Этот adapter не выбирает runtime и не передаёт историю: concrete invoker обязан
    создавать новую сессию из `package` при каждой попытке.
    """

    def __init__(self, invoker: RawRoleInvoker, max_attempts: int = 2) -> None:
        if max_attempts < 1:
            msg = "max_attempts должен быть не меньше 1"
            raise ValueError(msg)
        self.invoker = invoker
        self.max_attempts = max_attempts

    def propose_hypothesis(self, package: ContextPackage) -> HypothesisProposal:
        """Вернуть валидный HypothesisProposal либо поднять ValidationError."""
        return self._validated("research-scientist", package, HypothesisProposal)

    def research_data(self, package: ContextPackage) -> DataResearchResult:
        """Вернуть валидный DataResearchResult либо поднять ValidationError."""
        return self._validated("data-researcher", package, DataResearchResult)

    def interpret_evaluation(
        self, package: ContextPackage, result: EvaluationResult
    ) -> EvaluationNarrative:
        """Вернуть валидный EvaluationNarrative, добавив decision в retry feedback при ошибке."""
        return self._validated(
            "research-evaluator",
            package,
            EvaluationNarrative,
            f"Детерминированное решение: {result.decision.value}.",
        )

    def _validated(
        self,
        role: str,
        package: ContextPackage,
        contract: type[ResponseContract],
        initial_feedback: str | None = None,
    ) -> ResponseContract:
        feedback = initial_feedback
        error: ValidationError | None = None
        for _ in range(self.max_attempts):
            raw_response = self.invoker.invoke(role, package, feedback)
            try:
                return cast(ResponseContract, contract.model_validate_json(raw_response))
            except ValidationError as validation_error:
                error = validation_error
                feedback = self._validation_feedback(validation_error)
        assert error is not None
        raise error

    @staticmethod
    def _validation_feedback(error: ValidationError) -> str:
        """Вернуть безопасный feedback без значений невалидного внешнего payload."""
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"])
            for item in error.errors(include_url=False, include_input=False)
        )
        return f"Structured validation failed. Исправь JSON fields: {fields}."
