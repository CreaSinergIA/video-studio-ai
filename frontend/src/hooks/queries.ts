import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { GeneralPreferences, Job, ProjectDetail } from '@/lib/types'

export const keys = {
  system: ['system'] as const,
  storage: ['storage'] as const,
  locations: ['storage', 'locations'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  jobs: ['jobs'] as const,
  catalog: ['catalog'] as const,
  presets: ['presets'] as const,
  settings: ['settings'] as const,
  analysis: (id: string) => ['analysis', id] as const,
  track: (id: string) => ['track', id] as const,
  exports: (id: string) => ['exports', id] as const,
  asrModels: ['asr-models'] as const,
  analysisSettings: ['analysis-settings'] as const,
  claudeStatus: ['claude-status'] as const,
  claudeSettings: ['claude-settings'] as const,
  plan: (id: string) => ['plan', id] as const,
  planVersions: (id: string) => ['plan-versions', id] as const,
  usage: (id: string) => ['usage', id] as const,
  engine: ['engine'] as const,
  animations: (id: string) => ['animations', id] as const,
  sfx: ['sfx'] as const,
  safeZones: ['safe-zones'] as const,
  layout: (id: string, platform: string) => ['animation-layout', id, platform] as const,
  scene: (id: string, iid: string) => ['scene', id, iid] as const,
  budget: ['claude-budget'] as const,
  claudeUsage: ['claude-usage'] as const,
  backups: ['backups'] as const,
  setup: ['setup-status'] as const,
}

const isActive = (job: Job) => job.status === 'queued' || job.status === 'running'

export function useSystemInfo() {
  return useQuery({ queryKey: keys.system, queryFn: api.system, staleTime: 60_000 })
}

/** Estado del almacenamiento: se revisa periódicamente para detectar desconexiones. */
export function useStorageStatus() {
  return useQuery({
    queryKey: keys.storage,
    queryFn: () => api.storageStatus(true),
    refetchInterval: (query) => (query.state.data?.available ? 8_000 : 3_000),
    refetchOnWindowFocus: true,
  })
}

export function useStorageLocations() {
  return useQuery({ queryKey: keys.locations, queryFn: api.storageLocations })
}

export function useProjects() {
  return useQuery({
    queryKey: keys.projects,
    queryFn: api.projects,
    refetchInterval: (query) =>
      query.state.data?.some((p) => p.active_job || p.status === 'processing') ? 1_500 : 15_000,
  })
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: keys.project(id ?? ''),
    queryFn: () => api.project(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return false
      return data.active_job || data.status === 'processing' ? 1_500 : 15_000
    },
  })
}

export function useJobs() {
  return useQuery({
    queryKey: keys.jobs,
    queryFn: () => api.jobs(900),
    refetchInterval: (query) => (query.state.data?.some(isActive) ? 1_000 : 5_000),
  })
}

export function useCatalog() {
  return useQuery({ queryKey: keys.catalog, queryFn: api.catalog, staleTime: Infinity })
}

export function usePresets() {
  return useQuery({ queryKey: keys.presets, queryFn: api.presets })
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: api.settings, staleTime: 30_000 })
}

export function useSaveGeneral() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (general: GeneralPreferences) => api.saveGeneral(general),
    onMutate: async (general) => {
      await qc.cancelQueries({ queryKey: keys.settings })
      const previous = qc.getQueryData(keys.settings)
      qc.setQueryData(keys.settings, { general })
      return { previous }
    },
    onError: (_err, _vars, ctx) => qc.setQueryData(keys.settings, ctx?.previous),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.settings })
      qc.invalidateQueries({ queryKey: keys.presets })
    },
  })
}

export function useInvalidateProjects() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: keys.projects })
    qc.invalidateQueries({ queryKey: keys.jobs })
  }
}

export function setProjectCache(qc: ReturnType<typeof useQueryClient>, project: ProjectDetail) {
  qc.setQueryData(keys.project(project.id), project)
  qc.invalidateQueries({ queryKey: keys.projects, exact: true })
}

// --- Fase 2 ---------------------------------------------------------------------

export function useAnalysis(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.analysis(projectId ?? ''),
    queryFn: () => api.analysis(projectId as string),
    enabled: Boolean(projectId) && enabled,
    retry: false,
  })
}

