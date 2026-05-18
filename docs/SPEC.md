# MTG Commander Deck Recommender — Product Specification

## 1. Feature Context

- **Feature:** MTG Commander Deck Recommender
- **Description (Goal / Scope):** Application that analyzes a user's Magic: The Gathering collection and recommends Commander decks using graph-based synergy analysis, package detection, and role-aware deck construction.
- **Client:** MTG players / Commander players
- **Problem:** Commander players often own large collections but struggle to identify strong, synergistic decks they can build from existing cards.
- **Solution:** Import user collections, evaluate candidate commanders, detect synergistic packages, and generate playable Commander decks with upgrade recommendations.
- **Metrics:** Deck export rate, recommendation acceptance rate, user session duration, generated deck playability rating, frontend explanation engagement.
## 2. User Stories and Use Cases

### User Story 1

- **Role:** Commander player
- **User Story ID:** US-1
- **User Story:** As a Commander player, I want to import my collection, so that the app can recommend decks I can already build.
- **UX / User Flow:** Upload collection -> Parse cards -> Normalize card data -> Show owned commanders and archetypes
#### Use Case (+ Edges) BDD 1

- **Use Case ID:** UC-1.1
- **Given:** User has a collection export file.
- **When:** User uploads a supported collection file.
- **Then:** The system parses and stores the collection.
- **Input:** Collection file (CSV for MVP; Moxfield / Archidekt / Manabox are future scope)
- **Output:** Normalized collection database
- **State:** Collection imported
#### Functional Requirements

| Req ID | Requirement |
| --- | --- |
| FR-1 | System shall support importing collections from CSV in the MVP. |
| FR-2 | System shall normalize cards using Scryfall IDs. |
| FR-3 | System shall store owned quantities and printings. |

#### Non-Functional Requirements

| Req ID | Requirement |
| --- | --- |
| NFR-1 | Import should complete within 10 seconds for collections under 20,000 cards. |
| NFR-2 | Card parsing must tolerate malformed rows and partial imports. |
| NFR-3 | Collection data must persist for the active session in the MVP; account-backed persistence is future scope unless promoted. |

#### Use Case (+ Edges) BDD 2

- **Use Case ID:** UC-1.2
- **Given:** User has already imported a collection.
- **When:** User updates or reimports collection data.
- **Then:** Collection changes are merged and synchronized.
- **Input:** Updated collection export
- **Output:** Updated collection state
- **State:** Collection synchronized
#### Functional Requirements

| Req ID | Requirement |
| --- | --- |
| FR-4 | System shall detect duplicates and merge identical cards. |
| FR-5 | System shall allow reimport/replace updates in the MVP; manual collection edits are future scope unless promoted. |

#### Non-Functional Requirements

| Req ID | Requirement |
| --- | --- |
| NFR-4 | Synchronization should preserve data integrity. |
| NFR-5 | Reimported collection changes should be reflected in subsequent recommendations. |

### User Story 2

- **Role:** Commander player
- **User Story ID:** US-2
- **User Story:** As a Commander player, I want to receive recommended commanders and decklists, so that I can quickly build strong decks from my collection.
- **UX / User Flow:** Analyze collection -> Rank commanders -> Detect packages -> Generate decklists -> Show missing upgrades
#### Use Case BDD 1

- **Use Case ID:** UC-2.1
- **Given:** User has an imported collection.
- **When:** User requests commander recommendations.
- **Then:** The system displays ranked commanders with collection fit scores.
- **Input:** Imported collection
- **Output:** Ranked commander recommendations
- **State:** Recommendation generated
#### Functional Requirements

| Req ID | Requirement |
| --- | --- |
| FR-6 | System shall evaluate commander viability using owned cards, synergy density, and support confidence. |
| FR-7 | System shall compute collection fit percentages. |
| FR-8 | System shall suggest missing upgrade cards. |

#### Non-Functional Requirements

| Req ID | Requirement |
| --- | --- |
| NFR-6 | Recommendations should generate within 15 seconds. |
| NFR-7 | Commander rankings should remain deterministic for identical inputs. |

#### Use Case (+ Edges) BDD 2

- **Use Case ID:** UC-2.2
- **Given:** A commander recommendation has been selected.
- **When:** The user requests a generated deck.
- **Then:** The system generates a 100-card Commander decklist.
- **Input:** Commander selection
- **Output:** Playable decklist with role breakdown
- **State:** Deck generated
#### Functional Requirements

