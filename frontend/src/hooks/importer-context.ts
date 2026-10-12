import { createContext, useContext } from 'react'

export type UploadStatus =
  | 'queued'
  | 'checking'
  | 'confirm'
  | 'uploading'
  | 'finalizing'
  | 'done'
  | 'error'
  | 'cancelled'

export interface UploadItem {
  id: string
  name: string
  size: number
  status: UploadStatus
  progress: number
  error?: string
  projectId?: string
  jobId?: string
  source: 'browser' | 'path'
}

export interface ImportTarget {
  projectId?: string | null
}

export interface ImporterApi {
  items: UploadItem[]
  importFiles: (files: File[] | FileList, target?: ImportTarget) => void
  /** Selector nativo (macOS) con copia en el servidor; si no existe, selector del navegador. */
  pickAndImport: (target?: ImportTarget) => Promise<void>
  pickWithBrowser: (target?: ImportTarget) => void
  cancel: (id: string) => void
  dismiss: (id: string) => void
  busy: boolean
}

export const ImporterContext = createContext<ImporterApi | null>(null)

export function useImporter(): ImporterApi {
  const ctx = useContext(ImporterContext)
  if (!ctx) throw new Error('useImporter fuera de ImporterProvider')
  return ctx
}
