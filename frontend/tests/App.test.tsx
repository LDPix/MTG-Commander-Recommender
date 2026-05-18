import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import App from "../src/App";
import type {
  GeneratedDeckResponse,
  RecommendationResponse,
  SavedDeckDetail,
  SavedDeckListResponse
} from "../src/types/api";

const api = vi.hoisted(() => ({
  importCollection: vi.fn(),
  fetchRecommendations: vi.fn(),
  generateDeck: vi.fn(),
  exportPlaintextDeck: vi.fn(),
  fetchSavedDecks: vi.fn(),
  fetchSavedDeckDetail: vi.fn()
}));

vi.mock("../src/api/client", () => api);

const recommendations: RecommendationResponse = {
  session_id: "session-test",
  total: 1,
  recommendations: [
    {
      oracle_id: "cmd-1",
      name: "Meren of Clan Nel Toth",
      color_identity: ["B", "G"],
      fit_score: 0.87,
      archetype: "graveyard",
      owned_count: 42,
      owned_percentage: 0.72,
      explanation: {
        summary: "Strong graveyard fit for the collection.",
        owned_highlights: ["Sakura-Tribe Elder"],
        archetype_label: "Graveyard Value",
        missing_core_notes: ["Skullclamp"]
      },
      roles_covered: { RAMP: 8, DRAW: 5 },
      support_confidence: "curated"
    }
  ]
};

const deck: GeneratedDeckResponse = {
  deck_id: "deck-1",
  session_id: "session-test",
  generation_status: "success",
  commander: {
    oracle_id: "cmd-1",
    name: "Meren of Clan Nel Toth",
    is_owned: true,
    quantity: 1,
    roles: ["COMMANDER"],
    assigned_role: null,
    secondary_role_credit: {},
    package_ids: ["pkg-graveyard"],
    selection_reason: "Commander supports recursion.",
    synergy_score: 1
  },
  main_deck: [
    {
      oracle_id: "sol-ring",
      name: "Sol Ring",
      is_owned: true,
      quantity: 1,
      roles: ["RAMP"],
      assigned_role: "RAMP",
      secondary_role_credit: {},
      package_ids: [],
      selection_reason: "Efficient ramp.",
      synergy_score: 0.8
    },
    {
      oracle_id: "skullclamp",
      name: "Skullclamp",
      is_owned: false,
      quantity: 1,
      roles: ["DRAW"],
      assigned_role: "DRAW",
      secondary_role_credit: {},
      package_ids: [],
      selection_reason: "Turns small creatures into cards.",
      synergy_score: 0.76
    }
  ],
  role_breakdown: { RAMP: 1, DRAW: 1 },
  quota_status: [
    {
      role: "RAMP",
      target_min: 10,
      target_max: 12,
      actual_count: 1,
      is_satisfied: false,
      warning: "RAMP underfilled.",
      credit_sum: 1,
      credit_satisfied: false,
      credit_warning: null
    },
    {
      role: "CARD_DRAW",
      target_min: 6,
      target_max: 10,
      actual_count: 8,
      is_satisfied: true,
      warning: null,
      credit_sum: 3.5,
      credit_satisfied: false,
      credit_warning: "CARD_DRAW credit under minimum."
    }
  ],
  package_breakdown: [
    {
      package_id: "pkg-graveyard",
      label: "Graveyard recursion",
      confidence: 0.91,
      card_oracle_ids: ["cmd-1"],
      top_roles: ["RECURSION"],
      activation_status: "active",
      selected_count: 1,
      raw_selected_count: 1
    }
  ],
  warnings: ["RAMP underfilled."],
  owned_count: 2,
  owned_percentage: 0.66,
  is_valid: true,
  validation_errors: [],
  strategic_coherence: {
    primary_plan: "graveyard",
    confidence: 0.82,
    active_package_ids: ["pkg-graveyard"],
    on_plan_count: 12,
    off_plan_count: 3,
    warning_card_oracle_ids: ["skullclamp", "sol-ring"],
    warnings: []
  },
  upgrade_suggestions: [
    {
      oracle_id: "viscera-seer",
      name: "Viscera Seer",
      priority: "core",
      improves_roles: ["SACRIFICE_OUTLET"],
      improves_packages: ["pkg-graveyard"],
      reason: "Adds a free sacrifice outlet.",
      impact_score: 0.9,
      replaces_or_supplements: []
    },
    {
      oracle_id: "eternal-witness",
      name: "Eternal Witness",
      priority: "recommended",
      improves_roles: ["RECURSION"],
      improves_packages: ["pkg-graveyard"],
      reason: "Adds recursion redundancy.",
      impact_score: 0.78,
      replaces_or_supplements: []
    },
    {
      oracle_id: "satyr-wayfinder",
      name: "Satyr Wayfinder",
      priority: "optional",
      improves_roles: ["SETUP"],
      improves_packages: ["pkg-graveyard"],
      reason: "Adds light graveyard setup.",
      impact_score: 0.5,
      replaces_or_supplements: []
    }
  ],
  card_explanations: {
    skullclamp: {
      oracle_id: "skullclamp",
      name: "Skullclamp",
      summary: "Skullclamp converts expendable creatures into cards.",
      evidence: ["Roles: DRAW.", "No package membership."],
      roles: ["DRAW"],
      package_ids: [],
      synergy_score: 0.76,
      is_owned: false
    }
  }
};

