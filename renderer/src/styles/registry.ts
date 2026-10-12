/**
 * Registro de estilos del renderizador (Fase 5). Cada estilo aporta sus plantillas, su fondo a
 * pantalla completa y el marco del recuadro de la persona. Debe tener las MISMAS plantillas que
 * su definición del backend (`backend/app/styles/<estilo>.py`); una prueba lo comprueba.
 * Para añadir un estilo: crea `styles/<estilo>.tsx` con esas tres piezas y regístralo aquí.
 */
import type React from 'react'
import type { AnimationSpec } from '../spec'
import { EXPLAINER, ExplainerBackground, ExplainerPipFrame } from './explainer'
import { MINIMAL, MinimalBackground, MinimalPipFrame } from './minimal'
import { TECH, TechBackground, TechPipFrame } from './tech'

type Part = React.FC<{ spec: AnimationSpec }>

export interface StyleModule {
  templates: Record<string, Part>
  Background: Part
  PipFrame: Part
}

export const STYLES: Record<string, StyleModule> = {
  motion_tech: { templates: TECH, Background: TechBackground, PipFrame: TechPipFrame },
  minimal_motion: { templates: MINIMAL, Background: MinimalBackground, PipFrame: MinimalPipFrame },
  creative_explainer: { templates: EXPLAINER, Background: ExplainerBackground, PipFrame: ExplainerPipFrame },
}
