import { api, ApiError } from '../services/apiClient';

export const CHUNK_SIZE = 4 * 1024 * 1024;

export interface UploadJob {
  key: string;
  file: File;
  folder: string;
  artifactType: string;
  uploadId?: string;
  sent: number;
  status: 'uploading' | 'paused' | 'failed' | 'done';
  error?: string;
}

export function guessArtifactType(name: string): string {
  const ext = name.toLowerCase().split('.').pop() ?? '';
  if (['py', 'r', 'jl', 'm', 'c', 'cpp', 'h', 'js', 'ts', 'java', 'rs', 'go', 'sh', 'sql'].includes(ext)) return 'code';
  if (ext === 'ipynb') return 'notebook';
  if (['png', 'jpg', 'jpeg', 'webp', 'pdf', 'eps'].includes(ext)) return 'figure';
  if (['log', 'out'].includes(ext)) return 'log';
  if (['pt', 'pth', 'ckpt', 'onnx', 'safetensors', 'h5'].includes(ext)) return 'checkpoint';
  if (['tex', 'bib', 'docx', 'md'].includes(ext)) return 'manuscript';
  return 'dataset';
}

/**
 * Upload a file in ordered chunks. Safe to call again after a failure: it asks the server how
 * many chunks it already holds and resumes from there (retried chunks are idempotent server-side).
 */
export async function runUpload(projectId: string, job: UploadJob, onProgress: (sent: number) => void, signal: { cancelled: boolean }): Promise<string> {
  const totalChunks = Math.max(1, Math.ceil(job.file.size / CHUNK_SIZE));
  let next = 0;
  if (job.uploadId) {
    const status = await api.get<{ uploaded_chunks: number; status: string }>(`/uploads/${job.uploadId}`);
    if (status.status !== 'in_progress') job.uploadId = undefined;
    else next = status.uploaded_chunks;
  }
  if (!job.uploadId) {
    const init = await api.post<{ upload_id: string }>(`/projects/${projectId}/uploads/init`, {
      filename: job.file.name,
      folder: job.folder,
      artifact_type: job.artifactType,
      total_size_bytes: job.file.size,
      total_chunks: totalChunks,
    });
    job.uploadId = init.upload_id;
  }
  for (let i = next; i < totalChunks; i++) {
    if (signal.cancelled) throw new Error('Paused');
    const blob = job.file.slice(i * CHUNK_SIZE, Math.min(job.file.size, (i + 1) * CHUNK_SIZE));
    let attempt = 0;
    for (;;) {
      try {
        await api.put(`/uploads/${job.uploadId}/chunks/${i}`, blob);
        break;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === 'object' && 'expected_chunk' in e.detail) {
          i = Number((e.detail as { expected_chunk: number }).expected_chunk) - 1;
          break;
        }
        attempt += 1;
        if (attempt >= 4 || (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 429)) throw e;
        await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
      }
    }
    onProgress(Math.min(job.file.size, (i + 1) * CHUNK_SIZE));
  }
  const done = await api.post<{ file_id: string }>(`/uploads/${job.uploadId}/complete`);
  return done.file_id;
}
