export type ProjectRole = 'owner' | 'editor' | 'reviewer' | 'viewer';
export type TaskStatus = 'todo' | 'in_progress' | 'in_review' | 'done';
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';
export type ThemeMode = 'light' | 'dark' | 'system';
export type AccentColor = 'indigo' | 'blue' | 'violet' | 'teal' | 'emerald' | 'rose' | 'amber';

export interface SessionUser {
  id: string;
  username: string;
  email: string;
  full_name: string;
  email_verified: boolean;
  /** Changes whenever the profile picture changes; empty when there is none. */
  avatar_version?: string;
}

export interface ProjectMemberSummary {
  user_id: string;
  username: string;
  full_name: string;
  role: ProjectRole;
}

export interface Project {
  id: string;
  title: string;
  description: string;
  research_domain: string;
  status: string;
  publication_status: string;
  visibility: string;
  my_role: ProjectRole;
  member_count?: number;
  members?: ProjectMemberSummary[];
  keywords: string[];
  last_editor_name: string;
  last_edited_at: string;
  updated_at: string;
  storage_used_bytes?: number;
  storage_quota_bytes?: number;
}

export const MANUSCRIPT_STATUSES = [
  'Working Draft',
  'Internal Review',
  'Ready for Submission',
  'Submitted',
  'Under Review',
  'Revision Requested',
  'Accepted',
  'Published',
  'Rejected',
  'Archived',
] as const;
export type ManuscriptStatus = (typeof MANUSCRIPT_STATUSES)[number];
export const OWNER_ONLY_STATUSES: ReadonlySet<string> = new Set([
  'Submitted', 'Under Review', 'Revision Requested', 'Accepted', 'Published', 'Rejected',
]);

export const PUBLICATION_STATUSES = [
  'Research in Progress', 'Drafting', 'Under Internal Review', 'Ready for Submission', 'Submitted',
  'Under Review', 'Revision Requested', 'Accepted', 'Published', 'Rejected', 'Archived',
] as const;

export interface Manuscript {
  id: string;
  project_id: string;
  title: string;
  status: ManuscriptStatus;
  review_status: 'draft' | 'in_review' | 'approved' | 'changes_requested';
  main_file_path: string;
  /** TeX engine the source is written for; used only in the export README. */
  compiler: 'pdflatex' | 'xelatex' | 'lualatex';
  is_pinned: boolean;
  is_deleted: boolean;
  last_editor_name: string;
  updated_at: string;
  created_at: string;
  my_role: ProjectRole;
  linked_artifacts: { type: string; id: string }[];
  files?: ManuscriptFile[];
  project_title?: string;
  warnings?: string[];
  skipped?: string[];
}

export interface ManuscriptFile {
  id: string;
  document_id: string;
  path: string;
  file_kind: 'text' | 'binary' | 'folder';
  size_bytes: number;
  media_type: string;
  updated_at: string;
  deleted_at?: string | null;
  revision: number;
  content?: string;
  updated_by_name?: string;
}

export interface OutlineItem {
  kind: string;
  level: number;
  title: string;
  label: string;
  start: number;
  end: number;
  line: number;
  end_line: number;
}

export interface FileVersion {
  id: string;
  version_number: number;
  summary: string;
  version_kind: 'auto' | 'manual' | 'restore' | 'import' | 'initial';
  created_at: string;
  author_name: string | null;
  length: number;
}

export interface CommentAnchor {
  from: number;
  to: number;
  line: number;
  context_before?: string;
  context_after?: string;
}

export interface DocComment {
  id: string;
  file_id: string | null;
  parent_id: string | null;
  body: string;
  anchor: CommentAnchor;
  quoted_text: string;
  status: 'open' | 'resolved';
  author_id: string;
  author_name: string;
  author_username: string;
  resolved_by_name: string | null;
  created_at: string;
  replies?: DocComment[];
}

export interface Suggestion {
  id: string;
  file_id: string;
  author_id: string;
  author_name: string;
  anchor: CommentAnchor;
  original_text: string;
  proposed_text: string;
  note: string;
  status: 'pending' | 'accepted' | 'rejected' | 'stale';
  created_at: string;
}

export interface Reference {
  id: string;
  cite_key: string;
  entry_type: string;
  title: string;
  authors: string;
  year: number;
  doi: string;
  journal_or_conference: string;
  abstract: string;
  notes: string;
  fields: Record<string, string>;
  tags: string[];
}

export interface CitationIndex {
  labels: { label: string; line: number; file: string }[];
  citations: { key: string; title: string; authors: string; year: string | number; source: string }[];
  files: { path: string; kind: string }[];
}
