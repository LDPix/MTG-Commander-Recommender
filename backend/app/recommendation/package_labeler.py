"""SC-GRAPH-003: Assign human-readable labels to detected packages."""
from __future__ import annotations

from app.models.deck import PackageCluster


ROLE_TO_LABEL: dict[str, str] = {
    "ARISTOCRATS_SYNERGY": "sacrifice/aristocrats package",
    "LANDFALL_SYNERGY": "landfall package",
    "BLINK_SYNERGY": "blink/ETB package",
    "SPELLSLINGER_SYNERGY": "spellslinger package",
    "TRIBAL_SUPPORT": "tribal support package",
    "RECURSION": "graveyard recursion package",
    "SACRIFICE_OUTLET": "sacrifice outlet package",
    "TOKEN_MAKER": "token creation package",
}

CONSERVATIVE_LABELS: dict[str, str] = {
    # fallback when confidence < 0.5
    "ARISTOCRATS_SYNERGY": "black value package",
    "LANDFALL_SYNERGY": "green value package",
    "BLINK_SYNERGY": "utility package",
    "SPELLSLINGER_SYNERGY": "spells package",
    "TRIBAL_SUPPORT": "tribal package",
    "RECURSION": "graveyard package",
    "SACRIFICE_OUTLET": "utility package",
    "TOKEN_MAKER": "token package",
}


class PackageLabeler:
    def label(self, cluster: PackageCluster) -> PackageCluster:
        """Assign label. confidence < 0.5 → conservative label."""
        role_key = cluster.top_roles[0] if cluster.top_roles else ""

        if cluster.confidence >= 0.5:
            assigned_label = ROLE_TO_LABEL.get(role_key, f"{role_key.lower()} package")
        else:
            assigned_label = CONSERVATIVE_LABELS.get(role_key, f"{role_key.lower()} package")

        return PackageCluster(
            package_id=cluster.package_id,
            label=assigned_label,
            confidence=cluster.confidence,
            card_oracle_ids=cluster.card_oracle_ids,
            top_roles=cluster.top_roles,
        )
