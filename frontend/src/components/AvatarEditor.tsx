import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Camera, Minus, Plus, RotateCcw, Trash2, Upload } from 'lucide-react';
import { api, uploadWithProgress } from '../services/apiClient';
import { useApp } from '../lib/app';
import { setAvatarVersion } from '../lib/avatars';
import { Avatar, Spinner, useErrorToast } from './ui';

const VIEW = 240; // crop window, CSS px
const OUTPUT = 512; // uploaded square; the server resizes it to 256 px
const ACCEPT = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_BYTES = 5 * 1024 * 1024; // matches AVATAR_MAX_UPLOAD_BYTES' default; the server has the final say

interface Crop { zoom: number; x: number; y: number }

/** Upload, crop/reposition, change or remove the signed-in user's profile picture. */
export function AvatarEditor() {
  const { user, updateUser, toast } = useApp();
  const onError = useErrorToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<{ url: string; img: HTMLImageElement } | null>(null);
  const [crop, setCrop] = useState<Crop>({ zoom: 1, x: 0, y: 0 });
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);

  useEffect(() => () => { if (source) URL.revokeObjectURL(source.url); }, [source]);

  if (!user) return null;
  const hasPicture = !!user.avatar_version;

  const baseScale = source ? VIEW / Math.min(source.img.naturalWidth, source.img.naturalHeight) : 1;
  const scale = baseScale * crop.zoom;
  const clamp = (c: Crop): Crop => {
    if (!source) return c;
    const s = baseScale * c.zoom;
    const w = source.img.naturalWidth * s;
    const h = source.img.naturalHeight * s;
    return { zoom: c.zoom, x: Math.min(0, Math.max(VIEW - w, c.x)), y: Math.min(0, Math.max(VIEW - h, c.y)) };
  };

  const choose = (file: File | undefined) => {
    setError(null);
    if (!file) return;
    if (!ACCEPT.includes(file.type)) {
      setError('Use a JPEG, PNG or WebP image.');
      return;
    }
    if (file.size > MAX_BYTES) {
      setError(`That image is ${(file.size / 1048576).toFixed(1)} MB. Profile pictures can be up to 5 MB.`);
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const s = VIEW / Math.min(img.naturalWidth, img.naturalHeight);
      setSource({ url, img });
      setCrop({ zoom: 1, x: (VIEW - img.naturalWidth * s) / 2, y: (VIEW - img.naturalHeight * s) / 2 });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      setError("That file isn't a readable image.");
    };
    img.src = url;
  };

  const zoomTo = (zoom: number) => {
    const z = Math.min(4, Math.max(1, zoom));
    // Keep the point at the centre of the window fixed while zooming.
    const cx = (VIEW / 2 - crop.x) / scale;
    const cy = (VIEW / 2 - crop.y) / scale;
    const s = baseScale * z;
    setCrop(clamp({ zoom: z, x: VIEW / 2 - cx * s, y: VIEW / 2 - cy * s }));
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { px: e.clientX, py: e.clientY, x: crop.x, y: crop.y };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) setCrop(clamp({ zoom: crop.zoom, x: d.x + e.clientX - d.px, y: d.y + e.clientY - d.py }));
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 24 : 6;
    const moves: Record<string, [number, number]> = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (moves[e.key]) {
      e.preventDefault();
      setCrop(clamp({ zoom: crop.zoom, x: crop.x + moves[e.key][0], y: crop.y + moves[e.key][1] }));
    } else if (e.key === '+' || e.key === '=') zoomTo(crop.zoom + 0.1);
    else if (e.key === '-') zoomTo(crop.zoom - 0.1);
  };

  const cancel = () => {
    setSource(null);
    setError(null);
    if (fileInput.current) fileInput.current.value = '';
  };

  const save = async () => {
    if (!source) return;
    setError(null);
    const canvas = document.createElement('canvas');
    canvas.width = OUTPUT;
    canvas.height = OUTPUT;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(source.img, -crop.x / scale, -crop.y / scale, VIEW / scale, VIEW / scale, 0, 0, OUTPUT, OUTPUT);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', 0.92));
    if (!blob) {
      setError('Could not prepare the image. Try a different file.');
      return;
    }
    const form = new FormData();
    form.append('file', blob, blob.type === 'image/webp' ? 'avatar.webp' : 'avatar.png');
    setProgress(0);
    try {
      const res = await uploadWithProgress<{ avatar_version: string }>('/users/me/avatar', form, 'PUT', setProgress);
      setAvatarVersion(user.id, res.avatar_version);
      updateUser({ avatar_version: res.avatar_version });
      toast('Profile picture updated', 'success');
      cancel();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed. Try again.');
    } finally {
      setProgress(null);
    }
  };

  const remove = async () => {
    try {
      await api.del('/users/me/avatar');
      setAvatarVersion(user.id, '');
      updateUser({ avatar_version: '' });
      toast('Profile picture removed', 'success');
    } catch (e) {
      onError(e);
    } finally {
      setConfirmRemove(false);
    }
  };

  const uploading = progress !== null;

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <input ref={fileInput} type="file" accept={ACCEPT.join(',')} className="sr-only" tabIndex={-1} aria-hidden="true"
        onChange={(e) => choose(e.target.files?.[0])} />

      {source ? (
        <div className="flex flex-col items-center gap-3">
          <div
            role="slider"
            tabIndex={0}
            aria-label="Picture position. Drag or use the arrow keys to move, plus and minus to zoom."
            aria-valuemin={1}
            aria-valuemax={4}
            aria-valuenow={Number(crop.zoom.toFixed(2))}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={() => { drag.current = null; }}
            onPointerCancel={() => { drag.current = null; }}
            onKeyDown={onKey}
            onWheel={(e) => zoomTo(crop.zoom - e.deltaY * 0.0015)}
            className="relative cursor-grab touch-none select-none overflow-hidden rounded-full bg-raised ring-4 ring-accent/20 active:cursor-grabbing"
            style={{ width: VIEW, height: VIEW }}
          >
            <img
              src={source.url}
              alt="Preview of your new profile picture"
              draggable={false}
              className="pointer-events-none absolute max-w-none"
              style={{ left: crop.x, top: crop.y, width: source.img.naturalWidth * scale, height: source.img.naturalHeight * scale }}
            />
          </div>
          <div className="flex w-full max-w-[240px] items-center gap-2">
            <button type="button" className="icon-btn" onClick={() => zoomTo(crop.zoom - 0.2)} aria-label="Zoom out"><Minus size={14} /></button>
            <input type="range" min={1} max={4} step={0.01} value={crop.zoom} onChange={(e) => zoomTo(Number(e.target.value))}
              aria-label="Zoom" className="flex-1 accent-[rgb(var(--accent))]" />
            <button type="button" className="icon-btn" onClick={() => zoomTo(crop.zoom + 0.2)} aria-label="Zoom in"><Plus size={14} /></button>
          </div>
          <p className="text-xs text-muted">Drag to reposition · scroll or use the slider to zoom</p>
        </div>
      ) : (
        <Avatar name={user.full_name} userId={user.id} version={user.avatar_version ?? ''} size={96} className="ring-4" />
      )}

      <div className="min-w-0 flex-1 space-y-3">
        <div>
          <p className="font-medium">Profile picture</p>
          <p className="text-[13px] text-muted">
            Shown to your co-authors next to your name, comments and activity. JPEG, PNG or WebP, up to 5 MB.
          </p>
        </div>

        {uploading && (
          <div className="space-y-1" aria-live="polite">
            <div className="h-1.5 overflow-hidden rounded-full bg-raised">
              <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
            </div>
            <p className="text-xs text-muted">Uploading… {Math.round((progress ?? 0) * 100)}%</p>
          </div>
        )}
        {error && <p role="alert" className="rounded-md bg-danger/10 px-2.5 py-2 text-[13px] text-danger">{error}</p>}

        <div className="flex flex-wrap gap-2">
          {source ? (
            <>
              <button type="button" className="btn-primary" onClick={save} disabled={uploading}>
                {uploading ? <Spinner size={14} /> : <Camera size={14} />} Save picture
              </button>
              <button type="button" className="btn-outline" onClick={() => setCrop(clamp({ zoom: 1, x: (VIEW - source.img.naturalWidth * baseScale) / 2, y: (VIEW - source.img.naturalHeight * baseScale) / 2 }))} disabled={uploading}>
                <RotateCcw size={14} /> Reset
              </button>
              <button type="button" className="btn-ghost" onClick={cancel} disabled={uploading}>Cancel</button>
            </>
          ) : confirmRemove ? (
            <>
              <span className="self-center text-[13px]">Remove your profile picture?</span>
              <button type="button" className="btn-danger" onClick={remove}><Trash2 size={14} /> Remove</button>
              <button type="button" className="btn-ghost" onClick={() => setConfirmRemove(false)}>Keep it</button>
            </>
          ) : (
            <>
              <button type="button" className="btn-primary" onClick={() => fileInput.current?.click()}>
                <Upload size={14} /> {hasPicture ? 'Change picture' : 'Upload picture'}
              </button>
              {hasPicture && (
                <button type="button" className="btn-outline" onClick={() => setConfirmRemove(true)}>
                  <Trash2 size={14} /> Remove
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