| Req ID | Requirement |
| --- | --- |
| FR-9 | System shall generate decks using graph-based synergy scoring. |
| FR-10 | System shall enforce Commander legality and color identity constraints. |
| FR-11 | System shall enforce deck quotas for lands, ramp, draw, and interaction using the MVP `default_playable` deck profile. |

#### Non-Functional Requirements

| Req ID | Requirement |
| --- | --- |
| NFR-8 | Generated decks should contain valid Commander-legal card counts. |
| NFR-9 | Deck generation should prioritize owned cards over missing cards. |

### User Story 3

- **User Story ID:** US-3
- **User Story:** As a Commander player, I want to understand why cards were selected, so that I can trust and customize generated decks.
- **UX / User Flow:** Open generated deck -> Inspect packages -> View synergy explanations -> Modify deck
#### Use Case (+ Edges) BDD 1

- **Use Case ID:** UC-3.1
- **Given:** A deck has been generated.
- **When:** The user inspects the deck analysis.
- **Then:** The system displays packages, role quotas, and synergy explanations.
- **Input:** Generated deck
- **Output:** Explainable deck analysis
- **State:** Deck inspection active
#### Functional Requirements

| Req ID | Requirement |
| --- | --- |
| FR-12 | System shall return detected card packages and clusters in backend/API responses; user-facing visualization is frontend scope. |
| FR-13 | System shall explain role quotas and synergy scores. |

#### Non-Functional Requirements

| Req ID | Requirement |
| --- | --- |
| NFR-10 | Explanations should be understandable to non-technical users. |
| NFR-11 | UI interactions should remain responsive when displaying role, package, upgrade, and explanation data. |

## 3. Architecture / Solution

### 3.1 Client Side

- **Client Type:** Web UI
- **User Entry Points:** Landing page, collection import, commander recommendations, deck viewer
- **Main Screens / Commands:** React + TypeScript frontend
- **Input / Output Format:** Responsive SPA for import, recommendations, deck viewing, role/package data, upgrades, explanations, and plaintext export
- Collection import, commander ranking, deck generation, deck inspection, and export
### 3.2 Backend Services

Graph views, package inspection, deck statistics

- Service Name
- **Responsibility:** Backend
- **Business Logic:** Python FastAPI service
- **API / Contract:** Graph construction, recommendation engine, optimization logic
- **Request Schema:** Collection ingestion, card tagging, commander scoring, deck generation
- **Response Schema:** Recommendation APIs, deck generation APIs, collection APIs
- Error Handling
### 3.3 Data Architecture and Flows

- **Area:** Storage
- **Main Entities (ER):** PostgreSQL + graph/cache layer
- **Relationships (ER):** Card metadata, collections, generated decks, synergy weights
- **Data Flow (DFD):** Scryfall bulk data, decklist co-occurrence data, generated graph edges
- Input Sources
- External Services
- Scryfall API / bulk data
### 3.4 Infrastructure

Card metadata and oracle text

- Commander decklist/co-occurrence dataset
- **Required Hardware / Resources:** Card legality, metadata, and synergy calculations
## 4. Recommendation Logic

- Commander-conditioned weighted graph using normalized co-occurrence metrics.
- Louvain/Leiden community detection for package extraction.
- Rule-based + oracle-text-derived role tagging.
- Quota-aware optimization with synergy scoring and legality constraints.
- Deck score = synergy + role coverage + ownership priority - redundancy penalties.
## 5. Work Plan

- Mapping: Use Case → Tasks
| Use Case | Primary Task | Task | Dependencies | DoD | Subtasks |
| --- | --- | --- | --- | --- | --- |
| UC-1.1 | Import user collection files and normalize card records | T-1 Collection Import & Normalization | Scryfall card identifiers; supported export formats selected | A user can import a supported collection file and see normalized owned cards. | ST-1, ST-2, ST-3 |
| UC-1.2 | Synchronize and replace collection state by reimport | T-1 Collection Import & Normalization | Initial import pipeline | Reimports update collection state without duplicate corruption and expose change summary data. | ST-4, ST-5 |
| UC-2.1 | Rank feasible commanders from the user collection | T-3 Commander Recommendation Engine | T-1, T-2 | System returns ranked commanders with fit score, archetype explanation, and missing upgrades. | ST-6, ST-7, ST-8 |
| UC-2.2 | Generate Commander-legal 100-card decklists | T-4 Deck Generation & Optimizer | T-1, T-2, T-3 | System generates a legal deck with role quotas, owned-card preference, and package coherence. | ST-9, ST-10 |
| UC-3.1 | Explain recommendations and support deck viewing/export | T-5 Explainability, Deck Viewer & Export | T-3, T-4 | User can inspect packages, role balance, upgrade suggestions, card reasons, and export a decklist. | ST-11, ST-12 |

