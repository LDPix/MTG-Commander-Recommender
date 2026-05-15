import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import App from "../src/App";
import type { GeneratedDeckResponse, RecommendationResponse } from "../src/types/api";

const api = vi.hoisted(() => ({
  importCollection: vi.fn(),
  fetchRecommendations: vi.fn(),
  generateDeck: vi.fn(),
  exportPlaintextDeck: vi.fn()
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
      roles_covered: { RAMP: 8, DRAW: 5 }
    }
  ]
};

const deck: GeneratedDeckResponse = {
  deck_id: "deck-1",
  session_id: "session-test",
  commander: {
    oracle_id: "cmd-1",
    name: "Meren of Clan Nel Toth",
    is_owned: true,
    quantity: 1,
    roles: ["COMMANDER"],
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
      warning: "RAMP underfilled."
    }
  ],
  package_breakdown: [
    {
      package_id: "pkg-graveyard",
      label: "Graveyard recursion",
      confidence: 0.91,
      card_oracle_ids: ["cmd-1"],
      top_roles: ["RECURSION"]
    }
  ],
  warnings: ["RAMP underfilled."],
  owned_count: 2,
  owned_percentage: 0.66,
  is_valid: false,
  validation_errors: [],
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

beforeEach(() => {
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