// Saved deck fixtures use a DIFFERENT commander than `deck` above so
// tests can detect source confusion (TC-FR-023-01).
const savedDecksList: SavedDeckListResponse = {
  decks: [
    {
      deck_id: "saved-deck-1",
      session_id: "session-test",
      commander_oracle_id: "atraxa-id",
      commander_name: "Atraxa, Praetors' Voice",
      created_at: "2024-01-01T00:00:00"
    }
  ]
};

const savedDeckDetail: SavedDeckDetail = {
  deck_id: "saved-deck-1",
  session_id: "session-test",
  commander_oracle_id: "atraxa-id",
  commander_name: "Atraxa, Praetors' Voice",
  created_at: "2024-01-01T00:00:00",
  deck: {
    deck_id: "saved-deck-1",
    session_id: "session-test",
    generation_status: "success",
    commander: {
      oracle_id: "atraxa-id",
      name: "Atraxa, Praetors' Voice",
      is_owned: true,
      quantity: 1,
      roles: ["COMMANDER"],
      assigned_role: null,
      secondary_role_credit: {},
      package_ids: [],
      selection_reason: "Saved commander.",
      synergy_score: 1
    },
    main_deck: [
      {
        oracle_id: "cultivate-saved",
        name: "Cultivate",
        is_owned: true,
        quantity: 1,
        roles: ["RAMP"],
        assigned_role: "RAMP",
        secondary_role_credit: {},
        package_ids: [],
        selection_reason: "Saved ramp.",
        synergy_score: 0.7
      }
    ],
    role_breakdown: { RAMP: 1 },
    quota_status: [],
    package_breakdown: [],
    warnings: [],
    owned_count: 2,
    owned_percentage: 1.0,
    is_valid: true,
    validation_errors: [],
    strategic_coherence: null,
    upgrade_suggestions: [],
    card_explanations: {}
  }
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "test-session-id" });
  api.importCollection.mockResolvedValue({
    collection_id: "collection-1",
    session_id: "session-test",
    imported_count: 3,
    unknown_cards: ["Mystery Card"],
    warnings: [{ row: 4, message: "Missing quantity" }],
    change_summary: {
      added_count: 1,
      removed_count: 1,
      quantity_changed_count: 1,
      unchanged_count: 1,
      added_cards: ["Cultivate"],
      removed_cards: ["Swords to Plowshares"],
      quantity_changed_cards: ["Sol Ring"]
    },
    success: true,
    error: null
  });
  api.fetchRecommendations.mockResolvedValue(recommendations);
  api.generateDeck.mockResolvedValue(deck);
  api.exportPlaintextDeck.mockResolvedValue({
    format: "plaintext",
    text: "Commander\n1 Meren of Clan Nel Toth\n\nMain Deck\n1 Skullclamp [missing]",
    warnings: []
  });
  // Default: empty saved deck list so existing tests are not affected
  api.fetchSavedDecks.mockResolvedValue({ decks: [] });
  api.fetchSavedDeckDetail.mockResolvedValue(savedDeckDetail);
});

