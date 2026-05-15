"""Integration tests for the commander recommendation API (SC-API-002)."""
from __future__ import annotations

import io

import pytest

from tests.fixtures.sample_csv_collections import VALID_COLLECTION_CSV


def _import_collection(api_client, session_id: str) -> None:
    """Import the sample CSV collection for the given session."""
    file = io.BytesIO(VALID_COLLECTION_CSV.encode())
    resp = api_client.post(
        "/api/v1/collections/import",
        files={"file": ("collection.csv", file, "text/csv")},
        headers={"X-Session-Id": session_id},
    )
    assert resp.status_code == 200


class TestRecommendationAPI:
    def test_recommendation_api_returns_ranked_commanders(self, api_client):
        _import_collection(api_client, "rec-session-1")
        resp = api_client.get("/api/v1/recommendations/rec-session-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)
        assert data["total"] == len(data["recommendations"])

    def test_recommendation_api_includes_fit_score(self, api_client):
        _import_collection(api_client, "rec-session-2")
        resp = api_client.get("/api/v1/recommendations/rec-session-2")
        assert resp.status_code == 200
        for rec in resp.json()["recommendations"]:
            assert "fit_score" in rec
            assert 0.0 <= rec["fit_score"] <= 1.0

    def test_recommendation_api_includes_explanation(self, api_client):
        _import_collection(api_client, "rec-session-3")
        resp = api_client.get("/api/v1/recommendations/rec-session-3")
        assert resp.status_code == 200
        for rec in resp.json()["recommendations"]:
            assert "explanation" in rec
            exp = rec["explanation"]
            assert exp["summary"]
            assert "archetype_label" in exp
            assert isinstance(exp["owned_highlights"], list)
            assert isinstance(exp["missing_core_notes"], list)

    def test_recommendation_api_requires_collection(self, api_client):
        resp = api_client.get("/api/v1/recommendations/session-does-not-exist-xyz")
        assert resp.status_code == 404

    def test_recommendation_api_is_deterministic(self, api_client):
        _import_collection(api_client, "rec-session-det")
        r1 = api_client.get("/api/v1/recommendations/rec-session-det").json()
        r2 = api_client.get("/api/v1/recommendations/rec-session-det").json()
        assert r1 == r2
