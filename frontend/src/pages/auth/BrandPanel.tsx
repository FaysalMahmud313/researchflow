import { BookMarked, FileText, ShieldCheck } from 'lucide-react';
import { ResearchSignalIcon } from '../../components/ui';

// A loose citation network: papers (nodes) linked by references (edges).
const NODES: [number, number, number][] = [
  [70, 120, 4], [190, 70, 3], [300, 160, 5], [430, 90, 3], [540, 190, 4], [120, 260, 3], [250, 300, 4],
  [380, 270, 3], [500, 340, 5], [80, 420, 4], [210, 470, 3], [340, 430, 4], [470, 500, 3], [560, 460, 3],
  [140, 600, 4], [290, 620, 3], [420, 650, 4], [540, 610, 3], [60, 720, 3], [230, 760, 4], [380, 780, 3],
];
const EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [2, 6], [6, 7], [7, 8], [4, 8], [5, 9], [9, 10], [6, 10],
  [10, 11], [7, 11], [11, 12], [8, 12], [12, 13], [10, 14], [14, 15], [11, 15], [15, 16], [12, 16], [16, 17],
  [14, 18], [18, 19], [15, 19], [19, 20], [16, 20], [2, 7],
];
const PULSING = new Set([2, 8, 11, 16]);

function NetworkArt() {
  return (
    <svg viewBox="0 0 600 820" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full" aria-hidden="true">
      <defs>
        <linearGradient id="rf-edge" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a5b4fc" stopOpacity="0.45" />
          <stop offset="1" stopColor="#c4b5fd" stopOpacity="0.12" />
        </linearGradient>
      </defs>
      {EDGES.map(([a, b]) => {
        const [x1, y1] = NODES[a];
        const [x2, y2] = NODES[b];
        const mx = (x1 + x2) / 2 + (y2 - y1) * 0.12;
        const my = (y1 + y2) / 2 - (x2 - x1) * 0.12;
        return <path key={`${a}-${b}`} d={`M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`} fill="none" stroke="url(#rf-edge)" strokeWidth="1" />;
      })}
      {NODES.map(([x, y, r], i) => (
        <g key={i}>
          {PULSING.has(i) && <circle cx={x} cy={y} r={r * 3} className="rf-node-pulse" fill="#a78bfa" style={{ animationDelay: `${i * 0.35}s` }} />}
          <circle cx={x} cy={y} r={r} fill="#e0e7ff" fillOpacity={PULSING.has(i) ? 0.95 : 0.55} />
        </g>
      ))}
    </svg>
  );
}

const FEATURES = [
  { icon: FileText, title: 'LaTeX papers with full history', text: 'Write, compare versions and review with co-authors.' },
  { icon: BookMarked, title: 'References, data and code together', text: 'BibTeX, datasets and results beside the paper.' },
  { icon: ShieldCheck, title: 'Private by default', text: 'Every project is visible only to the people you invite.' },
];

/** Branded left panel of the sign-in screens (wide screens only). */
export function BrandPanel() {
  return (
    <aside className="rf-brand relative m-3 hidden h-[calc(100vh-1.5rem)] w-[44%] max-w-[620px] shrink-0 self-start overflow-hidden rounded-[28px] text-white lg:sticky lg:top-3 lg:flex lg:flex-col">
      <NetworkArt />
      <div className="relative z-10 flex h-full flex-col p-10 xl:p-12">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20 backdrop-blur">
            <ResearchSignalIcon className="h-5 w-5" />
          </span>
          <span className="text-[17px] font-semibold tracking-tight">ResearchFlow</span>
        </div>

        <div className="mt-auto max-w-md">
          <h2 className="text-[34px] font-semibold leading-[1.15] tracking-tight xl:text-[38px]">
            Your research,
            <br />
            <span className="bg-gradient-to-r from-indigo-200 via-violet-200 to-fuchsia-200 bg-clip-text text-transparent">in one flow.</span>
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-indigo-100/80">
            Papers, references, datasets and reviews in one private workspace for your whole team.
          </p>

          {/* A glimpse of the editor: a manuscript with a citation and its co-authors. */}
          <div className="rf-float mt-8 rounded-2xl border border-white/10 bg-white/[0.07] p-4 shadow-2xl shadow-indigo-950/40 backdrop-blur-md">
            <div className="flex items-center gap-2 text-[12px] text-indigo-100/80">
              <FileText size={14} aria-hidden="true" />
              <span className="font-mono">sections/results.tex</span>
              <span className="ml-auto rounded-full bg-emerald-400/15 px-2 py-0.5 text-[11px] font-medium text-emerald-200">Saved</span>
            </div>
            <div className="mt-3 space-y-1.5 font-mono text-[12.5px] leading-relaxed">
              <p><span className="text-violet-300">\section</span><span className="text-indigo-100/60">{'{'}</span>Results<span className="text-indigo-100/60">{'}'}</span></p>
              <p className="text-indigo-50/90">
                Diffusion priors recover fine-scale structure{' '}
                <span className="rounded bg-indigo-400/20 px-1 text-indigo-200">\cite{'{'}ho2020ddpm{'}'}</span>.
              </p>
            </div>
            <div className="mt-4 flex items-center gap-2 border-t border-white/10 pt-3 text-[12px] text-indigo-100/70">
              <span className="flex -space-x-1.5" aria-hidden="true">
                {[['AO', 'from-indigo-400 to-violet-500'], ['BE', 'from-sky-400 to-cyan-500'], ['MK', 'from-fuchsia-400 to-rose-500']].map(([t, g]) => (
                  <span key={t} className={`flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br ${g} text-[9px] font-semibold ring-2 ring-[#25205a]`}>{t}</span>
                ))}
              </span>
              3 co-authors · 1 open suggestion
            </div>
          </div>

          <ul className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon size={16} aria-hidden="true" />
                </span>
                <span>
                  <span className="block text-[14px] font-medium">{title}</span>
                  <span className="block text-[13px] text-indigo-100/70">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </aside>
  );
}
