import type { Attachment } from './types'

/**
 * Guide / Review start a slow request (thread + first AI exchange) from the
 * Calendar, then switch to Chat straight away so the athlete sees their message and
 * "Thinking…" instead of a frozen button. The request lives here, outside React,
 * so StrictMode double-mounts and route changes never fire it twice.
 */
export type PendingChat = {
  id: string
  text: string
  attachment: Attachment | null
  promise: Promise<{ thread_id: number }>
}

const store = new Map<string, PendingChat>()

export function startPendingChat(
  text: string,
  attachment: Attachment | null,
  run: () => Promise<{ thread_id: number }>,
): string {
  const id = Math.random().toString(36).slice(2)
  store.set(id, { id, text, attachment, promise: run() })
  return id
}

export const getPendingChat = (id: string | null): PendingChat | undefined => (id ? store.get(id) : undefined)

export const clearPendingChat = (id: string) => store.delete(id)
