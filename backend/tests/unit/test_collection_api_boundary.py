"""Architecture boundary tests for FR-5A.

TC-FR-005A-01 / AT-FR-005A-UNIT-01:
    Collection retrieval API must not access private service/repository
    internals. The route for GET /api/v1/collections/{session_id} must
    delegate retrieval through a public CollectionService method.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import app.api.v1.collection as collection_module
from app.api.v1.collection import get_collection


def _get_collection_source() -> str:
    """Return source lines of the get_collection route function."""
    return inspect.getsource(get_collection)


def _collection_module_source() -> str:
    """Return the full source of the collection API module."""
    path = Path(collection_module.__file__)  # type: ignore[arg-type]
    return path.read_text()


# ---------------------------------------------------------------------------
# TC-FR-005A-01: API route must not access private service internals
# ---------------------------------------------------------------------------


def test_get_collection_route_does_not_access_private_repo() -> None:
    """FR-5A: get_collection route must not reference service._repo."""
    source = _get_collection_source()
    assert "._repo" not in source, (
        "get_collection route accesses service._repo directly. "
        "Retrieval must go through a public CollectionService method (FR-5A)."
    )


def test_get_collection_route_does_not_access_private_attributes() -> None:
    """FR-5A: get_collection route must not access any private service attributes."""
    source = _get_collection_source()
    # Any attribute starting with _ on the service variable is a boundary violation.
    # We parse the AST to detect attribute accesses of the form `service._*`.
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id == "service"
        ):
            violations.append(node.attr)
    assert not violations, (
        f"get_collection route accesses private service attributes: {violations}. "
        "API routes must not reach into private service internals (FR-5A)."
    )


def test_collection_module_does_not_import_collection_repository_for_route() -> None:
    """Boundary check: the collection API module imports CollectionRepository only
    for dependency wiring in _build_service, not for direct use in route handlers."""
    # This is a soft check — the import is legitimately used in _build_service.
    # The hard check is that get_collection itself does not reference _repo.
    source = _get_collection_source()
    assert "CollectionRepository" not in source, (
        "get_collection route directly references CollectionRepository. "
        "Repository access must remain behind the service boundary (FR-5A)."
    )
