import type {
  CollectionImportResponse,
  DeckExportResponse,
  GeneratedDeckResponse,
  RecommendationResponse
} from "../types/api";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string; error?: string };
      message = body.detail ?? body.error ?? message;
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function importCollection(
  file: File,
  sessionId: string
): Promise<CollectionImportResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/api/v1/collections/import`, {
    method: "POST",
    headers: { "X-Session-Id": sessionId },
    body: formData
  });

  return parseJson<CollectionImportResponse>(response);
}

export async function fetchRecommendations(
  sessionId: string
): Promise<RecommendationResponse> {
  const response = await fetch(`${API_BASE}/api/v1/recommendations/${sessionId}`);
  return parseJson<RecommendationResponse>(response);
}

export async function generateDeck(
  sessionId: string,
  commanderOracleId: string
): Promise<GeneratedDeckResponse> {
  const response = await fetch(`${API_BASE}/api/v1/decks/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      commander_oracle_id: commanderOracleId
    })
  });

  return parseJson<GeneratedDeckResponse>(response);
}

export async function exportPlaintextDeck(
  deck: GeneratedDeckResponse
): Promise<DeckExportResponse> {
  const response = await fetch(`${API_BASE}/api/v1/decks/export/plaintext`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deck })
  });

  return parseJson<DeckExportResponse>(response);
}