## 6. Detailed Task Breakdown

### Task 1

- **Task ID:** T-1
- **Related Use Case:** UC-1.1, UC-1.2
- **Task Description:** Build the collection import, normalization, and reimport/update pipeline.
- **Dependencies:** Scryfall bulk data schema; selected export formats; database schema.
- **DoD:** CSV collection files can be imported, normalized to stable card IDs, and replaced or updated on reimport without duplicate corruption.
#### Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria |
| --- | --- | --- | --- |
| ST-1 | Implement CSV import parser for MVP collection files. | Supported CSV examples; collection schema. | Valid files import successfully; invalid rows are reported without aborting the whole import. |
| ST-2 | Normalize imported card names/printings to Scryfall IDs and store owned quantities. | Scryfall data ingestion. | Duplicate names and alternate printings resolve to canonical card records with quantity preserved. |
| ST-3 | Implement collection update flow: reimport, replace or merge duplicates according to selected import mode, and return change summary data. | ST-1, ST-2. | User can update collection and subsequent recommendation/deck requests use the changed owned-card counts. |

### Task 2

- **Task ID:** T-2
- **Related Use Case:** UC-2.1, UC-2.2, UC-3.1
- **Task Description:** Create the card metadata, role tagging, and archetype/package data layer used by recommendations.
- **Dependencies:** Scryfall/MTGJSON card data; selected Tagger/otag queries; manual override format.
- **DoD:** Cards have usable multi-label role tags and commander-relevant metadata for recommendation and explanation.
#### Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria |
| --- | --- | --- | --- |
| ST-4 | Ingest Scryfall bulk data and selected Scryfall Tagger otag search results. | Card data source access. | Local card table includes oracle text, type line, color identity, legality, keywords, and selected tags. |
| ST-5 | Build rule-based role tagger plus manual overrides for Commander-relevant cards. | ST-4. | Common roles such as ramp, draw, removal, wipes, protection, recursion, token maker, sacrifice outlet, payoff, and tutor are assigned with confidence scores. |

### Task 3

- **Task ID:** T-3
- **Related Use Case:** UC-2.1
- **Task Description:** Rank commanders the user can realistically build from their collection.
- **Dependencies:** T-1 collection data; T-2 card tags; commander/card legality data; co-occurrence data source.
- **DoD:** The system displays recommended commanders with collection fit, archetype/package hints, and missing key cards.
#### Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria |
| --- | --- | --- | --- |
| ST-6 | Identify legal candidate commanders from owned cards and optional user-selected missing commanders. | T-1, T-2. | Candidate list respects Commander color identity and banlist/legal status. |
| ST-7 | Compute commander score from owned synergy cards, role coverage, normalized co-occurrence, and archetype density. | ST-6; co-occurrence graph data. | Ranked commanders are deterministic and include explainable score components. |
| ST-8 | Generate missing-card upgrade suggestions for each recommended commander. | ST-7; card popularity/synergy data. | Each commander recommendation includes useful missing cards grouped by core, budget, and upgrade tiers. |

### Task 4

- **Task ID:** T-4
- **Related Use Case:** UC-2.2
- **Task Description:** Generate playable, legal Commander decks using graph synergy, detected packages, and role quotas.
- **Dependencies:** T-1, T-2, T-3; deck legality rules; optimizer/scoring module.
- **DoD:** For a selected commander, the app generates a legal 100-card deck with role balance, package coherence, and owned-card priority.
#### Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria |
| --- | --- | --- | --- |
| ST-9 | Build commander-conditioned weighted graph and detect packages/clusters for the candidate card pool. | T-2, T-3; co-occurrence data. | Graph uses normalized edge weights; package labels are derived from tag composition, oracle text, and signature cards. |
| ST-10 | Implement quota-aware deck selection and post-generation validation. | ST-9; role quota rules. | Generated deck satisfies color identity, singleton rules, card count, land/ramp/draw/interaction targets, and curve sanity checks. |

