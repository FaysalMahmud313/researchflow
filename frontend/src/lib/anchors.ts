import { codePointToUtf16 } from './text';
import type { CommentAnchor } from '../types';

/**
 * Find the passage a comment or suggestion refers to in the current text.
 *
 * Anchors store code-point offsets plus the quoted text and its surroundings. After later
 * edits the offsets may be stale, so the quote is searched for: first with its context,
 * then on its own, and only a unique match is accepted. Returns UTF-16 editor offsets,
 * or null when the passage can no longer be found (the caller falls back to the line).
 */
export function locateAnchor(text: string, anchor: CommentAnchor, quoted: string): { from: number; to: number } | null {
  if (!quoted) return null;
  const from = codePointToUtf16(text, anchor.from);
  const to = codePointToUtf16(text, anchor.to);
  if (text.slice(from, to) === quoted) return { from, to };
  const unique = (needle: string): number | null => {
    const first = text.indexOf(needle);
    if (first < 0 || text.indexOf(needle, first + 1) >= 0) return null;
    return first;
  };
  const before = anchor.context_before ?? '';
  const withContext = unique(before + quoted + (anchor.context_after ?? ''));
  if (withContext !== null) return { from: withContext + before.length, to: withContext + before.length + quoted.length };
  const alone = unique(quoted);
  if (alone !== null) return { from: alone, to: alone + quoted.length };
  return null;
}
