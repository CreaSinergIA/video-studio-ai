import { loadFont } from '@remotion/fonts'
import { staticFile } from 'remotion'

/**
 * Tipografías locales (OFL, las mismas TTF que usa el backend para los subtítulos).
 * `loadFont` bloquea el render hasta que la fuente está lista (sin parpadeos).
 */
const FONTS: { family: string; file: string; weight: string }[] = [
  { family: 'VSA Inter', file: 'Inter-Variable.ttf', weight: '100 900' },
  { family: 'VSA Montserrat', file: 'Montserrat-Variable.ttf', weight: '100 900' },
  { family: 'VSA Mono', file: 'JetBrainsMono-Variable.ttf', weight: '100 800' },
  { family: 'VSA Caveat', file: 'Caveat-Variable.ttf', weight: '400 700' },
  { family: 'VSA Poppins', file: 'Poppins-Medium.ttf', weight: '500' },
  { family: 'VSA Poppins', file: 'Poppins-SemiBold.ttf', weight: '600' },
  { family: 'VSA Poppins', file: 'Poppins-Bold.ttf', weight: '700' },
  { family: 'VSA Poppins', file: 'Poppins-ExtraBold.ttf', weight: '800' },
  { family: 'VSA Bebas', file: 'BebasNeue-Regular.ttf', weight: '400' },
]

let loaded: Promise<unknown> | null = null

export function ensureFonts() {
  if (!loaded) {
    loaded = Promise.all(
      FONTS.map((f) =>
        loadFont({ family: f.family, url: staticFile(`fonts/${f.file}`), weight: f.weight, format: 'truetype' }),
      ),
    )
  }
  return loaded
}