### Task 5

- **Task ID:** T-5
- **Related Use Case:** UC-3.1
- **Task Description:** Build the explainable deck viewer and export functionality.
- **Dependencies:** T-3 commander explanations; T-4 deck output; frontend deck UI components.
- **DoD:** User can understand why cards were selected, see role/package/upgrade data, and export the generated deck as plaintext.
#### Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria |
| --- | --- | --- | --- |
| ST-11 | Create deck analysis UI showing role quotas, package clusters, synergy reasons, and missing upgrades. | T-4 output format. | Deck viewer clearly displays role balance, owned/missing status, and selected package explanations. |
| ST-12 | Implement plaintext deck export for generated decks. | ST-11; deck validation endpoint. | User can export the generated list with commander/main-deck sections, quantities, and missing-card markings. |

## 7. Risks and Constraints

| Risk ID | Risk / Constraint | Impact | Mitigation | Owner / Area |
| --- | --- | --- | --- | --- |
| R-1 | Decklist licensing restrictions and API limitations. | May limit availability of commander co-occurrence data. | Use allowed/public datasets, user-submitted decks, or partnership data; cache only permitted derived metrics. | Data |
| R-2 | Popularity bias causing generic 'goodstuff' decks. | Generated decks may be powerful but not thematic. | Use normalized co-occurrence, package constraints, and role quotas instead of raw inclusion counts. | Recommendation |
| R-3 | Incorrect role tagging reducing deck quality. | Decks may miss ramp, draw, interaction, or win conditions. | Combine rule-based tags, selected Tagger labels, manual overrides, and user feedback loops. | Tagging |
| R-4 | Large graph computation costs for very large candidate pools. | Recommendation latency may be too high. | Limit candidate pools, precompute commander graphs, cache edge weights, and run optimization server-side. | Backend |
| R-5 | Need for explainability and user trust. | Users may reject recommendations without reasons. | Show role balance, packages, owned/missing cards, and card-level selection explanations. | UX |
| R-6 | Legal but strategically incoherent decks. | Users may receive a valid 100-card list that does not advance the commander's plan, such as random Treasure/Clue/Food/artifact-value piles in a mono-green commander deck. | Add strategic coherence gate, active-package thresholds, off-plan card limits, and negative regression fixtures. | Recommendation/QA |

## 8. Open Decisions

| Decision ID | Question | Recommended Default | Reason | Status |
| --- | --- | --- | --- | --- |
| D-1 | Which collection formats are supported in MVP? | CSV only. | Fastest path to validate demand while keeping parser complexity low; other deckbuilder imports are future scope. | Resolved |
| D-2 | Which commanders are supported initially? | Hybrid support: allow any legal resolved commander, but label support confidence as curated/profiled/fallback. | Avoids blocking exploration while making quality confidence transparent. | Resolved |
| D-3 | How are external decklists sourced? | Use legally permitted public data or user-provided decklists. | Avoid scraping/licensing risk. | Open |
| D-4 | Should MVP expose power-level selection? | No user-facing selector; use `default_playable` deck profile. | Power level is subjective and not yet explainable/tested enough for reliable user choice. | Resolved |

### 8.1 Commander Support Confidence

MVP commander support is hybrid:

- Any legal resolved commander may be recommended or used for deck generation.
- `curated` commanders have curated profile assumptions and golden regression coverage.
- `profiled` commanders have curated profile assumptions but incomplete or no golden regression coverage.
- `fallback` commanders are legal/resolved but depend on general color identity, role tags, ownership, and fallback synergy signals.

Initial profile list:

| Commander | Archetype/Profile | Support Confidence | Follow-up |
| --- | --- | --- | --- |
| Meren of Clan Nel Toth | Sacrifice / aristocrats / graveyard value | curated | Maintain golden coverage |
| Atraxa, Praetors' Voice | Proliferate / counters / multicolor value | curated | Maintain golden coverage |
| Prossh, Skyraider of Kher | Sacrifice / tokens | profiled | Add golden regression coverage before treating as curated |

### 8.2 Power Profile

The MVP has one deck profile: `default_playable`.

No MVP API or UI should ask for casual, focused, high-power, cEDH, or similar power-level choices. Future power profiles require documented quota/scoring changes, explanation copy, and regression tests before promotion.