export function useSubtitleTrack(projectId: string | undefined, version: string, enabled = true) {
  return useQuery({
    queryKey: [...keys.track(projectId ?? ''), version],
    queryFn: () => api.subtitleTrack(projectId as string),
    enabled: Boolean(projectId) && enabled,
    placeholderData: (prev) => prev,
    retry: false,
  })
}

export function useExports(projectId: string | undefined) {
  return useQuery({
    queryKey: keys.exports(projectId ?? ''),
    queryFn: () => api.exports(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.some((e) => e.status === 'queued' || e.status === 'running') ? 1_000 : 10_000,
  })
}

export function useAsrModels() {
  return useQuery({
    queryKey: keys.asrModels,
    queryFn: api.asrModels,
    refetchInterval: (query) => (query.state.data?.models.some((m) => m.job) ? 1_000 : false),
  })
}

export function useAnalysisSettings() {
  return useQuery({ queryKey: keys.analysisSettings, queryFn: api.analysisSettings })
}

// --- Fase 3 -----------------------------------------------------------------

export function useClaudeStatus() {
  return useQuery({ queryKey: keys.claudeStatus, queryFn: api.claudeStatus, staleTime: 15_000 })
}

export function useClaudeSettings() {
  return useQuery({ queryKey: keys.claudeSettings, queryFn: api.claudeSettings })
}

export function usePlan(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.plan(projectId ?? ''),
    queryFn: () => api.plan(projectId as string),
    enabled: Boolean(projectId) && enabled,
    // Mientras Claude trabaja, refresco frecuente del progreso real de la tarea.
    refetchInterval: (query) => (query.state.data?.job ? 1_500 : false),
  })
}

export function usePlanVersions(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.planVersions(projectId ?? ''),
    queryFn: () => api.planVersions(projectId as string),
    enabled: Boolean(projectId) && enabled,
  })
}

export function useUsage(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.usage(projectId ?? ''),
    queryFn: () => api.usage(projectId as string),
    enabled: Boolean(projectId) && enabled,
  })
}

// --- Fase 4 -----------------------------------------------------------------

export function useEngine() {
  return useQuery({
    queryKey: keys.engine,
    queryFn: api.engineStatus,
    refetchInterval: (query) => (query.state.data?.job ? 1_000 : false),
  })
}

export function useAnimations(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.animations(projectId ?? ''),
    queryFn: () => api.animations(projectId as string),
    enabled: Boolean(projectId) && enabled,
    refetchInterval: (query) => (query.state.data?.job || query.state.data?.exporting ? 1_500 : false),
  })
}

export function useSfx() {
  return useQuery({ queryKey: keys.sfx, queryFn: api.sfxCatalog, staleTime: Infinity })
}

// --- Fase 4.1 ---------------------------------------------------------------

export function useSafeZones() {
  return useQuery({ queryKey: keys.safeZones, queryFn: api.safeZones, staleTime: Infinity })
}

export function useAnimationLayout(projectId: string | undefined, platform: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.layout(projectId ?? '', platform),
    queryFn: () => api.animationLayout(projectId as string),
    enabled: Boolean(projectId) && enabled,
    staleTime: 30_000,
  })
}

/** Una escena (intervención animada) con sus versiones; se refresca mientras hay una tarea. */
export function useScene(projectId: string, iid: string | null) {
  return useQuery({
    queryKey: keys.scene(projectId, iid ?? ''),
    queryFn: () => api.scene(projectId, iid as string),
    enabled: Boolean(iid),
    refetchInterval: (query) => (query.state.data?.job ? 1_200 : false),
  })
}

export function useClaudeBudget() {
  return useQuery({ queryKey: keys.budget, queryFn: api.claudeBudget, staleTime: 5_000 })
}

export function useClaudeUsage() {
  return useQuery({ queryKey: keys.claudeUsage, queryFn: () => api.claudeUsage(30) })
}

export function useBackups() {
  return useQuery({ queryKey: keys.backups, queryFn: api.backups })
}

// --- Community Edition: primera configuración ------------------------------

export function useSetupStatus() {
  return useQuery({ queryKey: keys.setup, queryFn: api.setupStatus, staleTime: 5_000 })
}
