import { useMemo, useState } from "react";
import {
  exportPlaintextDeck,
  fetchRecommendations,
  generateDeck,
  importCollection
} from "./api/client";
import type {
  CardExplanation,
  CollectionImportResponse,
  CommanderRecommendation,
  DeckCard,
  GeneratedDeckResponse,
  RecommendationResponse,
  UpgradePriority,
  UpgradeSuggestion
} from "./types/api";

const upgradePriorities: UpgradePriority[] = ["core", "recommended", "optional"];

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
  const [selectedCard, setSelectedCard] = useState<DeckCard | null>(null);
  const [exportText, setExportText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [isImporting, setIsImporting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

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
      setSelectedCard(generatedDeck.commander);
      setExportText("");
      setStatus(`Generated ${recommendation.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deck generation failed.");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleExportDeck() {
    if (!deck) {
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

  const selectedExplanation = selectedCard
    ? deck?.card_explanations[selectedCard.oracle_id]
    : undefined;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Commander Deck Recommender</p>
          <h1>Collection to deck, in one working flow</h1>
        </div>
        <span className="session-pill">{sessionId}</span>
      </header>

      {(status || error) && (
        <section className="status-row" aria-live="polite">
          {status && <p>{status}</p>}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>
      )}

      <div className="workflow-grid">
        <section className="panel">
          <div className="panel-heading">
            <p className="step-label">1. Import</p>
            <h2>Collection CSV</h2>
          </div>
          <input
            aria-label="Collection CSV"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => {
              setSelectedFile(event.target.files?.[0] ?? null);
              setError("");
            }}
          />
          <div className="action-row">
            <button onClick={handleImport} disabled={isImporting}>
              {isImporting ? "Importing..." : "Import collection"}
            </button>
            <button
              className="secondary"
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
              Retry
            </button>
          </div>
          {importResult && <ImportSummary result={importResult} />}
        </section>

        <section className="panel recommendations-panel">
          <div className="panel-heading">
            <p className="step-label">2. Recommend</p>
            <h2>Ranked commanders</h2>
          </div>
          <RecommendationList
            recommendations={recommendations?.recommendations ?? []}
            isGenerating={isGenerating}
            onGenerateDeck={handleGenerateDeck}
          />
        </section>
      </div>

      {deck && (
        <DeckViewer
          deck={deck}
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
          <article className="recommendation-item">
            <div>
              <span className="rank">#{index + 1}</span>
              <h3>{recommendation.name}</h3>
              <p>{recommendation.explanation.summary}</p>
              <div className="metric-row">
                <span>Fit {(recommendation.fit_score * 100).toFixed(0)}%</span>
                <span>Owned {recommendation.owned_count}</span>
                <span>{recommendation.explanation.archetype_label}</span>
              </div>
              {recommendation.explanation.owned_highlights.length > 0 && (
                <p className="support-line">
                  Owned support:{" "}
                  {recommendation.explanation.owned_highlights.join(", ")}
                </p>
              )}
              {recommendation.explanation.missing_core_notes.length > 0 && (
                <p className="missing-line">
                  Missing: {recommendation.explanation.missing_core_notes.join(", ")}
                </p>
              )}
            </div>
            <button
              onClick={() => onGenerateDeck(recommendation)}
              disabled={isGenerating}
            >
              Generate deck
            </button>
          </article>
        </li>
      ))}
    </ol>
  );
}

function DeckViewer({
  deck,
  selectedCard,
  selectedExplanation,
  exportText,
  onSelectCard,
  onExportDeck
}: {
  deck: GeneratedDeckResponse;
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

  return (
    <section className="deck-grid">
      <div className="panel deck-list-panel">
        <div className="panel-heading deck-heading">
          <div>
            <p className="step-label">3. Inspect</p>
            <h2>Deck viewer</h2>
          </div>
          <button onClick={onExportDeck}>Export plaintext</button>
        </div>

        <h3>Commander</h3>
        <CardRow card={deck.commander} onSelectCard={onSelectCard} />

        <h3>Main Deck</h3>
        <div className="card-list">
          {deck.main_deck.map((card) => (
            <CardRow key={card.oracle_id} card={card} onSelectCard={onSelectCard} />
          ))}
        </div>

        {exportText && (
          <textarea
            aria-label="Plaintext deck export"
            className="export-box"
            readOnly
            value={exportText}
          />
        )}
      </div>

      <aside className="analysis-stack">
        <section className="panel">
          <h2>Role breakdown</h2>
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
                  className={quota.is_satisfied ? "quota-ok" : "quota-warning"}
                >
                  {quota.role}: {quota.actual_count}/{quota.target_min}-
                  {quota.target_max}
                  {quota.warning ? ` - ${quota.warning}` : ""}
                </p>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Package breakdown</h2>
          {deck.package_breakdown.length === 0 ? (
            <p className="empty-state">No package clusters returned.</p>
          ) : (
            deck.package_breakdown.map((pkg) => (
              <div className="package-row" key={pkg.package_id}>
                <strong>{pkg.label}</strong>
                <span>{(pkg.confidence * 100).toFixed(0)}%</span>
                <p>{pkg.top_roles.join(", ") || "No dominant role"}</p>
              </div>
            ))
          )}
        </section>

        <section className="panel">
          <h2>Upgrade suggestions</h2>
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
    </section>
  );
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
      <section className="panel">
        <h2>Card explanation</h2>
        <p className="empty-state">Select a card to inspect why it was included.</p>
      </section>
    );
  }

  const roles = explanation?.roles.length ? explanation.roles : card.roles;
  const packageIds = explanation?.package_ids.length
    ? explanation.package_ids
    : card.package_ids;

  return (
    <section className="panel explanation-panel">
      <h2>Card explanation</h2>
      <h3>{card.name}</h3>
      <p>{explanation?.summary ?? card.selection_reason}</p>
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