## 9. MVP Scope and Prioritization

| Priority | Feature / Capability | Description | Included in MVP? | Notes |
| --- | --- | --- | --- | --- |
| P0 | Collection import | CSV import; normalize by Scryfall/oracle identity. | Yes | Required before any recommendation feature can work. |
| P0 | Commander recommendation | Rank legal commanders by collection fit, role coverage, synergy, and support confidence. | Yes | Hybrid model: curated/profiled commanders carry more confidence; fallback legal commanders remain allowed. |
| P0 | Deck generation | Generate legal 100-card Commander decks with `default_playable` role quotas and owned-card preference. | Yes | Must validate singleton, color identity, banlist, and commander count. No power-level selector in MVP. |
| P0 | Explainability | Show packages, role balance, owned/missing status, and why key cards were selected. | Yes | Needed to build user trust. |
| P1 | Deck editing and replacement suggestions | Allow users to remove cards and receive role-compatible replacement suggestions. | No | Future scope unless explicitly promoted. |
| P1 | Upgrade suggestions | Show missing cards grouped into cheap, core, and premium upgrades. | Yes | Strong product differentiator. |
| P2 | Full automatic support for all commanders | Generalize data and tagging to every legal commander. | No | Too risky for MVP; use after validation. |
| P2 | Power-level profiles | Let users choose casual, focused, high-power, or similar profiles. | No | Future scope once assumptions can be explained and tested. |
| P2 | User feedback learning | Let users rate recommendations and use feedback to tune scoring. | No | Useful after enough users/decks exist. |

## 10. Data Model

| Entity | Key Fields | Purpose | Notes |
| --- | --- | --- | --- |
| Card | scryfall_id, name, oracle_text, type_line, color_identity, legalities, mana_value | Canonical card metadata for legality, tagging, and display. | Loaded from Scryfall bulk data. |
| Printing | scryfall_id, set_code, collector_number, image_uri, rarity | Preserve imported collection printings and display images. | Can be optional in early MVP. |
| UserCollectionItem | user_id, scryfall_id/card_key, quantity, foil, source | Tracks owned cards and quantities. | Use canonical card identity for deck legality; retain printing for display. |
| RoleTag | card_id, tag, confidence, source | Multi-label card roles used for quotas and explanations. | Sources: rules, Tagger queries, manual override, learned signal. |
| CommanderProfile | commander_id, archetypes, default_quotas, supported_packages, support_confidence | Stores commander-specific assumptions and quality-controlled metadata. | MVP confidence labels: curated, profiled, fallback. |
| DeckProfile | profile_id, role_quota_policy, scoring_policy, explanation_copy | Stores deck profile assumptions for generation. | MVP has one profile: `default_playable`; user-facing power profiles are future scope. |
| GraphEdge | commander_or_scope, card_a, card_b, weight, metric, sample_size | Stores normalized co-occurrence/synergy between cards. | Avoid raw popularity-only edge weights. |
| GeneratedDeck | deck_id/session_id, commander_id, cards, score_breakdown, created_at | Carries generated decklists, explanations, validation, upgrades, and export input data. | Current MVP uses in-memory/API payloads rather than persisted deck history. |

## 11. Algorithm Details

