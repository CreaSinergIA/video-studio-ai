import type { EditConfig, StyleId } from '@/lib/types'
import './style-preview.css'

/**
 * Muestras animadas que ilustran el lenguaje visual de cada estilo (composición, movimiento
 * y ritmo). Son ilustraciones de la interfaz, no resultados generados.
 */
export function StylePreview({ style, config, className }: { style: StyleId; config?: EditConfig['style']; className?: string }) {
  if (style === 'motion_tech') {
    const accent = config?.motion_tech.accent_color ?? '#22D3EE'
    const secondary = config?.motion_tech.secondary_color ?? '#A78BFA'
    const grid = config?.motion_tech.grid_overlay ?? true
    return (
      <svg viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice" className={className} role="img" aria-label="Muestra Motion Tech">
        <rect width="160" height="100" fill="#05070D" />
        {grid &&
          Array.from({ length: 9 }, (_, i) => (
            <line key={`v${i}`} x1={i * 20} y1="0" x2={i * 20} y2="100" stroke={accent} strokeOpacity=".08" />
          ))}
        {grid &&
          Array.from({ length: 6 }, (_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 20} x2="160" y2={i * 20} stroke={accent} strokeOpacity=".08" />
          ))}
        <path className="vsa-tech-link" d="M30 70 L62 38 L98 52 L130 24" fill="none" stroke={accent} strokeWidth="1.4" />
        {[
          [30, 70],
          [62, 38],
          [98, 52],
          [130, 24],
        ].map(([x, y], i) => (
          <g key={i} className="vsa-tech-node" style={{ animationDelay: `${i * 0.25}s` }}>
            <circle cx={x} cy={y} r="5" fill="none" stroke={accent} strokeOpacity=".35" />
            <circle cx={x} cy={y} r="2.2" fill={accent} />
          </g>
        ))}
        <rect x="104" y="64" width="44" height="22" rx="2" fill="none" stroke={secondary} strokeOpacity=".7" className="vsa-tech-panel" />
        <rect x="108" y="69" width="18" height="2" fill={secondary} className="vsa-tech-bar" />
        <rect x="108" y="75" width="30" height="2" fill={accent} opacity=".6" className="vsa-tech-bar" style={{ animationDelay: '.3s' }} />
        <rect x="108" y="80" width="12" height="2" fill={secondary} opacity=".6" className="vsa-tech-bar" style={{ animationDelay: '.6s' }} />
        <rect className="vsa-tech-scan" x="0" y="0" width="160" height="10" fill={`url(#scan-${accent.slice(1)})`} />
        <defs>
          <linearGradient id={`scan-${accent.slice(1)}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={accent} stopOpacity="0" />
            <stop offset="1" stopColor={accent} stopOpacity=".35" />
          </linearGradient>
        </defs>
        <text x="12" y="18" fill={accent} fontSize="6" fontFamily="JetBrains Mono, monospace" opacity=".8">
          SYS.ANALYSIS
        </text>
      </svg>
    )
  }
  if (style === 'minimal_motion') {
    const accent = config?.minimal_motion.accent_color ?? '#F5F0E8'
    const tone = config?.minimal_motion.background_tone ?? 'dark'
    const bg = tone === 'light' ? '#F4F1EC' : tone === 'neutral' ? '#2A2A2E' : '#0E0E10'
    const fg = tone === 'light' ? '#16161A' : accent
    return (
      <svg viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice" className={className} role="img" aria-label="Muestra Minimal Motion">
        <rect width="160" height="100" fill={bg} />
        <g className="vsa-min-reveal">
          <text x="22" y="50" fill={fg} fontSize="15" fontWeight="700" fontFamily="Inter Variable, sans-serif" letterSpacing="-.5">
            Menos,
          </text>
        </g>
        <g className="vsa-min-reveal" style={{ animationDelay: '.45s' }}>
          <text x="22" y="68" fill={fg} fontSize="15" fontWeight="300" fontFamily="Inter Variable, sans-serif" letterSpacing="-.5" opacity=".75">
            pero mejor.
          </text>
        </g>
        <rect x="22" y="78" height="1" fill={fg} className="vsa-min-line" opacity=".6" />
        <circle cx="132" cy="28" r="3" fill={fg} className="vsa-min-dot" />
      </svg>
    )
  }
  const accent = config?.creative_explainer.accent_color ?? '#FF7A59'
  const palette = config?.creative_explainer.palette ?? 'vibrant'
  const bg = palette === 'paper' ? '#F3EAD7' : palette === 'pastel' ? '#F6F0FF' : '#FFF8EC'
  return (
    <svg viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice" className={className} role="img" aria-label="Muestra Creative Explainer">
      <rect width="160" height="100" fill={bg} />
      <g className="vsa-cre-bounce">
        <rect x="22" y="34" width="34" height="30" rx="6" fill={accent} />
        <circle cx="39" cy="46" r="5" fill="#fff" />
        <rect x="31" y="55" width="16" height="3" rx="1.5" fill="#fff" opacity=".8" />
      </g>
      <path className="vsa-cre-draw" d="M62 50 C 80 30, 96 30, 110 46" fill="none" stroke="#2D3142" strokeWidth="2" strokeLinecap="round" />
      <path className="vsa-cre-draw" d="M104 40 L111 47 L102 50" fill="none" stroke="#2D3142" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animationDelay: '.5s' }} />
      <g className="vsa-cre-bounce" style={{ animationDelay: '.35s' }}>
        <circle cx="128" cy="52" r="15" fill="#FFD166" />
        <path d="M121 52 l5 5 l9 -10" fill="none" stroke="#2D3142" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <path className="vsa-cre-draw" d="M20 78 Q 60 72 100 79 T 140 77" fill="none" stroke={accent} strokeWidth="2" strokeLinecap="round" style={{ animationDelay: '.8s' }} />
    </svg>
  )
}
