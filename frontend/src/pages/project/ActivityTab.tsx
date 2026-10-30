import { Activity } from 'lucide-react';
import { useLoad } from '../../lib/app';
import { timeAgo } from '../../lib/text';
import type { Project } from '../../types';
import { Avatar, EmptyState, SkeletonRows } from '../../components/ui';

interface Event { id: string; actor_id: string; actor_name: string; summary: string; action: string; created_at: string }

export function ActivityTab({ project }: { project: Project }) {
  const { data, loading } = useLoad<{ activity: Event[] }>(`/projects/${project.id}/activity`);
  if (loading && !data) return <SkeletonRows />;
  if (!data?.activity.length) return <div className="card"><EmptyState icon={<Activity size={26} />} title="No activity yet" /></div>;
  return (
    <ol className="card divide-y divide-line">
      {data.activity.map((e) => (
        <li key={e.id} className="flex items-start gap-3 px-3 py-2 text-sm">
          <Avatar name={e.actor_name} userId={e.actor_id} size={24} />
          <span className="flex-1"><b className="font-medium">{e.actor_name}</b> <span className="text-muted">{e.summary}</span></span>
          <span className="shrink-0 text-xs text-faint">{timeAgo(e.created_at)}</span>
        </li>
      ))}
    </ol>
  );
}