| Component | Recommended Approach | Why | Acceptance Check |
| --- | --- | --- | --- |
| Edge weighting | Use normalized co-occurrence such as lift, PMI/NPMI, or cooccurrence / sqrt(freqA*freqB). | Reduces popularity bias from generic staples. | Staples do not dominate every package unless role-required. |
| Candidate pool | Owned legal cards + commander staples + archetype cards + optional upgrades; cap to 300–800 cards. | Keeps optimization fast and relevant. | Deck generation remains under target latency. |
| Package detection | Run Louvain/Leiden on the commander-conditioned weighted graph. | Finds naturally connected card groups. | Packages have coherent role/tag composition or are labeled as utility/staples. |
| Package labeling | Combine top role tags, oracle-text keywords, and signature/central cards. | Avoids pretending every cluster has a perfect semantic label. | Unclear clusters receive conservative labels. |
| Quotas | Start with `default_playable` baseline quotas, then adjust by commander, curve, colors, and learned archetype statistics. | Ensures decks are playable, not just dense graphs. | Generated role counts fall within configured target ranges; no power-level selector changes quotas in MVP. |
| Strategic coherence | Identify a primary commander plan, active packages, and off-plan warning candidates before finalizing flexible slots; use the result as a selection and repair constraint. Confidence must fail closed when unresolved validation, quota, package, or plan failures remain. | Prevents legal but incoherent piles of unrelated cards and prevents false-positive diagnostics. | Nonland cards primarily support assigned required roles, the commander plan, commander-relevant active packages, or high-quality staples; warning-only or contradictory analysis does not pass the gate. |
| Owned-card scoring | Apply owned priority only after commander relevance, active package status, role quality, and colorless strategy gates. | Prevents owned weak/off-plan cards from overpowering better commander-fit cards. | Owned bonus cannot cause off-plan colorless/filler cards to beat materially better role/package alternatives. |
| Role-slot accounting | Assign each selected card a primary quota role and bounded secondary credits before computing role breakdown, quota satisfaction, and coherence support. | Prevents multi-label tags from inflating role counts and on-plan counts. | Displayed role counts are plausible slot assignments, not raw all-tag totals. |
| Package activation | Treat candidate-pool packages as inactive evidence until commander relevance, selected-deck density, and viable enabler/payoff composition activate them, except explicit curated/profiled package commitments. | Prevents collection-heavy clusters from granting premature or commander-irrelevant package boosts. | Cards do not receive active-package priority merely because they appear in any detected candidate-pool package or dense unrelated package. |
| Package-core protection | Protect only active package-core cards during repair, not every card that appears in any detected cluster. | Keeps swap repair from freezing bad decks when package detection is broad. | Weak incidental package members remain removable. |
| Fallback commander plans | Infer or profile a concrete primary plan for fallback commanders before flexible-slot selection. | Avoids generic color-role piles for legal but unsupported commanders. | Greta-like decks show Food/sacrifice support; Toluz-like decks show connive/discard/graveyard support. |
| Profile identifier coverage | Bind commander profiles and negative fixtures to canonical resolver oracle IDs, with temporary name fallback only for bootstrap. | Ensures production decks receive the profile logic tested in fixtures. | Live Greta/Toluz catalog IDs activate the expected plan evidence. |
| Basic-land catalog audit | Backfill and audit canonical `Basic Land` metadata for regular and snow-covered basics in the live database/resolver. | Prevents false singleton failures caused by stale catalog records. | Live Snow-Covered Forest validates as basic in generated decks. |
| Basic-land virtual inventory | Treat every collection as having at least 99 copies of each canonical basic land. | Matches user expectation and prevents basics from polluting missing-card accounting. | Basic lands never show missing markers or upgrade suggestions. |
| Quality repair loop | Run deterministic multi-pass repair before returning failed-quality status. | Prevents weak capped-confidence lists from stopping after a narrow one-shot retry. | Hard quota/coherence failures are repaired when legal candidates exist; failed-quality appears only after repair exhaustion. |
| Quality-failure status | Add a status for legal but structurally failed decks after repair is exhausted. | Prevents weak capped-confidence lists from looking like normal recommendations. | Hard quota/coherence failures produce retry/repair, then failed-quality only if unresolved. |
| Package display counts | Compute package selected counts from assigned/core package members, not raw package membership. | Keeps package breakdown aligned with role-slot accounting. | Package display does not show inflated counts such as 50 selected token members unless they are actual core assignments. |
| Colorless strategy activation | Activate colorless/Eldrazi strategy scoring only from commander/profile relevance or committed selected-deck density, not collection-only clusters. | Prevents non-colorless commanders from selecting Eldrazi/colorless cards just because the collection contains many of them. | Eldrazi package in candidate pool alone does not boost colorless cards for a green lands commander. |
| Deck selection | Greedy role-fill + local swaps or ILP for later version, followed by quality and coherence repair passes. | Simpler MVP; can improve over time. | Final deck passes legality, role validation, mana-base validation, and strategic coherence checks. |
| Validation | Run legality, singleton, card count, curve, role quota, duplicate, and hard deck-quality checks after every repair pass. | Prevents embarrassing bad outputs. | No generated deck can be displayed as successful or exported until validation passes. |

## 12. Quality Gates and Test Plan