describe("frontend MVP flow", () => {
  test("test_import_page_allows_file_selection", async () => {
    render(<App />);
    const input = screen.getByLabelText("Collection CSV");
    const file = new File(["Count,Name\n1,Sol Ring"], "collection.csv", {
      type: "text/csv"
    });

    await userEvent.upload(input, file);

    expect(input).toHaveProperty("files");
    expect((input as HTMLInputElement).files?.[0]).toBe(file);
  });

  test("test_import_page_shows_loading_state", async () => {
    api.importCollection.mockReturnValue(new Promise(() => undefined));
    render(<App />);

    await uploadAndImport();

    expect(screen.getByText("Importing...")).toBeInTheDocument();
    expect(screen.getByText("Importing collection...")).toBeInTheDocument();
  });

  test("test_import_page_shows_success_summary", async () => {
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("Import summary")).toBeInTheDocument();
    expect(screen.getByText("3 cards imported.")).toBeInTheDocument();
    expect(screen.getByText("Mystery Card")).toBeInTheDocument();
    expect(screen.getByText(/Missing quantity/)).toBeInTheDocument();
  });

  test("test_import_page_shows_reimport_change_summary", async () => {
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("Change summary")).toBeInTheDocument();
    expect(screen.getByText("Added 1")).toBeInTheDocument();
    expect(screen.getByText("Removed 1")).toBeInTheDocument();
    expect(screen.getByText("Quantity changed 1")).toBeInTheDocument();
    expect(screen.getByText("Unchanged 1")).toBeInTheDocument();
    expect(screen.getByText("Cultivate")).toBeInTheDocument();
    expect(screen.getByText("Swords to Plowshares")).toBeInTheDocument();
    expect(screen.getByText("Sol Ring")).toBeInTheDocument();
  });

  test("test_recommendations_page_renders_ranked_list", async () => {
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Meren of Clan Nel Toth")).toBeInTheDocument();
  });

  test("test_recommendations_page_shows_fit_score", async () => {
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("Fit 87%")).toBeInTheDocument();
  });

  test("test_recommendations_page_shows_support_confidence", async () => {
    render(<App />);

    await uploadAndImport();

    expect(
      await screen.findByLabelText("Curated recommendation")
    ).toBeInTheDocument();
    expect(screen.getByText("Curated")).toBeInTheDocument();
  });

  test("test_deck_viewer_shows_commander", async () => {
    render(<App />);

    await importAndGenerate();

    const commanderSection = await screen.findByText("Commander");
    expect(commanderSection).toBeInTheDocument();
    expect(screen.getAllByText(/Meren of Clan Nel Toth/).length).toBeGreaterThan(0);
  });

  test("test_deck_viewer_marks_missing_cards", async () => {
    render(<App />);

    await importAndGenerate();

    const skullclampRow = screen.getByRole("button", { name: /Skullclamp missing/ });
    expect(within(skullclampRow).getByText("missing")).toBeInTheDocument();
  });

  test("test_deck_viewer_shows_role_breakdown", async () => {
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("Role breakdown")).toBeInTheDocument();
    expect(screen.getByText("RAMP")).toBeInTheDocument();
    expect(screen.getByText("RAMP: 1/10-12 - RAMP underfilled.")).toBeInTheDocument();
  });

  test("test_quota_panel_renders_credit_shortfall_text", async () => {
    render(<App />);

    await importAndGenerate();

    expect(
      await screen.findByText(
        "CARD_DRAW: 8/6-10, credit 3.5/6 - CARD_DRAW credit under minimum."
      )
    ).toBeInTheDocument();
  });

  test("test_quota_panel_omits_credit_warning_when_credit_is_satisfied", async () => {
    api.generateDeck.mockResolvedValueOnce({
      ...deck,
      quota_status: [
        {
          role: "RAMP",
          target_min: 10,
          target_max: 12,
          actual_count: 11,
          is_satisfied: true,
          warning: null,
          credit_sum: 10.5,
          credit_satisfied: true,
          credit_warning: null
        }
      ]
    });
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("RAMP: 11/10-12")).toBeInTheDocument();
    expect(screen.queryByText(/credit 10.5/)).not.toBeInTheDocument();
  });

  test("test_deck_viewer_shows_primary_plan_when_returned", async () => {
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("Strategic coherence")).toBeInTheDocument();
    expect(screen.getByText("Graveyard")).toBeInTheDocument();
    expect(screen.getByText("Confidence 82%")).toBeInTheDocument();
    expect(screen.getByText("Active packages: pkg-graveyard")).toBeInTheDocument();
  });

  test("test_deck_viewer_shows_warning_candidate_count", async () => {
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("Warning candidates 2")).toBeInTheDocument();
  });

  test("test_deck_viewer_shows_low_coherence_warning", async () => {
    api.generateDeck.mockResolvedValueOnce(lowCoherenceDeck());
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("Deck warnings")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Strategic coherence is low: no clear primary commander plan was identified."
      )
    ).toBeInTheDocument();
  });

  test("test_deck_viewer_groups_upgrade_suggestions", async () => {
    render(<App />);

    await importAndGenerate();

    expect(await screen.findByText("core")).toBeInTheDocument();
    expect(screen.getByText("Viscera Seer")).toBeInTheDocument();
    expect(screen.getByText("recommended")).toBeInTheDocument();
    expect(screen.getByText("Eternal Witness")).toBeInTheDocument();
    expect(screen.getByText("optional")).toBeInTheDocument();
    expect(screen.getByText("Satyr Wayfinder")).toBeInTheDocument();
  });

  test("test_user_can_open_card_explanation", async () => {
    render(<App />);

    await importAndGenerate();
    await userEvent.click(screen.getByRole("button", { name: /Skullclamp missing/ }));

    expect(
      await screen.findByText("Skullclamp converts expendable creatures into cards.")
    ).toBeInTheDocument();
    expect(screen.getByText("Missing card")).toBeInTheDocument();
    expect(screen.getByText("No package membership")).toBeInTheDocument();
  });

  test("test_deck_viewer_shows_export_button", async () => {
    render(<App />);

    await importAndGenerate();
    await userEvent.click(await screen.findByText("Export plaintext"));

    const exportBox = await screen.findByLabelText("Plaintext deck export");
    expect((exportBox as HTMLTextAreaElement).value).toContain("Commander");
  });

  test("test_frontend_disables_export_for_invalid_deck", async () => {
    api.generateDeck.mockResolvedValueOnce(invalidDeck());
    render(<App />);

    await importAndGenerate();

    expect(
      await screen.findByText(
        "Generation failed validation. Export is disabled until the deck passes Commander legality checks."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Deck has 101 cards.")).toBeInTheDocument();
    expect(screen.getByText("Export plaintext")).toBeDisabled();
    expect(api.exportPlaintextDeck).not.toHaveBeenCalled();
  });

  test("test_frontend_distinguishes_failed_quality_from_failed_validation", async () => {
    api.generateDeck.mockResolvedValueOnce(failedQualityDeck());
    render(<App />);

    await importAndGenerate();

    expect(
      await screen.findByText(
        "Deck generation failed quality checks. Export is disabled until quota, coherence, and win-condition gaps are repaired."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Export plaintext")).toBeDisabled();
  });

  test("test_frontend_displays_package_activation_status_and_core_count", async () => {
    api.generateDeck.mockResolvedValueOnce({
      ...deck,
      package_breakdown: [
        {
          package_id: "pkg-token",
          label: "Token package",
          confidence: 0.7,
          card_oracle_ids: ["a", "b", "c"],
          top_roles: ["TOKEN_MAKER"],
          activation_status: "inactive_bad_composition",
          selected_count: 1,
          raw_selected_count: 3
        }
      ]
    });
    render(<App />);

    await importAndGenerate();

    expect(
      await screen.findByText("Inactive Bad Composition - 1 core selected (3 raw)")
    ).toBeInTheDocument();
  });

  test("test_export_includes_coherence_warning_when_present", async () => {
    api.generateDeck.mockResolvedValueOnce(lowCoherenceDeck());
    api.exportPlaintextDeck.mockResolvedValueOnce({
      format: "plaintext",
      text:
        "Commander\n1 Meren of Clan Nel Toth\n\nMain Deck\n1 Skullclamp [missing]\n\nWarnings\n- Strategic coherence is low: no clear primary commander plan was identified.",
      warnings: [
        "Strategic coherence is low: no clear primary commander plan was identified."
      ]
    });
    render(<App />);

    await importAndGenerate();
    await userEvent.click(await screen.findByText("Export plaintext"));

    const exportBox = await screen.findByLabelText("Plaintext deck export");
    expect((exportBox as HTMLTextAreaElement).value).toContain(
      "Strategic coherence is low"
    );
  });
});

describe("saved deck flow", () => {
  // TC-FR-019-01 / AT-FR-019-FE-01
  test("test_saved_decks_list_shown_after_import", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("Saved decks")).toBeInTheDocument();
    expect(await screen.findByText("Atraxa, Praetors' Voice")).toBeInTheDocument();
  });

  // TC-FR-019-02 / AT-FR-019-FE-02
  test("test_saved_decks_empty_state_shown_when_no_saved_decks", async () => {
    api.fetchSavedDecks.mockResolvedValue({ decks: [] });
    render(<App />);

    await uploadAndImport();

    expect(await screen.findByText("Saved decks")).toBeInTheDocument();
    expect(await screen.findByText("No saved decks yet.")).toBeInTheDocument();
  });

  // TC-FR-020-01 / AT-FR-020-FE-01
  test("test_open_saved_deck_does_not_call_generate", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    render(<App />);

    await uploadAndImport();
    const openButton = await screen.findByRole("button", { name: "Open" });
    await userEvent.click(openButton);

    await waitFor(() => expect(api.fetchSavedDeckDetail).toHaveBeenCalled());
    expect(api.generateDeck).not.toHaveBeenCalled();
  });

  // TC-FR-021-01 / AT-FR-021-FE-01
  test("test_saved_deck_displays_saved_commander_and_card_list", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    render(<App />);

    await uploadAndImport();
    const openButton = await screen.findByRole("button", { name: "Open" });
    await userEvent.click(openButton);

    // Saved commander appears in deck viewer (Atraxa, not Meren)
    expect(
      await screen.findByRole("button", { name: /Atraxa, Praetors' Voice owned/ })
    ).toBeInTheDocument();
    // Saved main deck card appears
    expect(screen.getByRole("button", { name: /Cultivate owned/ })).toBeInTheDocument();
  });

  // TC-FR-022-01 / AT-FR-022-FE-01
  test("test_new_deck_shows_new_label_saved_deck_shows_saved_label", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    render(<App />);

    // Generate a new deck → "New deck" label
    await importAndGenerate();
    expect(await screen.findByText("New deck")).toBeInTheDocument();

    // Open a saved deck → "Saved deck" label
    const openButton = screen.getByRole("button", { name: "Open" });
    await userEvent.click(openButton);
    expect(await screen.findByText("Saved deck")).toBeInTheDocument();
    // "New deck" label must no longer be present once saved deck is opened
    expect(screen.queryByText("New deck")).not.toBeInTheDocument();
  });

  // TC-FR-018-02 / AT-FR-018-FE-02
  test("test_export_saved_deck_uses_existing_plaintext_format", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    api.exportPlaintextDeck.mockResolvedValue({
      format: "plaintext",
      text: "Commander\n1 Atraxa, Praetors' Voice\n\nMain Deck\n1 Cultivate",
      warnings: []
    });
    render(<App />);

    await uploadAndImport();
    const openButton = await screen.findByRole("button", { name: "Open" });
    await userEvent.click(openButton);

    await userEvent.click(await screen.findByText("Export plaintext"));

    const exportBox = await screen.findByLabelText("Plaintext deck export");
    expect((exportBox as HTMLTextAreaElement).value).toContain("Atraxa");
  });

  // TC-FR-023-01 / AT-FR-023-FE-01
  test("test_export_saved_deck_uses_saved_content_not_active_generated", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    render(<App />);

    // Generate a Meren deck (the active generated deck)
    await importAndGenerate();
    await waitFor(() => expect(screen.getByText("New deck")).toBeInTheDocument());

    // Open the Atraxa saved deck
    const openButton = screen.getByRole("button", { name: "Open" });
    await userEvent.click(openButton);
    await waitFor(() => expect(screen.getByText("Saved deck")).toBeInTheDocument());

    // Export — must use saved Atraxa deck, not active Meren deck
    await userEvent.click(screen.getByText("Export plaintext"));
    await waitFor(() => expect(api.exportPlaintextDeck).toHaveBeenCalled());

    const lastCallArg = api.exportPlaintextDeck.mock.lastCall?.[0] as GeneratedDeckResponse;
    expect(lastCallArg.commander.name).toBe("Atraxa, Praetors' Voice");
    expect(lastCallArg.commander.oracle_id).toBe("atraxa-id");
  });

  // TC-FR-020-03 / AT-FR-020-FE-03
  test("test_open_unknown_saved_deck_shows_error", async () => {
    api.fetchSavedDecks.mockResolvedValue(savedDecksList);
    api.fetchSavedDeckDetail.mockRejectedValue(new Error("Saved deck not found."));
    render(<App />);

    await uploadAndImport();
    const openButton = await screen.findByRole("button", { name: "Open" });
    await userEvent.click(openButton);

    expect(await screen.findByText("Saved deck not found.")).toBeInTheDocument();
    // No deck regeneration occurred
    expect(api.generateDeck).not.toHaveBeenCalled();
  });
});

