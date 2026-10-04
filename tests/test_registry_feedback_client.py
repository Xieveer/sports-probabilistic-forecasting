"""S3 ListObjects transport для локального feedback importer."""

from __future__ import annotations

from typing import Any

from sports_forecast.deploy.registry_feedback_client import Boto3CandidateFeedbackStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        if "ContinuationToken" not in kwargs:
            return {
                "Contents": [{"Key": "prefix/candidates/install/one.jsonl"}],
                "IsTruncated": True,
                "NextContinuationToken": "page-2",
            }
        return {
            "Contents": [{"Key": "prefix/candidates/install/two.jsonl"}],
            "IsTruncated": False,
        }


def test_candidate_transport_lists_bounded_pages_and_uses_start_after() -> None:
    client = FakeS3Client()
    storage = Boto3CandidateFeedbackStorage(
        endpoint="https://object.example",
        bucket="registry",
        access_key_id="local-feedback-reader",
        secret_access_key="not-a-production-secret",
        client=client,
    )

    first, token = storage.list_keys(
        "prefix/candidates/install/",
        start_after="prefix/candidates/install/00000000000000000001-g",
        max_keys=1,
    )
    second, next_token = storage.list_keys(
        "prefix/candidates/install/", continuation_token=token, max_keys=1
    )

    assert first == ("prefix/candidates/install/one.jsonl",)
    assert second == ("prefix/candidates/install/two.jsonl",)
    assert next_token is None
    assert client.calls == [
        {
            "Bucket": "registry",
            "Prefix": "prefix/candidates/install/",
            "MaxKeys": 1,
            "StartAfter": "prefix/candidates/install/00000000000000000001-g",
        },
        {
            "Bucket": "registry",
            "Prefix": "prefix/candidates/install/",
            "MaxKeys": 1,
            "ContinuationToken": "page-2",
        },
    ]
