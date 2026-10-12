import { ApiError, CLIENT_HEADER } from './api'
import type { ImportResult } from './types'

const QUICK_HASH_CHUNK = 4 * 1024 * 1024

/**
 * Huella rápida idéntica a la del backend: sha256(«tamaño:» + primeros 4 MB + últimos 4 MB).
 * Permite detectar duplicados antes de transferir el archivo. Lee como máximo 8 MB.
 */
export async function quickHash(file: File): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null
  const head = await file.slice(0, Math.min(QUICK_HASH_CHUNK, file.size)).arrayBuffer()
  const tail = await file.slice(Math.max(0, file.size - QUICK_HASH_CHUNK), file.size).arrayBuffer()
  const prefix = new TextEncoder().encode(`${file.size}:`)
  const data = new Uint8Array(prefix.byteLength + head.byteLength + tail.byteLength)
  data.set(prefix, 0)
  data.set(new Uint8Array(head), prefix.byteLength)
  data.set(new Uint8Array(tail), prefix.byteLength + head.byteLength)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

export const SUPPORTED_EXTENSIONS = ['.mp4', '.mov']

export function hasSupportedExtension(name: string): boolean {
  const lower = name.toLowerCase()
  return SUPPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

export interface UploadHandle {
  promise: Promise<ImportResult>
  abort: () => void
}

/**
 * Sube el archivo como cuerpo binario. El navegador lo transmite desde disco por bloques
 * (no se carga entero en memoria) y XHR informa del progreso real de envío.
 */
export function uploadFile(
  file: File,
  params: { projectId?: string | null; projectName?: string | null; allowDuplicate?: boolean },
  onProgress: (fraction: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest()
  const search = new URLSearchParams({ filename: file.name })
  if (params.projectId) search.set('project_id', params.projectId)
  if (params.projectName) search.set('project_name', params.projectName)
  if (params.allowDuplicate) search.set('allow_duplicate', 'true')

  const promise = new Promise<ImportResult>((resolve, reject) => {
    xhr.open('POST', `/api/imports/upload?${search.toString()}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.setRequestHeader(Object.keys(CLIENT_HEADER)[0], Object.values(CLIENT_HEADER)[0])
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total)
    }
    xhr.onload = () => {
      let body: Record<string, unknown> = {}
      try {
        body = JSON.parse(xhr.responseText || '{}')
      } catch {
        /* sin JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as unknown as ImportResult)
      } else {
        reject(
          new ApiError(
            xhr.status,
            String(body.code ?? 'http_error'),
            String(body.message ?? `Error ${xhr.status} al subir el archivo.`),
            (body.details as Record<string, unknown> | null) ?? null,
          ),
        )
      }
    }
    xhr.onerror = () =>
      reject(new ApiError(0, 'offline', 'Se perdió la conexión con el servidor local.'))
    xhr.onabort = () => reject(new ApiError(499, 'upload_cancelled', 'Subida cancelada.'))
    xhr.send(file)
  })
  return { promise, abort: () => xhr.abort() }
}
