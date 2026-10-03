import { apiRequest } from "./client";

// Mirrors the backend's SINGLE_SHOT_UPLOAD_MAX_BYTES default (app/config.py).
// If that config value changes, update this constant to match -- the
// backend enforces the real limit either way (this just picks which flow
// to use so large files don't get streamed once, rejected, then retried).
export const SINGLE_SHOT_MAX_BYTES = 5 * 1024 * 1024;
const CHUNK_SIZE = 2 * 1024 * 1024;

/**
 * Uploads `file` into `folderId` (null = root), automatically choosing the
 * single-shot endpoint for small files or the chunked flow
 * (init -> chunk*N -> complete) for anything over SINGLE_SHOT_MAX_BYTES.
 * Calls `onProgress(fraction)` (0..1) as it goes -- for a single-shot
 * upload that's just 0 then 1 (the browser gives no mid-request progress
 * via fetch), for a chunked upload it advances one step per acked chunk.
 */
export async function uploadFileSmart(file, folderId, token, onProgress) {
  if (file.size <= SINGLE_SHOT_MAX_BYTES) {
    onProgress?.(0);
    const formData = new FormData();
    formData.append("file", file);
    if (folderId) formData.append("folder_id", folderId);
    const result = await apiRequest("/files/upload", { method: "POST", token, formData });
    onProgress?.(1);
    return result;
  }

  const chunkCount = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
  const { upload_id } = await apiRequest("/files/upload/init", {
    method: "POST",
    token,
    json: { filename: file.name, total_size: file.size, chunk_count: chunkCount, folder_id: folderId || null },
  });

  for (let i = 0; i < chunkCount; i++) {
    const start = i * CHUNK_SIZE;
    const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size));
    const formData = new FormData();
    formData.append("chunk", blob, `chunk-${i}`);
    await apiRequest(`/files/upload/${upload_id}/chunk/${i}`, { method: "POST", token, formData });
    onProgress?.((i + 1) / chunkCount);
  }

  return await apiRequest(`/files/upload/${upload_id}/complete`, { method: "POST", token });
}
