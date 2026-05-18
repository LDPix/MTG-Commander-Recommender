export interface CollectionImportResponse {
  collection_id: string;
  session_id: string;
  imported_count: number;
  unknown_cards: string[];
  warnings: Array<Record<string, unknown>>;
  change_summary: CollectionChangeSummary | null;
  success: boolean;
  error: string | null;
}

export interface CollectionChangeSummary {
  added_count: number;
  removed_count: number;
  quantity_changed_count: number;
  unchanged_count: number;
  added_cards: string[];
  removed_cards: string[];
  quantity_changed_cards: string[];
}

export interface Explanation {
  summary: string;
  owned_highlights: string[];
  archetype_label: string;
  missing_core_notes: string[];
}

export type SupportConfidence = "curated" | "profiled" | "fallback";

export interface CommanderRecommendation {
  oracle_id: string;
  name: string;
  color_identity: string[];
  fit_score: number;
  archetype: string;
  owned_count: number;
  owned_percentage: number;
  explanation: Explanation;
  roles_covered: Record<string, number>;
  support_confidence: SupportConfidence;
}

export interface RecommendationResponse {
  session_id: string;
  recommendations: CommanderRecommendation[];
  total: number;
}

export interface DeckCard {
  oracle_id: string;
  name: string;
  is_owned: boolean;
  quantity: number;
  roles: string[];
  assigned_role: string | null;
  secondary_role_credit: Record<string, number>;
  package_ids: string[];
  selection_reason: string;
  synergy_score: number;
}

export interface QuotaStatus {
  role: string;
  target_min: number;
  target_max: number;
  actual_count: number;
  is_satisfied: boolean;
  warning: string | null;
  credit_sum: number;
  credit_satisfied: boolean;
  credit_warning: string | null;
}

export interface PackageBreakdown {
  package_id: string;
  label: string;
  confidence: number;
  card_oracle_ids: string[];
  top_roles: string[];
  activation_status: string;
  selected_count: number;
  raw_selected_count: number;
}

export type UpgradePriority = "core" | "recommended" | "optional";

export interface UpgradeSuggestion {
  oracle_id: string;
  name: string;
  priority: UpgradePriority;
  improves_roles: string[];
  improves_packages: string[];
  reason: string;
  impact_score: number;
  replaces_or_supplements: string[];
}

export interface CardExplanation {
  oracle_id: string;
  name: string;
  summary: string;
  evidence: string[];
  roles: string[];
  package_ids: string[];
  synergy_score: number;
  is_owned: boolean;
}

export interface GeneratedDeckResponse {
  deck_id: string;
  session_id: string;
  generation_status:
    | "success"
    | "failed_validation"
    | "failed_quality"
    | "needs_repair"
    | "low_confidence";
  commander: DeckCard;
  main_deck: DeckCard[];
  role_breakdown: Record<string, number>;
  quota_status: QuotaStatus[];
  package_breakdown: PackageBreakdown[];
  warnings: string[];
  owned_count: number;
  owned_percentage: number;
  is_valid: boolean;
  validation_errors: string[];
  upgrade_suggestions: UpgradeSuggestion[];
  card_explanations: Record<string, CardExplanation>;
  strategic_coherence: StrategicCoherenceReport | null;
}

export interface StrategicCoherenceReport {
  primary_plan: string | null;
  confidence: number;
  active_package_ids: string[];
  on_plan_count: number;
  off_plan_count: number;
  warning_card_oracle_ids: string[];
  warnings: string[];
}

export interface DeckExportResponse {
  format: "plaintext";
  text: string;
  warnings: string[];
}

export interface SavedDeckSummary {
  deck_id: string;
  session_id: string;
  commander_oracle_id: string;
  commander_name: string;
  created_at: string;
}

export interface SavedDeckListResponse {
  decks: SavedDeckSummary[];
}

export interface SavedDeckDetail {
  deck_id: string;
  session_id: string;
  commander_oracle_id: string;
  commander_name: string;
  created_at: string;
  deck: GeneratedDeckResponse;
}
