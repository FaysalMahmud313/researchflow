/**
 * Lightweight structural checks for LaTeX source, run in the browser as you type.
 * ResearchFlow does not compile documents, so this catches the most common structural
 * mistakes early: unbalanced braces and mismatched \begin{…}/\end{…} environments.
 */
export interface LintIssue {
  from: number;
  to: number;
  message: string;
}

/** Replace comments and escaped characters with spaces so offsets stay identical. */
function maskSource(text: string): string {
  const out = text.split('');
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '\\') {
      if (i + 1 < text.length && !/[a-zA-Z]/.test(text[i + 1])) {
        out[i] = ' ';
        out[i + 1] = ' ';
      }
      i++;
      continue;
    }
    if (ch === '%') {
      while (i < text.length && text[i] !== '\n') out[i++] = ' ';
    }
  }
  return out.join('');
}

const VERBATIM = /\\begin\{(verbatim|lstlisting|minted|comment)\*?\}[\s\S]*?\\end\{\1\*?\}/g;

export function lintLatex(text: string): LintIssue[] {
  let masked = maskSource(text);
  masked = masked.replace(VERBATIM, (m) => m.replace(/[^\n]/g, ' '));
  const issues: LintIssue[] = [];

  const envStack: { name: string; from: number; to: number }[] = [];
  const envRe = /\\(begin|end)\s*\{([^}]*)\}/g;
  for (let m = envRe.exec(masked); m; m = envRe.exec(masked)) {
    const [whole, kind, name] = m;
    if (kind === 'begin') {
      envStack.push({ name, from: m.index, to: m.index + whole.length });
    } else {
      const open = envStack.pop();
      if (!open) {
        issues.push({ from: m.index, to: m.index + whole.length, message: `\\end{${name}} has no matching \\begin{${name}}.` });
      } else if (open.name !== name) {
        issues.push({ from: m.index, to: m.index + whole.length, message: `\\end{${name}} closes \\begin{${open.name}}.` });
      }
    }
  }
  for (const open of envStack) {
    issues.push({ from: open.from, to: open.to, message: `\\begin{${open.name}} is never closed.` });
  }

  const braces: number[] = [];
  for (let i = 0; i < masked.length; i++) {
    if (masked[i] === '{') braces.push(i);
    else if (masked[i] === '}') {
      if (!braces.length) issues.push({ from: i, to: i + 1, message: 'Closing brace without a matching opening brace.' });
      else braces.pop();
    }
  }
  for (const b of braces.slice(-5)) issues.push({ from: b, to: b + 1, message: 'Opening brace is never closed.' });
  return issues.slice(0, 50);
}
