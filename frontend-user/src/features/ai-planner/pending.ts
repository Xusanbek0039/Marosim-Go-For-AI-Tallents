/**
 * The chat's "pending" slot. The server keeps the user message even when the AI fails (a retry
 * with the same `client_request_id` reuses it), so once history has that message the slot must
 * not draw it a second time — it only shows the error / retry row or the typing indicator.
 */
export function pendingAlreadySaved(history: { role: string; client_request_id: string | null }[], key: string): boolean {
  return history.some((m) => m.role === "user" && m.client_request_id === key);
}
