# Arquitectura

```
Panel (React + Vite) ──HTTP solo 127.0.0.1 (cabecera anti-CSRF)──► API (FastAPI)
                                                                      │
                                      Cola de tareas locales (importar, analizar, planificar,
                                      animar, modificar escenas, exportar)
        ┌──────────────┬───────────────┬───────────────────┬──────────────┬─────────────┐
     FFmpeg/ffprobe  Whisper local   Claude (API del      Remotion +     Compositor
     (del usuario)   (MLX; Windows   usuario)             navegador de   FFmpeg
                     pendiente)      plan · dirección     render         (exportación
                                     · escenas            (ProRes alfa)  verificada)
        │
  SQLite (directorio de datos de la edición) ◄──► Almacenamiento elegido por el usuario
  proyectos · planes inmutables · versiones         originales · planes JSON · clips ·
  · consumo · copias de seguridad                    exportaciones
```

## Principios
- **Originales intocables:** se copian al almacenamiento y quedan registrados con su SHA-256.
- **Plan aprobado inmutable:** cada cambio crea una versión nueva, también al regenerar una escena.
- **Claude declara, el sistema valida:** esquemas cerrados, tiempos anclados a palabras y vocabulario de cada estilo. Nunca se ejecuta código generado.
- **Caché por contenido:** la huella incluye la especificación y el código del renderizador, así que nunca se reutiliza un clip obsoleto.
- **Mismo compositor** para la vista previa y la exportación.
- **Instalación independiente:** directorio de datos, puerto (8775) y servicio del llavero propios de esta edición (`app/edition.py`). No comparte nada con otras copias de Video Studio AI del mismo equipo.

## Estilos y extensiones
- **Estilos integrados:** los tres estilos gratuitos están registrados en `backend/app/styles/` y `renderer/src/styles/registry.ts`. Una prueba exige que las plantillas coincidan.
- **Paquetes de estilos adicionales:** se cargan **solo** si se indican de forma explícita en la variable `VSA_STYLE_PACKAGES` (módulos Python importables). El editor **nunca** explora carpetas ni descubre paquetes por su cuenta.
- **Parte visual de un paquete:** debe añadirse al registro del renderizador en la compilación de la edición que lo use.
- **Separación del núcleo:** un paquete externo puede mantenerse en otro repositorio, incluso privado, sin modificar el núcleo ni obligar a publicarlo.

## Plataforma
`backend/app/platform/` reúne lo que cambia entre sistemas:
- rutas de datos;
- procesos;
- motores de transcripción;
- codificadores por hardware;
- diagnóstico.

Ver [PLATFORMS.md](PLATFORMS.md).