async function uploadAndImport() {
  const input = screen.getByLabelText("Collection CSV");
  const file = new File(["Count,Name\n1,Sol Ring"], "collection.csv", {
    type: "text/csv"
  });
  await userEvent.upload(input, file);
  await userEvent.click(screen.getByText("Import collection"));
}

async function importAndGenerate() {
  await uploadAndImport();
  await userEvent.click(await screen.findByText("Generate deck"));
  await waitFor(() => expect(api.generateDeck).toHaveBeenCalled());
}

function lowCoherenceDeck(): GeneratedDeckResponse {
  const warning =
    "Strategic coherence is low: no clear primary commander plan was identified.";
  return {
    ...deck,
    warnings: [warning],
    strategic_coherence: {
      primary_plan: null,
      confidence: 0.18,
      active_package_ids: [],
      on_plan_count: 1,
      off_plan_count: 14,
      warning_card_oracle_ids: ["skullclamp", "sol-ring", "viscera-seer"],
      warnings: [warning]
    }
  };
}

function invalidDeck(): GeneratedDeckResponse {
  return {
    ...deck,
    generation_status: "failed_validation",
    is_valid: false,
    validation_errors: ["Deck has 101 cards."],
    warnings: ["Generation failed validation."]
  };
}

function failedQualityDeck(): GeneratedDeckResponse {
  return {
    ...deck,
    generation_status: "failed_quality",
    warnings: ["Deck quality failure: WIN_CONDITION underfilled."]
  };
}