| Test Area | Test / Gate | Expected Result | Priority | Owner / Area |
| --- | --- | --- | --- | --- |
| Collection import | Import valid CSV, malformed CSV, duplicate rows, alternate printings. | Valid rows import; invalid rows are reported; quantities are correct. | P0 | Backend/Data |
| Card normalization | Resolve split cards, MDFCs, alternate names, reprints, and special characters. | Cards map to stable canonical identities. | P0 | Data |
| Legality | Generate decks for commanders with narrow color identities and known banned cards. | No illegal card appears in output. | P0 | Recommendation |
| Role quotas | Generate decks for different archetypes: aristocrats, landfall, spellslinger, Voltron. | Role counts are within expected ranges after commander adjustments. | P0 | Recommendation |
| Package quality | Inspect top packages for curated/profiled commander expansion candidates. | Packages are meaningfully labeled or conservatively marked utility/staples. | P0 | Product/Data |
| Strategic coherence | Run negative deck fixtures for known incoherent outputs, including mono-green Nissa-style random Treasure/Clue/Food/artifact-value piles, Greta generic Golgari piles, and Toluz generic Esper piles. | Deck is repaired or fails the coherence gate; warning-only output is insufficient. | P0 | Recommendation/QA |
| Fallback commander plan quality | Generate decks for fallback commanders with identifiable text plans such as Greta and Toluz. | Deck contents materially support the inferred/profiled plan rather than only color identity and broad roles. | P0 | Recommendation/QA |
| Diagnostic truthfulness | Compare displayed warnings, role breakdown, quota status, validation errors, and strategic coherence report for the same deck. | Reports cannot claim high confidence / zero off-plan when unresolved failures exist. | P0 | Recommendation/API/UI |
| Role-slot accounting | Generate decks with multi-tag cards and package-heavy collections. | Quota counts use assigned roles and bounded credits; raw tags do not inflate role totals. | P0 | Recommendation |
| Hard validation failure | Generate decks with snow-covered basics and intentional non-basic duplicates. | Snow-covered basics validate when canonical basic; invalid non-basic duplicates block normal display/export. | P0 | Recommendation/API/UI |
| Live catalog basic audit | Run validation against resolver/database records for all basic lands, not only synthetic test objects. | Stored regular and snow-covered basics agree with canonical `Basic Land` metadata. | P0 | Data/QA |
| Basic-land virtual inventory | Generate and export decks from collections with zero imported basics. | Decks can use basics without missing markers; missing counts/upgrades exclude basics. | P0 | Recommendation/API/UI |
| Quality repair loop | Generate decks that initially have win-condition, quota-credit, overfill, and off-plan failures. | System performs deterministic repair passes before failed-quality status. | P0 | Recommendation/API/UI |
| Quality-failure response | Generate decks that remain unresolved after repair exhaustion. | Response returns failed-quality status with exhausted repair reasons instead of normal recommendation. | P0 | Recommendation/API/UI |
| Package display accounting | Generate package-heavy decks after role-slot assignment. | Package selected counts use assigned/core members and do not contradict role breakdown. | P0 | Recommendation/API/UI |
| Off-plan colorless leakage | Generate colored commander decks with many owned Eldrazi/colorless cards. | Non-staple off-plan colorless/Eldrazi cards are excluded unless commander-relevant. | P0 | Recommendation/QA |
| Root-cause regressions | Test owned-bonus scaling, package-core protection, and colorless-strategy activation directly. | Nissa-style failures cannot recur through scoring branch, repair, or package-detection loopholes. | P0 | Recommendation/QA |
| Performance | Run commander ranking and deck generation on large sample collections. | Latency stays within configured non-functional targets. | P1 | Backend |
| Explainability | User can understand why each core card/package was selected. | Deck viewer shows card reasons, packages, and role contribution. | P0 | UX |
| Regression set | Maintain golden test collections and expected commander/deck qualities. | Changes do not degrade known cases without review. | P1 | QA |

## 13. Additional Subtasks

