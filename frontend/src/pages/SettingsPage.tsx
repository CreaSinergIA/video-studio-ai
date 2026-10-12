import { useEffect, useState } from 'react'
import { useLocation } from 'react-router'
import { AudioLines, Clapperboard, Cpu, DatabaseBackup, Info, HardDrive, Layers, Palette, Sparkles, SlidersHorizontal } from 'lucide-react'
import { AboutSection } from '@/components/settings/AboutSection'
import { BackupsSection } from '@/components/settings/BackupsSection'
import { ClaudeSection } from '@/components/settings/ClaudeSection'
import { EngineSection } from '@/components/settings/EngineSection'
import {
  AnalysisSettingsSection,
  EnvironmentSection,
  GeneralSection,
  PresetsSection,
  StorageSection,
  StylesSection,
} from '@/components/settings/sections'
import { cn } from '@/lib/cn'

const SECTIONS = [
  { id: 'storage', label: 'Almacenamiento', icon: HardDrive },
  { id: 'general', label: 'Preferencias', icon: SlidersHorizontal },
  { id: 'presets', label: 'Presets', icon: Layers },
  { id: 'analysis', label: 'Transcripción', icon: AudioLines },
  { id: 'claude', label: 'Claude', icon: Sparkles },
  { id: 'engine', label: 'Animaciones', icon: Clapperboard },
  { id: 'styles', label: 'Estilos', icon: Palette },
  { id: 'backups', label: 'Datos y respaldos', icon: DatabaseBackup },
  { id: 'environment', label: 'Entorno', icon: Cpu },
  { id: 'about', label: 'Acerca de', icon: Info },
]

export function SettingsPage() {
  const location = useLocation()
  const [active, setActive] = useState('storage')

  useEffect(() => {
    const id = location.hash.replace('#', '')
    if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [location.hash])

  useEffect(() => {
    const root = document.getElementById('settings-scroll')
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { root, rootMargin: '0px 0px -65% 0px' },
    )
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [])

  return (
    <div id="settings-scroll" className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1240px] gap-10 px-8 pb-24 pt-8">
        <nav className="sticky top-8 hidden h-fit w-48 shrink-0 lg:block" aria-label="Secciones de ajustes">
          <h1 className="mb-5 text-[26px] font-semibold tracking-tight text-fg">Ajustes</h1>
          <ul className="space-y-0.5">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className={cn(
                    'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition',
                    active === id ? 'bg-surface-3 text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                  )}
                >
                  <Icon className="size-4" />
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1 space-y-6">
          <h1 className="text-[26px] font-semibold tracking-tight text-fg lg:hidden">Ajustes</h1>
          <div id="storage" className="scroll-mt-8">
            <StorageSection />
          </div>
          <div id="general" className="scroll-mt-8">
            <GeneralSection />
          </div>
          <div id="presets" className="scroll-mt-8">
            <PresetsSection />
          </div>
          <div id="analysis" className="scroll-mt-8">
            <AnalysisSettingsSection />
          </div>
          <div id="claude" className="scroll-mt-8">
            <ClaudeSection />
          </div>
          <div id="engine" className="scroll-mt-8">
            <EngineSection />
          </div>
          <div id="styles" className="scroll-mt-8">
            <StylesSection />
          </div>
          <div id="backups" className="scroll-mt-8">
            <BackupsSection />
          </div>
          <div id="environment" className="scroll-mt-8">
            <EnvironmentSection />
          </div>
          <div id="about" className="scroll-mt-8">
            <AboutSection />
          </div>
        </div>
      </div>
    </div>
  )
}
