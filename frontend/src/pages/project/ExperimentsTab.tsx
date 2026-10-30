import { useMemo, useState } from 'react';
import { AlertTriangle, FlaskConical, Plus } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../services/apiClient';
import { useApp, useLoad } from '../../lib/app';
import { timeAgo } from '../../lib/text';
import type { Project } from '../../types';
import { EmptyState, Modal, SkeletonRows, Spinner, useErrorToast } from '../../components/ui';

interface Experiment {
  id: string;
  name: string;
  objective: string;
  dataset_ref: string;
  dataset_version: string;
  method_or_model: string;
  parameters: Record<string, unknown>;
  repo_url: string;
  commit_sha: string;
  environment_details: string;
  results_summary: string;
  status: string;
  metrics: Record<string, number>;
  created_at: string;
}

const SERIES = ['rgb(var(--accent))', '#0d9488', '#d97706', '#db2777', '#2563eb', '#65a30d'];

export function ExperimentsTab({ project }: { project: Project }) {
  const { data, loading, reload } = useLoad<{ experiments: Experiment[] }>(`/projects/${project.id}/experiments`);
  const [selected, setSelected] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';
  const exps = data?.experiments ?? [];
  const chosen = exps.filter((e) => selected.includes(e.id));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="mr-auto font-semibold">Experiments</h2>
        {selected.length > 0 && <button className="btn-ghost" onClick={() => setSelected([])}>Clear selection</button>}
        {canWrite && <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={14} /> Log experiment</button>}
      </div>
      {loading && !data && <SkeletonRows />}
      {data && exps.length === 0 && <div className="card"><EmptyState icon={<FlaskConical size={26} />} title="No experiments yet">Log runs with their dataset, code version, parameters and metrics to compare results.</EmptyState></div>}
      {exps.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr className="border-b border-line"><th className="w-8 px-3 py-2" /><th className="font-medium">Run</th><th className="px-2 font-medium">Dataset</th><th className="px-2 font-medium">Code</th><th className="px-2 font-medium">Metrics</th><th className="px-2 font-medium">Status</th></tr></thead>
            <tbody className="divide-y divide-line">
              {exps.map((e) => (
                <tr key={e.id} className="hover:bg-raised/60">
                  <td className="px-3"><input type="checkbox" aria-label={`Compare ${e.name}`} checked={selected.includes(e.id)} onChange={(ev) => setSelected((s) => (ev.target.checked ? [...s, e.id] : s.filter((x) => x !== e.id)))} /></td>
                  <td className="py-2"><span className="block font-medium">{e.name}</span><span className="block text-xs text-muted">{e.method_or_model} · {timeAgo(e.created_at)}</span></td>
                  <td className="px-2 text-xs text-muted">{e.dataset_ref || '—'} {e.dataset_version}</td>
                  <td className="px-2 font-mono text-xs text-muted">{e.commit_sha ? e.commit_sha.slice(0, 8) : '—'}</td>
                  <td className="px-2 text-xs text-muted">{Object.entries(e.metrics).slice(0, 3).map(([k, v]) => `${k}=${Number(v).toPrecision(4)}`).join(', ') || '—'}</td>
                  <td className="px-2"><span className="chip">{e.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {chosen.length >= 2 ? <ResultComparison runs={chosen} /> : exps.length > 1 && <p className="text-xs text-muted">Select two or more runs to compare their results.</p>}
      <CreateExperimentModal open={creating} onClose={() => setCreating(false)} projectId={project.id} onCreated={reload} />
    </div>
  );
}

function ResultComparison({ runs }: { runs: Experiment[] }) {
  const metricNames = useMemo(() => Array.from(new Set(runs.flatMap((r) => Object.keys(r.metrics)))).sort(), [runs]);
  const datasets = new Set(runs.map((r) => `${r.dataset_ref}@${r.dataset_version}`));
  const shared = metricNames.filter((m) => runs.every((r) => m in r.metrics));
  const partial = metricNames.filter((m) => !shared.includes(m));
  const paramKeys = Array.from(new Set(runs.flatMap((r) => Object.keys(r.parameters ?? {})))).sort();
  const chartData = shared.map((m) => ({ metric: m, ...Object.fromEntries(runs.map((r) => [r.name, r.metrics[m]])) }));

  return (
    <div className="card space-y-4 p-4">
      <h3 className="font-semibold">Result comparison</h3>
      {datasets.size > 1 && (
        <p className="flex items-start gap-2 rounded-md bg-warn/10 px-3 py-2 text-xs text-ink"><AlertTriangle size={14} className="mt-0.5 text-warn" />These runs use different datasets or dataset versions ({Array.from(datasets).join(', ')}). Metric values may not be directly comparable.</p>
      )}
      {partial.length > 0 && (
        <p className="flex items-start gap-2 rounded-md bg-raised px-3 py-2 text-xs text-muted"><AlertTriangle size={14} className="mt-0.5" />Not reported by every run, so not charted: {partial.join(', ')}.</p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line text-left text-xs text-muted"><th className="py-1.5 pr-3 font-medium" /> {runs.map((r) => <th key={r.id} className="px-2 font-medium">{r.name}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {/* No "best" highlighting: whether higher or lower is better depends on the metric. */}
            {metricNames.map((m) => (
              <tr key={m}><td className="py-1.5 pr-3 text-xs font-medium">{m}</td>
                {runs.map((r) => <td key={r.id} className="px-2 font-mono text-xs">{r.metrics[m] !== undefined ? Number(r.metrics[m]).toPrecision(5) : '—'}</td>)}
              </tr>
            ))}
            {[
              ['Dataset', (r: Experiment) => `${r.dataset_ref || '—'} ${r.dataset_version}`],
              ['Method', (r: Experiment) => r.method_or_model],
              ['Code version', (r: Experiment) => r.commit_sha ? r.commit_sha.slice(0, 10) : '—'],
              ['Environment', (r: Experiment) => r.environment_details || '—'],
            ].map(([label, fn]) => (
              <tr key={label as string} className="text-muted"><td className="py-1.5 pr-3 text-xs">{label as string}</td>{runs.map((r) => <td key={r.id} className="px-2 text-xs">{(fn as (r: Experiment) => string)(r)}</td>)}</tr>
            ))}
            {paramKeys.map((k) => {
              const vals = runs.map((r) => JSON.stringify(r.parameters?.[k] ?? null));
              const differs = new Set(vals).size > 1;
              return <tr key={k} className={differs ? '' : 'text-muted'}><td className="py-1.5 pr-3 text-xs">param: {k}</td>{vals.map((v, i) => <td key={i} className={`px-2 font-mono text-xs ${differs ? 'bg-warn/10' : ''}`}>{v}</td>)}</tr>;
            })}
          </tbody>
        </table>
      </div>
      {chartData.length > 0 && (
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
              <XAxis dataKey="metric" tick={{ fill: 'rgb(var(--muted))', fontSize: 11 }} />
              <YAxis tick={{ fill: 'rgb(var(--muted))', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {runs.map((r, i) => <Bar key={r.id} dataKey={r.name} fill={SERIES[i % SERIES.length]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function CreateExperimentModal({ open, onClose, projectId, onCreated }: { open: boolean; onClose(): void; projectId: string; onCreated(): void }) {
  const [form, setForm] = useState({ name: '', method_or_model: '', objective: '', dataset_ref: '', dataset_version: 'v1', repo_url: '', commit_sha: '', environment_details: '', parameters: '{}', metrics: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { toast } = useApp();
  const onError = useErrorToast();
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async () => {
    setErr(null);
    let parameters: Record<string, unknown>;
    const metrics: Record<string, number> = {};
    try {
      parameters = JSON.parse(form.parameters || '{}');
    } catch {
      setErr('Parameters must be valid JSON.');
      return;
    }
    for (const line of form.metrics.split(/[\n,]/).map((l) => l.trim()).filter(Boolean)) {
      const [k, v] = line.split('=').map((s) => s.trim());
      if (!k || v === undefined || Number.isNaN(Number(v))) {
        setErr(`Metric “${line}” must look like name=0.95`);
        return;
      }
      metrics[k] = Number(v);
    }
    setBusy(true);
    try {
      await api.post(`/projects/${projectId}/experiments`, { ...form, parameters, metrics, status: 'completed' });
      toast('Experiment logged', 'success');
      onClose();
      onCreated();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal wide open={open} onClose={onClose} title="Log experiment" footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || form.name.length < 2 || form.method_or_model.length < 2} onClick={save}>{busy && <Spinner size={14} />} Save</button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><span className="label">Run name</span><input className="input" value={form.name} onChange={set('name')} /></label>
        <label className="block"><span className="label">Method / model</span><input className="input" value={form.method_or_model} onChange={set('method_or_model')} /></label>
        <label className="block"><span className="label">Dataset</span><input className="input" value={form.dataset_ref} onChange={set('dataset_ref')} /></label>
        <label className="block"><span className="label">Dataset version</span><input className="input" value={form.dataset_version} onChange={set('dataset_version')} /></label>
        <label className="block"><span className="label">Repository URL</span><input className="input" value={form.repo_url} onChange={set('repo_url')} /></label>
        <label className="block"><span className="label">Commit</span><input className="input font-mono" value={form.commit_sha} onChange={set('commit_sha')} /></label>
        <label className="block sm:col-span-2"><span className="label">Environment</span><input className="input" value={form.environment_details} onChange={set('environment_details')} placeholder="e.g. PyTorch 2.4, CUDA 12.4, 1×A100" /></label>
        <label className="block"><span className="label">Parameters (JSON)</span><textarea className="input min-h-[90px] font-mono text-xs" value={form.parameters} onChange={set('parameters')} /></label>
        <label className="block"><span className="label">Metrics (name=value, one per line)</span><textarea className="input min-h-[90px] font-mono text-xs" value={form.metrics} onChange={set('metrics')} placeholder={'rmse=0.412\nssim=0.871'} /></label>
      </div>
      {err && <p className="mt-2 text-sm text-danger">{err}</p>}
    </Modal>
  );
}
