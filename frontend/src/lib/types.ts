// Tipos que reflejan el contrato de la API (backend/app/schemas.py y domain/*).

export type StyleId = 'motion_tech' | 'minimal_motion' | 'creative_explainer'
export type Level = 'low' | 'medium' | 'high'
export type Pace = 'slow' | 'medium' | 'fast'

export interface MotionTechParams {
  accent_color: string
  secondary_color: string
  grid_overlay: boolean
  hud_density: Level
  glow: number
  data_callouts: boolean
  transition: 'glitch' | 'scan' | 'slide'
}
export interface MinimalMotionParams {
  accent_color: string
  background_tone: 'dark' | 'neutral' | 'light'
  whitespace: 'airy' | 'balanced'
  type_scale: 'small' | 'medium' | 'large'
  easing: 'smooth' | 'spring'
  transition: 'fade' | 'mask' | 'slide'
}
export interface CreativeExplainerParams {
  accent_color: string
  palette: 'vibrant' | 'pastel' | 'paper'
  stroke: 'hand_drawn' | 'clean'
  icon_style: 'doodle' | 'flat'
  paper_texture: boolean
  draw_on_speed: Pace
}

export type SubtitleFont =
  | 'Inter'
  | 'Montserrat'
  | 'Poppins'
  | 'Bebas Neue'
  | 'Anton'
  | 'DM Serif Display'
  | 'JetBrains Mono'
export type SubtitleAnimation =
  | 'none'
  | 'fade'
  | 'pop'
  | 'slide_up'
  | 'karaoke'
  | 'word_by_word'
  | 'typewriter'

export interface SubtitleSettings {
  enabled: boolean
  font_family: SubtitleFont
  font_weight: 400 | 500 | 600 | 700 | 800 | 900
  font_size: number
  uppercase: boolean
  text_color: string
  highlight_color: string
  outline_enabled: boolean
  outline_color: string
  outline_width: number
  shadow_enabled: boolean
  shadow_color: string
  shadow_blur: number
  position: 'top' | 'middle' | 'bottom'
  auto_position: boolean
  safe_area: 'none' | 'platform'
  margin_percent: number
  max_words_per_line: number
  animation: SubtitleAnimation
  mode: 'classic' | 'dynamic'
  max_lines: number
}

export interface EditConfig {
  schema_version: 1 | 2
  style: {
    id: StyleId
    motion_tech: MotionTechParams
    minimal_motion: MinimalMotionParams
    creative_explainer: CreativeExplainerParams
  }
  subtitles: SubtitleSettings
  animations: {
    enabled: boolean
    intensity: Level
    placement: 'discrete' | 'balanced' | 'fullscreen'
    pace: Pace
  }
  audio: { sfx_enabled: boolean; sfx_volume: number; sfx_intensity: 'soft' | 'balanced' | 'strong'; background_music: false }
  delivery: { platform: Platform }
  export: {
    resolution: 'original' | '1080p' | '4k'
    fps: 'original' | 24 | 25 | 30 | 50 | 60
    format: 'mp4_h264' | 'mp4_hevc' | 'mov_prores'
    quality: 'high' | 'max'
    encoder: 'hardware' | 'software'
  }
}

export type ExportSettings = EditConfig['export']

export interface StyleDefinition {
  id: StyleId
  name: string
  tagline: string
  description: string
  palette: string[]
  typography: string
  motion_language: string
  composition: string
  pacing: string
  best_for: string[]
}

export interface Catalog {
  styles: StyleDefinition[]
  subtitle_fonts: SubtitleFont[]
  subtitle_animations: { id: SubtitleAnimation; label: string }[]
  default_config: EditConfig
}