| Subtask ID | Description | Dependencies | Acceptance Criteria | Related Task |
| --- | --- | --- | --- | --- |
| ST-13 | Define MVP commander support confidence and manually review archetypes, core cards, and likely packages. | Product decision D-2. | Hybrid support model is documented; initial curated/profiled commanders are listed; fallback commanders are allowed but lower-confidence. | T-3, T-4 |
| ST-14 | Create a tag taxonomy document with role definitions, confidence levels, and examples. | T-2. | Developers and reviewers use the same definitions for ramp, draw, removal, payoff, enabler, etc. | T-2 |
| ST-15 | Build deck validation service used by generator and export flow. | T-2, T-4. | Every generated deck receives validation status and actionable errors before export. | T-4, T-5 |
| ST-16 | Add deterministic recommendation logs and score breakdowns for debugging. | T-3, T-4. | A developer can reproduce why a commander/card was selected for a given collection. | T-3, T-4 — implemented internally via `ScoreLog` |
| ST-17 | Prepare golden test collections for initial commanders. | ST-13. | Each sample collection has expected commander recommendations and quality notes. | T-6 — implemented for aristocrats, landfall, and spellslinger fixtures |
| ST-18 | Implement user-facing warnings for missing data, unsupported formats, and low-confidence generated decks. | T-1, T-3, T-4. | Users see clear warnings instead of silent failures or misleading recommendations. | T-5 |

## 14. Suggested Implementation Phases

| Phase | Scope | Deliverables | Exit Criteria |
| --- | --- | --- | --- |
| Phase 1 | Data foundation | Scryfall ingestion, collection import, role tag taxonomy, manual overrides. | Collection imports and cards have usable tags. |
| Phase 2 | Recommendation MVP | Commander ranking, support confidence, basic quotas, deck generation, legality validator. | User can generate legal decks for curated/profiled commanders and fallback legal commanders with clear confidence expectations. |
| Phase 3 | Explainability and UX | Deck viewer, packages, score explanations, upgrade display, card explanations, and plaintext export. | User can understand and export generated decks. |
| Phase 4 | Quality expansion | More commanders, better package labeling, upgrade suggestions, feedback loop. | Quality improves without breaking golden tests. |

## Change Log

| Date | Change |
| --- | --- |
| 2026-05-15 | Enhanced specification with MVP scope, data model, algorithm details, quality gates, additional subtasks, implementation phases, and improved workbook formatting. |
| 2026-05-15 | Aligned MVP scope with backend state at that point: CSV-only import, session-based collection flow, backend/API upgrade and card explanation data, and deck editing future scope. |
| 2026-05-15 | Updated implementation state: frontend MVP flow, plaintext export, golden regression fixtures, and internal deterministic score logs are implemented and tested. |
| 2026-05-15 | Resolved MVP commander scope and power-profile decisions: hybrid commander support confidence and no user-facing power-level selector in MVP. |
| 2026-05-16 | Added strategic coherence gate and negative regression requirement for legal but incoherent generated decks, based on Nissa, Worldsoul Speaker failure case. |
| 2026-05-16 | Added Greta/Toluz regression requirements: strategic coherence must constrain selection, candidate packages must not be active by default, fallback commanders need concrete plan pressure, and negative fixtures must cover multiple archetypes. |
| 2026-05-16 | Added displayed-diagnostics hardening requirements: coherence metrics must fail closed, role counts must use assigned slots, validation errors block successful generation, package activation requires commander relevance, and profiles must use real catalog IDs. |
| 2026-05-16 | Marked first wave-6 implementation present: coherence repair/refresh, inactive candidate packages, Greta/Toluz plan evidence, negative fixtures, and end-to-end coherence gate regressions are covered by backend tests. |
| 2026-05-16 | Implemented role-slot accounting: generated deck cards expose assigned primary roles and bounded secondary credit; role breakdown, quota status, refresh, and coherence plan counts no longer use full raw multi-tag counts. |
| 2026-05-17 | Implemented commander-relevant package activation: package diagnostics expose activation status and active packages require selected density, commander-plan relevance, non-loose status, and viable composition. |
| 2026-05-17 | Added post-wave-7 live-output requirements: audit live basic-land metadata, add quality-failure generation status/retry, align package display counts with assigned/core members, and re-block off-plan colorless/Eldrazi cards for all colored commanders. |
| 2026-05-17 | Implemented quality-failure status, core-vs-raw package display counts, and broad colored-commander colorless/Eldrazi leakage blocking. |
| 2026-05-17 | Planned multi-pass quality repair and basic-land virtual inventory: basics are assumed available at 99 copies each and failed-quality should occur only after repair exhaustion. |
| 2026-05-18 | Implemented eleventh-wave recommendation fixes: loose-value label false-positive removal, commander score desaturation, quality-aware initial selection, filler/repair role-overfill controls, and quota-capped fallback role assignment. |
