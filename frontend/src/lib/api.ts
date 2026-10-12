import type {
  RenderCacheUsage,
  BackupItem,
  BudgetStatus,
  ClaudeUsage,
  SceneState,
  AnimationLayout,
  SafeZoneProfile,
  AnimationsState,
  EngineStatus,
  SfxItem,
  ClaudePreferences,
  ClaudeCheck,
  ClaudeStatus,
  InterventionStatus,
  InterventionType,
  PlanState,
  PlanVersionItem,
  ProjectUsage,
  StyleId,
  AnalysisFrame,
  AnalysisPreferences,
  AnalysisState,
  AsrModelsResponse,
  ClaudeKeyCheck,
  SetupStatus,
  ExportItem,
  ExportPlan,
  ExportSettings,
  SubtitleTrack,
  Transcript,
  BrowseResult,
  Catalog,
  EditConfig,
  EditorState,
  GeneralPreferences,
  ImportCheckResult,
  Job,
  Preset,
  ProjectDetail,
  ProjectSummary,
  StorageCandidate,
  StorageLocation,
  StorageStatus,
  SystemInfo,
  Waveform,
  Duplicate,
} from './types'

/** Evento global cuando la API pide el token de sesión (ver backend/app/session.py). */
export const SESSION_EVENT = 'vsa:session-required'

/** Cabecera exigida por el backend en peticiones que modifican datos (protección CSRF). */
export const CLIENT_HEADER = { 'X-VSA-Client': '1' } as const

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown> | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null = null,
  ) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export async function toApiError(res: Response): Promise<ApiError> {
  let body: { code?: string; message?: string; details?: Record<string, unknown> | null } = {}
  try {
    body = await res.json()
  } catch {
    /* respuesta sin JSON */
  }
  return new ApiError(
    res.status,
    body.code ?? 'http_error',
    body.message ?? `Error ${res.status} del servidor local.`,
    body.details ?? null,
  )
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(method !== 'GET' ? CLIENT_HEADER : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(
      0,
      'offline',
      'No hay conexión con el servidor local. ¿Sigue en ejecución Video Studio AI?',
    )
  }
  if (!res.ok) {
    const error = await toApiError(res)
    // Sin cookie de sesión (abierto sin el lanzador o token renovado): aviso global.
    if (error.status === 401 && error.code === 'session_required') window.dispatchEvent(new Event(SESSION_EVENT))
    throw error
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {})
const patch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body)
const put = <T>(path: string, body: unknown) => request<T>('PUT', path, body)
const del = <T>(path: string) => request<T>('DELETE', path)