export interface Preset {
  id: string
  name: string
  description: string
  style_id: StyleId
  is_builtin: boolean
  is_default: boolean
  config: EditConfig
  created_at: string
  updated_at: string
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Job {
  id: string
  kind: string
  label: string
  status: JobStatus
  project_id: string | null
  asset_id: string | null
  progress: number
  stage: string | null
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AudioTrack {
  index: number
  codec: string
  channels: number | null
  channel_layout: string | null
  sample_rate: number | null
  bit_rate: number | null
  language: string | null
  title: string | null
}

export interface Asset {
  id: string
  project_id: string
  role: string
  status: 'processing' | 'ready' | 'error'
  error: string | null
  original_filename: string
  file_rel: string
  size_bytes: number
  sha256: string
  container: 'mp4' | 'mov'
  format_name: string
  major_brand: string | null
  duration: number
  width: number
  height: number
  display_width: number
  display_height: number
  rotation: number
  orientation: 'vertical' | 'horizontal' | 'square'
  fps: number
  fps_num: number
  fps_den: number
  video_codec: string
  video_profile: string | null
  pix_fmt: string | null
  bit_depth: number | null
  color_transfer: string | null
  is_hdr: boolean
  bit_rate: number | null
  frame_count: number | null
  has_audio: boolean
  audio_tracks: AudioTrack[]
  creation_time: string | null
  browser_playable: boolean
  playback: 'original' | 'proxy' | 'unavailable'
  stream_url: string | null
  original_url: string
  proxy_ready: boolean
  thumbnail_url: string | null
  filmstrip: {
    url: string
    count: number
    tile_width: number
    tile_height: number
    interval: number
  } | null
  waveform_url: string | null
  verified_at: string | null
  created_at: string
}

export type ProjectStatus = 'empty' | 'importing' | 'processing' | 'ready' | 'error' | 'unavailable'

export interface ProjectSummary {
  id: string
  name: string
  status: ProjectStatus
  storage_id: string
  storage_available: boolean
  dir_rel: string
  preset_id: string | null
  style_id: StyleId
  created_at: string
  updated_at: string
  last_opened_at: string | null
  source: Asset | null
  active_job: Job | null
}

export interface EditorState {
  position: number
  volume: number
  muted: boolean
  settings_tab: string
}

export interface ProjectDetail extends ProjectSummary {
  config: EditConfig
  editor_state: EditorState
  storage_path: string | null
  storage_message: string | null
  assets: Asset[]
}

export interface Duplicate {
  project_id: string
  project_name: string
  asset_id: string
  original_filename: string
  created_at: string
}

export interface ImportCheckResult {
  ok: boolean
  extension_ok: boolean
  space_ok: boolean
  free_bytes: number | null
  duplicates: Duplicate[]
  errors: string[]
}

export interface ImportResult {
  project: ProjectSummary
  asset: Asset
  job: Job | null
}

export interface GeneralPreferences {
  theme: 'dark' | 'light' | 'system'
  library_view: 'grid' | 'list'
  library_sort: 'recent' | 'created' | 'name' | 'duration'
  autoplay_on_open: boolean
  loop_playback: boolean
  remember_playback_position: boolean
  default_volume: number
  playback_proxy: 'auto' | 'always' | 'never'
  reduce_motion: 'system' | 'on' | 'off'
  default_preset_id: string | null
}

export interface StorageStatus {
  configured: boolean
  available: boolean
  path: string | null
  storage_id: string | null
  code: string | null
  message: string | null
  writable: boolean
  free_bytes: number | null
  total_bytes: number | null
  volume_name: string | null
  is_external: boolean
  checked_at: string
}

export interface StorageCandidate {
  path: string
  exists: boolean
  parent_exists: boolean
  is_dir: boolean
  writable: boolean
  has_marker: boolean
  storage_id: string | null
  project_count: number
  is_empty: boolean
  free_bytes: number | null
  total_bytes: number | null
  volume_name: string | null
  is_external: boolean
  can_use: boolean
  warnings: string[]
  errors: string[]
  suggested_path: string | null
}

export interface StorageLocation {
  id: string
  path: string
  active: boolean
  available: boolean
  message: string | null
  project_count: number
  last_seen_at: string | null
}

export interface BrowseEntry {
  name: string
  path: string
  is_storage: boolean
}

export interface BrowseResult {
  path: string
  parent: string | null
  entries: BrowseEntry[]
  shortcuts: BrowseEntry[]
}

export interface Capability {
  id: string
  name: string
  phase: number
  available: boolean
}

export interface SystemInfo {
  app: { name: string; version: string; phase: number; edition?: string; creator?: string }
  platform?: {
    os: string
    arch: string
    apple_silicon: boolean
    nvidia_gpu: string | null
    notes: string[]
    transcription_engines: { id: string; name: string; implemented: boolean; available: boolean; reason: string }[]
    encoders: Record<string, { name: string; present: boolean; validated: boolean }[]>
  }
  os: string
  arch: string
  cpu: string
  cpu_count: number | null
  memory_bytes: number | null
  python: string
  node: string | null
  ffmpeg: {
    path: string
    version: string | null
    ffprobe_path: string
    ffprobe_version: string | null
    hardware_encoders: string[]
    has_libx264: boolean
  }
  paths: { app_home: string; database: string; database_bytes: number; logs: string | null }
  database: { integrity: string }
  server: { host: string; port: number }
  native_dialogs: boolean
  capabilities: Capability[]
}

export interface Waveform {
  version: number
  duration: number
  peaks_per_second: number
  max_peak: number
  peaks: number[]
}

// --- Fase 2 -------------------------------------------------------------------

export type TimingSource = 'asr' | 'refined' | 'aligned' | 'manual' | 'estimated'

export interface TranscriptWord {
  id: string
  text: string
  start: number
  end: number
  probability: number | null
  timing: TimingSource
  edited: boolean
  original_text: string | null
}

export interface TranscriptSegment {
  id: string
  start: number
  end: number
  text: string
  language: string | null
  avg_logprob: number | null
  no_speech_prob: number | null
  edited: boolean
  reviewed: boolean
  needs_timing_review: boolean
  words: TranscriptWord[]
}

export interface Transcript {
  id: string
  asset_id: string
  kind: 'asr' | 'edited'
  parent_id: string | null
  is_active: boolean
  status: 'ready' | 'no_audio' | 'no_speech'
  engine: string
  model: string
  language: string | null
  stats: {
    duration?: number
    words?: number
    estimated_words?: number
    refined?: number
    dropped_in_silence?: number
    realtime_factor?: number
    asr_seconds?: number
    languages?: Record<string, number>
    voice?: {
      speech: [number, number][]
      silences: [number, number][]
      speech_ratio: number
      speech_seconds: number
    }
  }
  segments: TranscriptSegment[]
  created_at: string
  updated_at: string
}

export interface TranscriptVersion {
  id: string
  kind: 'asr' | 'edited'
  model: string
  language: string | null
  status: string
  is_active: boolean
  created_at: string
  parent_id: string | null
}

export interface FaceInfo {
  box: [number, number, number, number]
  score: number
  right_eye: [number, number]
  left_eye: [number, number]
  nose: [number, number]
  mouth_right: [number, number]
  mouth_left: [number, number]
}

export interface Scene {
  index: number
  start: number
  end: number
  duration: number
  transition_in: 'start' | 'cut' | 'dissolve' | 'fade'
  metrics: {
    brightness: number
    contrast: number
    colorfulness: number
    motion: number
    static_ratio: number
  }
  labels: {
    brightness: 'dark' | 'normal' | 'bright'
    motion: 'static' | 'low' | 'medium' | 'high'
    faces: 'unknown' | 'none' | 'single' | 'multiple'
  }
  faces?: {
    status: string
    frames_checked?: number
    frames_with_faces?: number
    max_faces?: number
    union_box?: [number, number, number, number] | null
  }
}

export interface AnalysisFrame {
  id: string
  t: number
  reason: 'scene_start' | 'scene_mid' | 'scene_end' | 'interval' | 'on_demand'
  scene_index: number | null
  file: string
  url: string
  width: number
  height: number
  faces: FaceInfo[] | null
}

export interface VisualAnalysis {
  id: string
  params: Record<string, unknown>
  created_at: string
  duration: number
  frames_analyzed: number
  scenes: Scene[]
  transitions: { kind: string; start: number; end: number; score?: number }[]
  static_intervals: [number, number][]
  frames_extracted: number
  faces_enabled: boolean
}

export interface AnalysisState {
  asset_id: string
  transcript: Transcript | null
  versions: TranscriptVersion[]
  visual: VisualAnalysis | null
  frames: AnalysisFrame[]
  timing_labels: Record<TimingSource, string>
}

export interface TrackWord {
  id: string
  text: string
  start: number
  end: number
  x: number
  w: number
}

export interface TrackBlock {
  id: string
  start: number
  end: number
  top: number
  height: number
  position_source: 'manual' | 'auto-default' | 'auto-faces'
  lines: { baseline: number; width: number; words: TrackWord[] }[]
}

export interface SubtitleSafeArea {
  mode: 'none' | 'platform'
  platform: string | null
  band: [number, number] | null
  status: 'off' | 'ok' | 'no_space'
  blocks_without_space: number
  blocks: number
  range: [number, number] | null
}

export interface SubtitleTrack {
  version: number
  width: number
  height: number
  safe_area?: SubtitleSafeArea
  enabled: boolean
  mode: 'classic' | 'dynamic'
  animation: SubtitleAnimation
  font: {
    family: string
    css_family: string
    file: string
    weight: number
    size: number
    ascent: number
    descent: number
    line_height: number
  }
  style: {
    text_color: string
    highlight_color: string
    outline_color: string
    outline: number
    shadow: boolean
    shadow_color: string
    shadow_blur: number
    shadow_offset: number
  }
  blocks: TrackBlock[]
  transcript_id: string | null
}

export interface ExportPlan {
  width: number
  height: number
  fps: string
  container: string
  video_codec: string
  encoder: string
  pix_fmt: string
  estimated_bytes: number
  warnings: string[]
}

export interface ExportItem {
  id: string
  project_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  settings: Record<string, unknown>
  file_rel: string | null
  file_name: string | null
  size_bytes: number | null
  width: number | null
  height: number | null
  duration: number | null
  error: string | null
  job_id: string | null
  job: Job | null
  created_at: string
  finished_at: string | null
  url: string | null
}

export interface AsrEngine {
  id: 'mlx-whisper' | 'faster-whisper'
  name: string
  implemented: boolean
  available: boolean
  reason: string
}

export interface AsrModelsResponse {
  supported: boolean
  engines: AsrEngine[]
  default_model: string
  models: AsrModel[]
}

export interface AsrModel {
  id: string
  name: string
  engine: AsrEngine['id']
  license: string | null
  description: string
  repo: string
  revision: string
  size_bytes: number
  recommended: boolean
  installed: boolean
  downloaded_at: string | null
  path: string
  source_url: string
  job: Job | null
}

export interface AnalysisPreferences {
  transcription_model: 'large-v3-turbo' | 'large-v3-turbo-q4' | 'fw-large-v3-turbo' | 'fw-small'
  language: 'auto' | 'es' | 'en' | 'pt' | 'fr' | 'it' | 'de' | 'ca'
  scene_threshold: number
  min_scene_seconds: number
  static_min_seconds: number
  frame_interval_seconds: number
  max_frames: number
  detect_faces: boolean
}

// ---------------------------------------------------------------------------
// Fase 3 — Claude como director creativo
// ---------------------------------------------------------------------------

export type ClaudeEffort = 'low' | 'medium' | 'high'

export interface ClaudePreferences {
  transport: 'claude_code' | 'api'
  model: 'claude-opus-5-5'
  effort: ClaudeEffort
  cli_path: string | null
  timeout_seconds: number
  max_budget_usd_per_call: number
  max_frames: number
  daily_request_limit: number
  max_retries: number
  max_requests_per_operation: number
}

export interface BudgetStatus {
  used_24h: number
  limit_24h: number
  remaining_24h: number
  max_retries: number
  max_requests_per_operation: number
  billing: 'subscription' | 'api'
  estimates?: Record<string, { operation: string; expected: number; maximum: number }>
}

export interface ClaudeUsage {
  days: number
  requests: number
  by_day: { day: string; requests: number; errors: number; retries: number }[]
  by_step: Record<string, number>
  input_tokens: number
  output_tokens: number
  cost_estimate_usd: number | null
  billing: string[]
}

export type SceneVersionStatus = 'candidate' | 'applied' | 'archived' | 'discarded'

export interface SceneImpact {
  rerender_self?: boolean
  /** Fracción de la región que cambia de forma visible frente a la versión en uso. */
  visual_change?: number
  affected?: { intervention_id: string; start: number; end: number; template: string; reasons: string[] }[]
}

export interface SceneVersion {
  id: string
  number: number
  parent_number: number | null
  source: 'approved' | 'claude' | 'restored'
  status: SceneVersionStatus
  in_use: boolean
  instruction: string | null
  summary: string
  changes: string[]
  diff: string[]
  template: string | null
  direction: 'claude' | 'compilador'
  start: number
  end: number
  type: InterventionType
  impact: SceneImpact
  preview: { url: string; window: [number, number] } | null
  applied_plan_version: number | null
  created_at: string
}

export interface SceneState {
  intervention_id: string
  plan_version: number
  start: number
  end: number
  type: InterventionType
  goal: string | null
  in_use: number
  versions: SceneVersion[]
  job: Job | null
  budget: BudgetStatus & { estimate: { operation: string; expected: number; maximum: number } }
}

export interface RenderCacheUsage {
  clips: { count: number; bytes: number; unused_count: number; unused_bytes: number }
  previews: { count: number; bytes: number; unused_count: number; unused_bytes: number }
  unused_bytes: number
  bytes: number
}

export interface BackupItem {
  name: string
  kind: 'auto' | 'manual' | 'pre-migracion' | 'antes-de-restaurar' | 'pre-fase' | 'otra'
  size: number
  created_at: string
}

export interface RateLimitInfo {
  status: string
  resetsAt?: number
  rateLimitType?: string
  overageStatus?: string
  overageDisabledReason?: string
  isUsingOverage?: boolean
  unifiedWindows?: Record<string, { utilization: number; resetsAt: number }>
}

export interface ClaudeCheck {
  checked_at: string
  transport: string
  model: string
  effort: string
  ok: boolean
  error?: string
  code?: string
  model_reported?: string
  duration_ms?: number
  billing?: 'subscription' | 'api'
  rate_limit?: RateLimitInfo | null
  cost_estimate_usd?: number | null
  cli_version?: string
}

export interface ClaudeStatus {
  transports?: ('api' | 'claude_code')[]
  transport: 'claude_code' | 'api'
  model: string
  effort: ClaudeEffort
  last_check: ClaudeCheck | null
  api_key_saved: boolean
  cli: {
    installed: boolean
    cli_path?: string
    version?: string | null
    logged_in: boolean
    auth_method?: string
    api_provider?: string
    subscription?: string
    message?: string
  } | null
  ready: boolean
  verified: boolean
  billing: 'subscription' | 'api'
  key_store?: string
  pricing?: {
    usd_per_mtok: { input: number; output: number; cache_write: number; cache_read: number } | null
    as_of: string
  }
}

export interface ClaudeKeyCheck {
  ok: boolean
  code?: string
  error?: string
  model?: string
  display_name?: string | null
  duration_ms?: number
}

export interface SetupCheck {
  id: 'platform' | 'resources' | 'ffmpeg' | 'node' | 'panel' | 'remotion' | 'transcription' | 'claude'
  label: string
  status: 'ok' | 'warning' | 'error' | 'missing'
  detail: string
  fix: string
  data: Record<string, unknown>
}

export interface SetupStatus {
  checks: SetupCheck[]
  ready: boolean
  storage_configured: boolean
  completed_at: string | null
  data_dir: string
}

export type InterventionType =
  | 'keep_original'
  | 'overlay_motion'
  | 'fullscreen_animation'
  | 'diagram'
  | 'kinetic_typography'
  | 'screen_highlight'
  | 'transition'
  | 'no_intervention'

export type InterventionStatus = 'proposed' | 'accepted' | 'rejected' | 'needs_changes'
export type PlanStatus = 'draft' | 'in_review' | 'approved' | 'rejected' | 'needs_changes'

export interface Region {
  x: number
  y: number
  w: number
  h: number
}

export interface PlanIntervention {
  id: string
  start: number
  end: number
  anchor_from_word: string | null
  anchor_to_word: string | null
  timing: 'word_anchored' | 'model_seconds' | 'repaired'
  segment_ids: string[]
  transcript_excerpt: string
  scene_indices: number[]
  frame_ids: string[]
  type: InterventionType
  goal: string
  visual_description: string
  style: StyleId
  composition: { layout: string; background: string; region: Region | null; notes: string }
  elements: { kind: string; description: string; text: string | null; role: string }[]
  motion: {
    entry: string
    exit: string
    easing: string
    camera: string
    emphasis: string
    entry_seconds: number
    exit_seconds: number
  }
  transitions: { into: string; out: string }
  sfx: { kind: string; at: number; description: string }[]
  intensity: 'low' | 'medium' | 'high'
  avoid_face: boolean
  protected_regions: Region[]
  subtitles: 'keep' | 'hide' | 'move_top' | 'move_bottom' | 'integrate'
  rationale: string
  evidence: { observed: string[]; inferred: string[] }
  confidence: 'low' | 'medium' | 'high'
  status: InterventionStatus
  status_history: { status: string; at: string; note: string }[]
  user_note: string
  origin: 'generated' | 'revised' | 'alternative' | 'manual'
  revision: number
  warnings: string[]
  stale: boolean
  stale_reason: string
}

export interface PlanDocument {
  schema_version: number
  style: StyleId
  understanding: {
    summary: string
    topic: string
    intent: string
    audience: string
    tone: string
    content_kind: string
    structure: { start: number; end: number; label: string; purpose: string }[]
    scenes: { scene_index: number; kind: string; policy: 'open' | 'light' | 'preserve'; observed: string }[]
    observed_facts: string[]
    inferences: string[]
  }
  direction: {
    concept: string
    visual_language: string
    pacing: string
    typography: string
    color_usage: string
    density: string
  }
  interventions: PlanIntervention[]
  validation: {
    checked_at?: string
    errors?: string[]
    warnings?: string[]
    conflicts?: { a: string; b: string; seconds: number; reason: string }[]
    density_per_minute?: number
    density_target?: number
    notes_total?: number
  }
}

export interface PlanSessionItem {
  id: string
  operation: 'generate' | 'revise' | 'alternative'
  instruction: string | null
  scope: string[]
  status: string
  strategy: string | null
  result_version: number | null
  summary: string | null
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface PlanState {
  plan: {
    id: string
    status: PlanStatus
    status_label: string
    status_history: { status: string; at: string; note: string; version: number | null }[]
    current_version: number
    approved_version: number | null
    version: {
      number: number
      parent_number: number | null
      kind: string
      summary: string
      instruction: string | null
      created_at: string
      model: string | null
      effort: string | null
      immutable: boolean
    }
    document: PlanDocument
    staleness: {
      stale: boolean
      transcript_changed: boolean
      analysis_changed: boolean
      asset_changed: boolean
      affected: Record<string, string>
    }
    can_undo: boolean
    can_redo: boolean
    approval_problems: string[]
  } | null
  job: Job | null
  sessions: PlanSessionItem[]
  frames: Record<string, AnalysisFrame>
  labels: { types: Record<InterventionType, string>; statuses: Record<PlanStatus, string> }
  ready_to_plan: boolean
}

export interface PlanVersionItem {
  number: number
  parent_number: number | null
  kind: string
  summary: string
  instruction: string | null
  created_at: string
  immutable: boolean
  current: boolean
  approved: boolean
  interventions: number
  model: string | null
}

export interface UsageItem {
  id: string
  at: string
  step: string
  model: string
  effort: string
  status: string
  attempt: number
  input_tokens: number | null
  output_tokens: number | null
  cache_creation_tokens: number | null
  cache_read_tokens: number | null
  duration_ms: number | null
  cost_estimate_usd: number | null
  billing: 'subscription' | 'api'
  sent: { frame_count?: number; text_chars?: number; estimated_tokens?: number; content?: string }
  error: string | null
}

export interface ProjectUsage {
  calls: number
  ok: number
  errors: number
  cancelled: number
  retries: number
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  duration_ms: number
  cost_estimate_usd: number | null
  billing: string[]
  items: UsageItem[]
}

// ---------------------------------------------------------------------------
// Fase 4 — motor de animaciones
// ---------------------------------------------------------------------------

export interface EngineStatus {
  ready: boolean
  node: { path: string | null; version: string | null }
  remotion: { installed: string | null; expected: string; dir: string }
  browser: {
    installed: boolean
    name: string
    version: string
    download_bytes: number
    source: string
    path: string | null
    sha256: string | null
    codesign: string | null
    installed_at: string | null
  }
  license: string
  job: Job | null
}

export type AnimationStatus = 'pending' | 'rendering' | 'ready' | 'failed' | 'kept'

export interface AnimationItem {
  intervention_id: string
  type: InterventionType
  start: number
  end: number
  goal: string
  status: AnimationStatus
  template: string | null
  direction: 'claude' | 'compilador' | null
  notes: string[]
  warnings: LayoutWarning[]
  reused: boolean
  error: string | null
  render_ms: number | null
  size: [number, number, number] | null
  preview: { id: string; url: string; window: [number, number] } | null
  preview_running: boolean
}

export interface AnimationsState {
  approved_version: number | null
  engine_ready: boolean
  job: Job | null
  exporting: boolean
  items: AnimationItem[]
  summary: Partial<Record<AnimationStatus, number>>
}

export interface SfxItem {
  kind: string
  label: string
  duration: number
}

// ---------------------------------------------------------------------------
// Fase 4.1 — zonas seguras de redes sociales
// ---------------------------------------------------------------------------

export type Platform = 'universal' | 'instagram_reels' | 'tiktok' | 'none'

export interface SafeZone {
  id: string
  label: string
  x: number
  y: number
  w: number
  h: number
  kind: string
}

export interface SafeZoneProfile {
  id: Platform
  name: string
  zones: SafeZone[]
  sources: string[]
}

export interface LayoutWarning {
  code: string
  message: string
}

export interface AnimationLayout {
  approved_version: number | null
  platform?: SafeZoneProfile
  applies?: boolean
  subtitle_band?: [number, number] | null
  warnings: LayoutWarning[]
  items: {
    intervention_id: string
    start: number
    end: number
    type: InterventionType
    mode: string
    template: string
    region: { x: number; y: number; w: number; h: number }
    pip: { x: number; y: number; w: number; h: number } | null
    faces: { x: number; y: number; w: number; h: number }[]
    warnings: LayoutWarning[]
  }[]
}
