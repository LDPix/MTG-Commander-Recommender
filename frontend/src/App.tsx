import { useMemo, useState } from "react";
import {
  exportPlaintextDeck,
  fetchRecommendations,
  fetchSavedDeckDetail,
  fetchSavedDecks,
  generateDeck,
  importCollection
} from "./api/client";
import type {
  CardExplanation,
  CollectionImportResponse,
  CommanderRecommendation,
  DeckCard,
  GeneratedDeckResponse,
  QuotaStatus,
  RecommendationResponse,
  SavedDeckSummary,
  SupportConfidence,
  UpgradePriority,
  UpgradeSuggestion
} from "./types/api";

const upgradePriorities: UpgradePriority[] = ["core", "recommended", "optional"];

function shouldShowCreditStatus(quota: QuotaStatus): boolean {
  return quota.credit_satisfied !== quota.is_satisfied || Boolean(quota.credit_warning);
}

function isDeckExportable(deck: GeneratedDeckResponse): boolean {
  return (
    deck.generation_status === "success" &&
    deck.is_valid &&
    deck.validation_errors.length === 0
  );
}

function makeSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `session-${crypto.randomUUID()}`;
  }

  return `session-${Date.now().toString(36)}`;
}

export default function App() {
  const [sessionId] = useState(makeSessionId);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importResult, setImportResult] = useState<CollectionImportResponse | null>(
    null
  );
  const [recommendations, setRecommendations] =
    useState<RecommendationResponse | null>(null);
  const [deck, setDeck] = useState<GeneratedDeckResponse | null>(null);
  const [deckSource, setDeckSource] = useState<"new" | "saved" | null>(null);
  const [savedDecks, setSavedDecks] = useState<SavedDeckSummary[]>([]);
  const [selectedCard, setSelectedCard] = useState<DeckCard | null>(null);
  const [exportText, setExportText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isLoadingSaved, setIsLoadingSaved] = useState(false);

  async function handleImport() {
    if (!selectedFile) {
      setError("Choose a CSV file before importing.");
      return;
    }

    setError("");
    setStatus("Importing collection...");
    setIsImporting(true);

    try {
      const result = await importCollection(selectedFile, sessionId);
      setImportResult(result);
      setStatus(`Imported ${result.imported_count} cards.`);
      const nextRecommendations = await fetchRecommendations(result.session_id);
      setRecommendations(nextRecommendations);
      setStatus(`Found ${nextRecommendations.total} commander recommendations.`);
      try {
        const saved = await fetchSavedDecks(sessionId);
        setSavedDecks(saved.decks);
      } catch {
        // Non-critical: saved deck list does not block import flow
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
      setStatus("");
    } finally {
      setIsImporting(false);
    }
  }

  async function handleGenerateDeck(recommendation: CommanderRecommendation) {
    setError("");
    setStatus(`Generating ${recommendation.name} deck...`);
    setIsGenerating(true);

    try {
      const generatedDeck = await generateDeck(
        sessionId,
        recommendation.oracle_id
      );
      setDeck(generatedDeck);
      setDeckSource("new");
      setSelectedCard(generatedDeck.commander);
      setExportText("");
      setStatus(
        isDeckExportable(generatedDeck)
          ? `Generated ${recommendation.name}.`
          : `Generation failed validation for ${recommendation.name}.`
      );
      try {
        const saved = await fetchSavedDecks(sessionId);
        setSavedDecks(saved.decks);
      } catch {
        // Non-critical: saved deck list refresh does not block deck generation flow
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deck generation failed.");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleExportDeck() {
    if (!deck || !isDeckExportable(deck)) {
      setError("Invalid generated decks cannot be exported.");
      return;
    }

    setError("");
    try {
      const exported = await exportPlaintextDeck(deck);
      setExportText(exported.text);
      setStatus("Plaintext export is ready.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
    }
  }

  async function handleOpenSavedDeck(savedDeckId: string) {
    setError("");
    setIsLoadingSaved(true);
    try {
      const detail = await fetchSavedDeckDetail(savedDeckId, sessionId);
      setDeck(detail.deck);
      setDeckSource("saved");
      setSelectedCard(detail.deck.commander);
      setExportText("");
      setStatus(`Opened saved deck: ${detail.commander_name}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved deck.");
    } finally {
      setIsLoadingSaved(false);
    }
  }

  const selectedExplanation = selectedCard
    ? deck?.card_explanations[selectedCard.oracle_id]
    : undefined;

  return (
    <main className="app-shell">
      <header className="page-header">
        <div className="header-content">
          <p className="header-eyebrow">Commander Deck Recommender</p>
          <h1 className="header-title">Turn your collection into a playable deck</h1>
          <p className="header-subtitle">
            Import your collection, review best-fit commanders, and generate a
            complete deck in minutes.
          </p>
        </div>
        <span className="session-badge">{sessionId}</span>
      </header>

      {(status || error) && (
        <div aria-live="polite" className="alerts-area">
          {status && (
            <div className="alert alert--success">
              <p>{status}</p>
            </div>
          )}
          {error && (
            <div className="alert alert--error" role="alert">
              <p>{error}</p>
            </div>
          )}
        </div>
      )}

      <div className="workflow-grid">
        <section className="surface-card">
          <p className="section-label">Step 1</p>
          <h2 className="section-title">Collection CSV</h2>
          <p className="section-subtitle">Upload your card collection file to get started.</p>

          <div className="file-upload-zone">
            <input
              aria-label="Collection CSV"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                setSelectedFile(event.target.files?.[0] ?? null);
                setError("");
              }}
            />
            <div className="file-upload-prompt">
              {selectedFile ? (
                <>
                  <p className="file-selected-name">{selectedFile.name}</p>
                  <p className="file-upload-hint">Ready to import</p>
                </>
              ) : (
                <>
                  <p className="file-upload-title">Choose a CSV file</p>
                  <p className="file-upload-hint">or drag and drop</p>
                </>
              )}
            </div>
          </div>

          <div className="btn-row">
            <button
              className="btn-primary"
              onClick={handleImport}
              disabled={isImporting}
            >
              {isImporting ? "Importing..." : "Import collection"}
            </button>
            <button
              className="btn-secondary"
              onClick={() => {
                setImportResult(null);
                setRecommendations(null);
                setDeck(null);
                setSelectedCard(null);
                setExportText("");
                setStatus("");
                setError("");
              }}
            >
              Reset
            </button>
          </div>

          {importResult && <ImportSummary result={importResult} />}
        </section>

        <section className="surface-card">
          <p className="section-label">Step 2</p>
          <h2 className="section-title">Ranked commanders</h2>
          <p className="section-subtitle">Sorted by collection fit and archetype match.</p>
          <RecommendationList
            recommendations={recommendations?.recommendations ?? []}
            isGenerating={isGenerating}
            onGenerateDeck={handleGenerateDeck}
          />
        </section>
      </div>

      {importResult && (
        <section className="surface-card saved-decks-section">
          <h2 className="section-title">Saved decks</h2>
          <SavedDeckList
            savedDecks={savedDecks}
            isLoading={isLoadingSaved}
            onOpenSavedDeck={handleOpenSavedDeck}
          />
        </section>
      )}

      {deck && deckSource && (
        <DeckViewer
          deck={deck}
          deckSource={deckSource}
          selectedCard={selectedCard}
          selectedExplanation={selectedExplanation}
          exportText={exportText}
          onSelectCard={setSelectedCard}
          onExportDeck={handleExportDeck}
        />
      )}
    </main>
  );
}

function ImportSummary({ result }: { result: CollectionImportResponse }) {
  return (
    <div className="summary-box">
      <strong>Import summary</strong>
      <p>{result.imported_count} cards imported.</p>
      {result.unknown_cards.length > 0 && (
        <div>
          <h3>Unknown cards</h3>
          <ul>
            {result.unknown_cards.map((card) => (
              <li key={card}>{card}</li>
            ))}
          </ul>
        </div>
      )}
      {result.warnings.length > 0 && (
        <div>
          <h3>Malformed rows</h3>
          <ul>
            {result.warnings.map((warning, index) => (
              <li key={index}>{JSON.stringify(warning)}</li>
            ))}
          </ul>
        </div>
      )}
      {result.change_summary && (
        <div className="change-summary">
          <h3>Change summary</h3>
          <div className="change-metrics">
            <span>Added {result.change_summary.added_count}</span>
            <span>Removed {result.change_summary.removed_count}</span>
            <span>
              Quantity changed {result.change_summary.quantity_changed_count}
            </span>
            <span>Unchanged {result.change_summary.unchanged_count}</span>
          </div>
          <ChangeList label="Added cards" cards={result.change_summary.added_cards} />
          <ChangeList
            label="Removed cards"
            cards={result.change_summary.removed_cards}
          />
          <ChangeList
            label="Quantity changes"
            cards={result.change_summary.quantity_changed_cards}
          />
        </div>
      )}
    </div>
  );
}

function ChangeList({ label, cards }: { label: string; cards: string[] }) {
  if (cards.length === 0) {
    return null;
  }

  return (
    <div>
      <strong>{label}</strong>
      <ul>
        {cards.map((card) => (
          <li key={`${label}-${card}`}>{card}</li>
        ))}
      </ul>
    </div>
  );
}

function RecommendationList({
  recommendations,
  isGenerating,
  onGenerateDeck
}: {
  recommendations: CommanderRecommendation[];
  isGenerating: boolean;
  onGenerateDeck: (recommendation: CommanderRecommendation) => void;
}) {
  if (recommendations.length === 0) {
    return <p className="empty-state">Import a collection to see commanders.</p>;
  }

  return (
    <ol className="recommendation-list">
      {recommendations.map((recommendation, index) => (
        <li key={recommendation.oracle_id}>
          <article className={`commander-card${index === 0 ? " commander-card--best" : ""}`}>
            <div className="commander-card-top">
              <span className={`rank-badge${index === 0 ? " rank-badge--gold" : ""}`}>
                #{index + 1}
              </span>
              <div className="commander-card-identity">
                <h3 className="commander-name">{recommendation.name}</h3>
                <div className="chip-row">
                  {index === 0 && (
                    <span className="best-match-tag">Best match</span>
                  )}
                  <span className="chip chip--green">
                    {recommendation.explanation.archetype_label}
                  </span>
                  <span className="chip chip--gold">
                    Fit {(recommendation.fit_score * 100).toFixed(0)}%
                  </span>
                  <span className="chip chip--neutral">
                    {recommendation.owned_count} owned
                  </span>
                  <SupportConfidenceBadge confidence={recommendation.support_confidence} />
                </div>
              </div>
            </div>

            <p className="commander-summary">
              {recommendation.explanation.summary}
            </p>

            {recommendation.explanation.owned_highlights.length > 0 && (
              <div className="commander-detail-section">
                <span className="detail-label">Top owned support</span>
                <p className="detail-text">
                  {recommendation.explanation.owned_highlights.join(", ")}
                </p>
              </div>
            )}

            {recommendation.explanation.missing_core_notes.length > 0 && (
              <div className="commander-detail-section">
                <span className="detail-label">Key missing cards</span>
                <p className="detail-text detail-text--missing">
                  {recommendation.explanation.missing_core_notes.join(", ")}
                </p>
              </div>
            )}

            <div className="commander-cta">
              <button
                className="btn-primary"
                onClick={() => onGenerateDeck(recommendation)}
                disabled={isGenerating}
              >
                Generate deck
              </button>
            </div>
          </article>
        </li>
      ))}
    </ol>
  );
}

function SupportConfidenceBadge({ confidence }: { confidence: SupportConfidence }) {
  if (confidence === "curated") {
    return <span className="chip chip--curated" aria-label="Curated recommendation">Curated</span>;
  }
  if (confidence === "profiled") {
    return <span className="chip chip--profiled" aria-label="Profiled recommendation">Profiled</span>;
  }
  return null;
}

function SavedDeckList({
  savedDecks,
  isLoading,
  onOpenSavedDeck
}: {
  savedDecks: SavedDeckSummary[];
  isLoading: boolean;
  onOpenSavedDeck: (id: string) => void;
}) {
  if (isLoading) {
    return <p className="empty-state">Loading saved decks...</p>;
  }
  if (savedDecks.length === 0) {
    return <p className="empty-state">No saved decks yet.</p>;
  }
  return (
    <ul className="saved-deck-list">
      {savedDecks.map((d) => (
        <li key={d.deck_id} className="saved-deck-item">
          <span className="saved-commander-name">{d.commander_name}</span>
          <span className="saved-deck-date">
            {new Date(d.created_at).toLocaleString()}
          </span>
          <button
            className="btn-secondary btn-sm"
            onClick={() => onOpenSavedDeck(d.deck_id)}
          >
            Open
          </button>
        </li>
      ))}
    </ul>
  );
}

function DeckViewer({
  deck,
  deckSource,
  selectedCard,
  selectedExplanation,
  exportText,
  onSelectCard,
  onExportDeck
}: {
  deck: GeneratedDeckResponse;
  deckSource: "new" | "saved";
  selectedCard: DeckCard | null;
  selectedExplanation?: CardExplanation;
  exportText: string;
  onSelectCard: (card: DeckCard) => void;
  onExportDeck: () => void;
}) {
  const groupedUpgrades = useMemo(
    () => groupUpgrades(deck.upgrade_suggestions),
    [deck.upgrade_suggestions]
  );
  const exportable = isDeckExportable(deck);

  return (
    <div className="deck-section">
      <div className="deck-grid">
        <div className="surface-card">
          <div className="deck-panel-header">
            <div>
              <p className="section-label">Step 3</p>
              <h2 className="section-title">Deck viewer</h2>
              <span className="deck-source-badge" data-source={deckSource}>
                {deckSource === "saved" ? "Saved deck" : "New deck"}
              </span>
            </div>
            <button
              className="btn-secondary btn-sm"
              onClick={onExportDeck}
              disabled={!exportable}
            >
              Export plaintext
            </button>
          </div>

          {!exportable && (
            <div className="alert alert--error invalid-deck-alert">
              <p>{generationFailureCopy(deck)}</p>
            </div>
          )}

          {deck.validation_errors.length > 0 && (
            <ul className="validation-error-list">
              {deck.validation_errors.map((validationError) => (
                <li key={validationError}>{validationError}</li>
              ))}
            </ul>
          )}

          {exportText && (
            <textarea
              aria-label="Plaintext deck export"
              className="export-box"
              readOnly
              value={exportText}
            />
          )}

          <h3>Commander</h3>
          <CardRow card={deck.commander} onSelectCard={onSelectCard} />

          <h3>Main Deck</h3>
          <div className="card-list">
            {deck.main_deck.map((card) => (
              <CardRow key={card.oracle_id} card={card} onSelectCard={onSelectCard} />
            ))}
          </div>
        </div>

        <aside className="analysis-stack">
          <section className="surface-card">
            <h2 className="section-title">Role breakdown</h2>
            <dl className="breakdown-list">
              {Object.entries(deck.role_breakdown).map(([role, count]) => (
                <div key={role}>
                  <dt>{role}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
            {deck.quota_status.length > 0 && (
              <div className="warnings-list">
                <h3>Quota warnings</h3>
                {deck.quota_status.map((quota) => (
                  <p
                    key={quota.role}
                    className={
                      quota.is_satisfied && quota.credit_satisfied
                        ? "quota-ok"
                        : "quota-warning"
                    }
                  >
                    {quota.role}: {quota.actual_count}/{quota.target_min}-
                    {quota.target_max}
                    {shouldShowCreditStatus(quota)
                      ? `, credit ${quota.credit_sum}/${quota.target_min}`
                      : ""}
                    {quota.warning ? ` - ${quota.warning}` : ""}
                    {quota.credit_warning ? ` - ${quota.credit_warning}` : ""}
                  </p>
                ))}
              </div>
            )}
          </section>

          <StrategicCoherencePanel deck={deck} />

          <section className="surface-card">
            <h2 className="section-title">Package breakdown</h2>
            {deck.package_breakdown.length === 0 ? (
              <p className="empty-state">No package clusters returned.</p>
            ) : (
              deck.package_breakdown.map((pkg) => (
                <div className="package-row" key={pkg.package_id}>
                  <div className="package-row-top">
                    <strong>{pkg.label}</strong>
                    <span>{(pkg.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <p>
                    {formatPackageStatus(pkg.activation_status)} - {pkg.selected_count} core selected
                    {pkg.raw_selected_count !== pkg.selected_count
                      ? ` (${pkg.raw_selected_count} raw)`
                      : ""}
                  </p>
                  <p>{pkg.top_roles.join(", ") || "No dominant role"}</p>
                </div>
              ))
            )}
          </section>

          <section className="surface-card">
            <h2 className="section-title">Upgrade suggestions</h2>
            {upgradePriorities.map((priority) => (
              <div key={priority} className="upgrade-group">
                <h3>{priority}</h3>
                {groupedUpgrades[priority].length === 0 ? (
                  <p className="empty-state">No {priority} upgrades.</p>
                ) : (
                  groupedUpgrades[priority].map((upgrade) => (
                    <article key={upgrade.oracle_id} className="upgrade-item">
                      <strong>{upgrade.name}</strong>
                      <p>{upgrade.reason}</p>
                    </article>
                  ))
                )}
              </div>
            ))}
          </section>

          <ExplanationPanel card={selectedCard} explanation={selectedExplanation} />
        </aside>
      </div>
    </div>
  );
}

function StrategicCoherencePanel({ deck }: { deck: GeneratedDeckResponse }) {
  const report = deck.strategic_coherence;
  const warnings = report?.warnings.length ? report.warnings : deck.warnings;

  if (!report && warnings.length === 0) {
    return null;
  }

  return (
    <section className="surface-card">
      <h2 className="section-title">Strategic coherence</h2>
      {report?.primary_plan && (
        <p>
          Primary plan: <strong>{formatPlan(report.primary_plan)}</strong>
        </p>
      )}
      {report && (
        <div className="coherence-metrics">
          <span>Confidence {(report.confidence * 100).toFixed(0)}%</span>
          <span>On plan {report.on_plan_count}</span>
          <span>Off plan {report.off_plan_count}</span>
          <span>Warning candidates {report.warning_card_oracle_ids.length}</span>
        </div>
      )}
      {report && report.active_package_ids.length > 0 && (
        <p className="detail-text">
          Active packages: {report.active_package_ids.join(", ")}
        </p>
      )}
      {warnings.length > 0 && (
        <div className="coherence-warning-list">
          <h3>Deck warnings</h3>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function formatPlan(plan: string) {
  return plan
    .split(/[_-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatPackageStatus(status: string) {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function generationFailureCopy(deck: GeneratedDeckResponse) {
  if (deck.generation_status === "failed_quality") {
    return "Deck generation failed quality checks. Export is disabled until quota, coherence, and win-condition gaps are repaired.";
  }
  if (deck.generation_status === "needs_repair") {
    return "Deck generation needs repair before export.";
  }
  return "Generation failed validation. Export is disabled until the deck passes Commander legality checks.";
}

function CardRow({
  card,
  onSelectCard
}: {
  card: DeckCard;
  onSelectCard: (card: DeckCard) => void;
}) {
  return (
    <button className="card-row" onClick={() => onSelectCard(card)}>
      <span>
        {card.quantity} {card.name}
      </span>
      <span className={card.is_owned ? "owned-badge" : "missing-badge"}>
        {card.is_owned ? "owned" : "missing"}
      </span>
    </button>
  );
}

function ExplanationPanel({
  card,
  explanation
}: {
  card: DeckCard | null;
  explanation?: CardExplanation;
}) {
  if (!card) {
    return (
      <section className="surface-card">
        <h2 className="section-title">Card explanation</h2>
        <p className="empty-state">Select a card to inspect why it was included.</p>
      </section>
    );
  }

  const roles = explanation?.roles.length ? explanation.roles : card.roles;
  const packageIds = explanation?.package_ids.length
    ? explanation.package_ids
    : card.package_ids;

  return (
    <section className="surface-card">
      <h2 className="section-title">Card explanation</h2>
      <h3 className="explanation-card-name">{card.name}</h3>
      <p className="explanation-summary">
        {explanation?.summary ?? card.selection_reason}
      </p>
      <p className={card.is_owned ? "owned-text" : "missing-text"}>
        {card.is_owned ? "Owned card" : "Missing card"}
      </p>
      <div className="tag-row">
        {roles.length > 0 ? (
          roles.map((role) => <span key={role}>{role}</span>)
        ) : (
          <span>No role tags</span>
        )}
      </div>
      <div className="tag-row">
        {packageIds.length > 0 ? (
          packageIds.map((packageId) => <span key={packageId}>{packageId}</span>)
        ) : (
          <span>No package membership</span>
        )}
      </div>
      {explanation?.evidence.length ? (
        <ul>
          {explanation.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function groupUpgrades(upgrades: UpgradeSuggestion[]) {
  return upgradePriorities.reduce<Record<UpgradePriority, UpgradeSuggestion[]>>(
    (groups, priority) => {
      groups[priority] = upgrades.filter((upgrade) => upgrade.priority === priority);
      return groups;
    },
    { core: [], recommended: [], optional: [] }
  );
}