const q = (params: Record<string, string | number | boolean | null | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  system: () => get<SystemInfo>('/api/system/info'),

  storageStatus: (fresh = false) => get<StorageStatus>(`/api/storage/status${q({ fresh })}`),
  validateStorage: (path: string) => post<StorageCandidate>('/api/storage/validate', { path }),
  configureStorage: (path: string) =>
    post<{ status: StorageStatus; adopted_projects: number }>('/api/storage/configure', { path }),
  storageLocations: () => get<StorageLocation[]>('/api/storage/locations'),
  browse: (path?: string) => get<BrowseResult>(`/api/storage/browse${q({ path })}`),
  pickFolder: () => post<{ path: string | null; supported: boolean }>('/api/storage/pick-folder'),

  projects: () => get<ProjectSummary[]>('/api/projects'),
  project: (id: string) => get<ProjectDetail>(`/api/projects/${id}`),
  createProject: (name: string, preset_id?: string | null) =>
    post<ProjectDetail>('/api/projects', { name, preset_id: preset_id ?? null }),
  openProject: (id: string) => post<ProjectDetail>(`/api/projects/${id}/open`),
  updateProject: (
    id: string,
    body: { name?: string; config?: EditConfig; editor_state?: EditorState },
  ) => patch<ProjectDetail>(`/api/projects/${id}`, body),
  applyPreset: (id: string, preset_id: string) =>
    post<ProjectDetail>(`/api/projects/${id}/apply-preset`, { preset_id }),
  deleteProject: (id: string, keepFiles = false) =>
    del<{ deleted: boolean; files_removed: boolean; message: string }>(
      `/api/projects/${id}${q({ keep_files: keepFiles || undefined })}`,
    ),

  checkImport: (body: {
    filename: string
    size_bytes: number
    quick_hash: string | null
    project_id?: string | null
  }) => post<ImportCheckResult>('/api/imports/check', body),
  importFromPath: (body: { path: string; project_id?: string | null; allow_duplicate?: boolean }) =>
    post<{ job: Job | null; duplicates: Duplicate[] }>('/api/imports/from-path', body),
  pickFiles: () => post<{ paths: string[]; supported: boolean }>('/api/imports/pick-files'),

  waveform: (url: string) => get<Waveform>(url),
  requestProxy: (assetId: string) => post<Job>(`/api/media/${assetId}/proxy`),
  verify: (assetId: string) => post<Job>(`/api/media/${assetId}/verify`),
  reprocess: (assetId: string) => post<Job>(`/api/media/${assetId}/reprocess`),
  reveal: (assetId: string) => post<{ ok: boolean }>(`/api/media/${assetId}/reveal`),

  jobs: (recentSeconds = 30) => get<Job[]>(`/api/jobs${q({ recent_seconds: recentSeconds })}`),
  cancelJob: (id: string) => post<Job>(`/api/jobs/${id}/cancel`),
  retryJob: (id: string) => post<Job>(`/api/jobs/${id}/retry`),

  catalog: () => get<Catalog>('/api/catalog'),
  presets: () => get<Preset[]>('/api/presets'),
  createPreset: (body: { name: string; description?: string; config: EditConfig }) =>
    post<Preset>('/api/presets', body),
  updatePreset: (id: string, body: { name?: string; description?: string; config?: EditConfig }) =>
    patch<Preset>(`/api/presets/${id}`, body),
  duplicatePreset: (id: string, name?: string) =>
    post<Preset>(`/api/presets/${id}/duplicate`, { name: name ?? null }),
  setDefaultPreset: (id: string) => post<Preset>(`/api/presets/${id}/default`),
  deletePreset: (id: string) => del<void>(`/api/presets/${id}`),

  // --- Fase 2 ---
  analyze: (
    projectId: string,
    body: { transcribe?: boolean; visual?: boolean; transcription_model?: string; language?: string } = {},
  ) => post<{ jobs: Job[] }>(`/api/projects/${projectId}/analyze`, body),
  analysis: (projectId: string) => get<AnalysisState>(`/api/projects/${projectId}/analysis`),
  subtitleTrack: (projectId: string) => get<SubtitleTrack>(`/api/projects/${projectId}/subtitles/track`),
  fonts: () => get<{ family: string; file: string; weight: string }[]>('/api/fonts'),
  patchSegment: (transcriptId: string, segmentId: string, body: { text?: string; reviewed?: boolean }) =>
    patch<Transcript>(`/api/transcripts/${transcriptId}/segments/${segmentId}`, body),
  putSegmentTimes: (
    transcriptId: string,
    segmentId: string,
    words: { id: string; start: number; end: number }[],
  ) => put<Transcript>(`/api/transcripts/${transcriptId}/segments/${segmentId}/times`, { words }),
  realign: (transcriptId: string, segmentIds: string[]) =>
    post<{ job: Job; transcript_id: string }>(`/api/transcripts/${transcriptId}/realign`, {
      segment_ids: segmentIds,
    }),
  activateTranscript: (transcriptId: string) => post<Transcript>(`/api/transcripts/${transcriptId}/activate`),
  captureFrame: (projectId: string, t: number) => post<AnalysisFrame>(`/api/projects/${projectId}/frames`, { t }),
  deleteFrame: (frameId: string) => del<void>(`/api/frames/${frameId}`),
  exportPlan: (projectId: string, settings: ExportSettings) =>
    post<{ ok: boolean; plan?: ExportPlan; error?: string; subtitles?: boolean }>(
      `/api/projects/${projectId}/exports/plan`,
      { settings },
    ),
  createExport: (projectId: string, settings: ExportSettings, withAnimations = false) =>
    post<ExportItem>(`/api/projects/${projectId}/exports`, { settings, with_animations: withAnimations }),
  exports: (projectId: string) => get<ExportItem[]>(`/api/projects/${projectId}/exports`),
  revealExport: (id: string) => post<{ ok: boolean }>(`/api/exports/${id}/reveal`),
  openExport: (id: string) => post<{ ok: boolean }>(`/api/exports/${id}/open`),
  deleteExport: (id: string) => del<void>(`/api/exports/${id}`),
  asrModels: () => get<AsrModelsResponse>('/api/asr/models'),
  downloadModel: (id: string) => post<Job>(`/api/asr/models/${id}/download`),
  deleteModel: (id: string) => del<void>(`/api/asr/models/${id}`),
  analysisSettings: () => get<AnalysisPreferences>('/api/settings/analysis'),
  saveAnalysisSettings: (body: AnalysisPreferences) => put<AnalysisPreferences>('/api/settings/analysis', body),

  // Fase 4: animaciones
  engineStatus: () => get<EngineStatus>('/api/animations/engine'),
  installEngine: () => post<{ job?: Job; already_installed?: boolean }>('/api/animations/engine/install'),
  sfxCatalog: () => get<SfxItem[]>('/api/animations/sfx'),
  safeZones: () => get<SafeZoneProfile[]>('/api/animations/safe-zones'),
  animationLayout: (projectId: string) => get<AnimationLayout>(`/api/projects/${projectId}/animations/layout`),
  animations: (projectId: string) => get<AnimationsState>(`/api/projects/${projectId}/animations`),
  prepareAnimations: (projectId: string, body: { use_claude: boolean; only?: string[] | null; confirm_budget?: boolean }) =>
    post<{ job: Job }>(`/api/projects/${projectId}/animations/prepare`, body),
  previewAnimation: (projectId: string, iid: string) =>
    post<{ job: Job }>(`/api/projects/${projectId}/animations/${iid}/preview`),
  // Fase 3: Claude y planificación
  claudeStatus: () => get<ClaudeStatus>('/api/claude/status'),
  claudeSettings: () => get<ClaudePreferences>('/api/claude/settings'),
  saveClaudeSettings: (body: ClaudePreferences) => put<ClaudePreferences>('/api/claude/settings', body),
  testClaude: () => post<ClaudeCheck>('/api/claude/test'),
  claudeLogin: () => post<{ opened: boolean; command?: string }>('/api/claude/login'),
  saveApiKey: (key: string) => put<void>('/api/claude/api-key', { key }),
  deleteApiKey: () => del<void>('/api/claude/api-key'),
  verifyClaudeKey: () => post<ClaudeKeyCheck>('/api/claude/verify-key'),

  // Community Edition: primera configuración y cierre ordenado
  setupStatus: () => get<SetupStatus>('/api/setup/status'),
  completeSetup: (completed = true) => post<{ completed_at?: string }>('/api/setup/complete', { completed }),
  shutdown: () => post<{ stopping: boolean }>('/api/system/shutdown'),
  plan: (projectId: string) => get<PlanState>(`/api/projects/${projectId}/plan`),
  generatePlan: (projectId: string, body: { style?: StyleId | null; instruction?: string | null; confirm_budget?: boolean }) =>
    post<{ job: Job; session_id: string }>(`/api/projects/${projectId}/plan/generate`, body),
  revisePlan: (projectId: string, body: { instruction: string; scope: string[]; confirm_budget?: boolean }) =>
    post<{ job: Job; session_id: string }>(`/api/projects/${projectId}/plan/revise`, body),
  alternative: (projectId: string, iid: string, instruction?: string, confirmBudget = false) =>
    post<{ job: Job; session_id: string }>(`/api/projects/${projectId}/plan/interventions/${iid}/alternative`, {
      instruction: instruction || null,
      confirm_budget: confirmBudget,
    }),
  patchIntervention: (
    projectId: string,
    iid: string,
    body: { status?: InterventionStatus; type?: InterventionType; user_note?: string },
  ) => patch<PlanState>(`/api/projects/${projectId}/plan/interventions/${iid}`, body),
  bulkPlan: (projectId: string, status: 'accepted' | 'rejected') =>
    post<PlanState>(`/api/projects/${projectId}/plan/bulk`, { status }),
  undoPlan: (projectId: string) => post<PlanState>(`/api/projects/${projectId}/plan/undo`),
  redoPlan: (projectId: string) => post<PlanState>(`/api/projects/${projectId}/plan/redo`),
  restorePlan: (projectId: string, n: number) => post<PlanState>(`/api/projects/${projectId}/plan/versions/${n}/restore`),
  planVersions: (projectId: string) => get<PlanVersionItem[]>(`/api/projects/${projectId}/plan/versions`),
  planStatus: (projectId: string, status: 'draft' | 'in_review' | 'rejected' | 'needs_changes', note = '') =>
    post<PlanState>(`/api/projects/${projectId}/plan/status`, { status, note }),
  refreshPlan: (projectId: string) => post<PlanState>(`/api/projects/${projectId}/plan/refresh`),
  approvePlan: (projectId: string, note = '') => post<PlanState>(`/api/projects/${projectId}/plan/approve`, { note }),
  approvedPlan: (projectId: string) => get<Record<string, unknown>>(`/api/projects/${projectId}/plan/approved`),
  usage: (projectId: string) => get<ProjectUsage>(`/api/projects/${projectId}/usage`),
  health: () => get<{ ok: boolean; version: string; environment: 'user' | 'test'; db_integrity: string }>('/api/health'),
  claudeBudget: () => get<BudgetStatus>('/api/claude/budget'),
  renderCache: (projectId: string) => get<RenderCacheUsage>(`/api/projects/${projectId}/render-cache`),
  cleanRenderCache: (projectId: string) =>
    post<RenderCacheUsage & { removed: number; freed_bytes: number }>(`/api/projects/${projectId}/render-cache/clean`, { confirm: true }),
  claudeUsage: (days = 30) => get<ClaudeUsage>(`/api/claude/usage?days=${days}`),
  scene: (projectId: string, iid: string) => get<SceneState>(`/api/projects/${projectId}/scenes/${iid}`),
  reviseScene: (projectId: string, iid: string, body: { instruction: string; base_number?: number | null; confirm_budget?: boolean }) =>
    post<{ reused: boolean; version: number | null; job: { id: string } | null }>(`/api/projects/${projectId}/scenes/${iid}/revise`, body),
  previewSceneVersion: (projectId: string, iid: string, n: number, compareWith?: number | null) =>
    post<{ job: { id: string } }>(`/api/projects/${projectId}/scenes/${iid}/versions/${n}/preview`, { compare_with: compareWith ?? null }),
  applySceneVersion: (projectId: string, iid: string, n: number) =>
    post<{ plan_version: number; job: { id: string }; draft_kept: number | null; directions_reused: number }>(
      `/api/projects/${projectId}/scenes/${iid}/versions/${n}/apply`,
      { confirm: true },
    ),
  discardSceneVersion: (projectId: string, iid: string, n: number) =>
    post<SceneState>(`/api/projects/${projectId}/scenes/${iid}/versions/${n}/discard`),
  backups: () => get<{ items: BackupItem[]; directory: string; integrity: string }>('/api/system/backups'),
  createBackup: () => post<BackupItem>('/api/system/backups'),
  restoreBackup: (name: string) =>
    post<{ restored: string; previous_state: string }>(`/api/system/backups/${encodeURIComponent(name)}/restore`, { confirm: true }),
  settings: () => get<{ general: GeneralPreferences }>('/api/settings'),
  saveGeneral: (general: GeneralPreferences) =>
    put<{ general: GeneralPreferences }>('/api/settings/general', general),
}
