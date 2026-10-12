# Privacidad de la distribución

Este repositorio está pensado para publicarse. Para que una actualización no exponga datos personales hay tres barreras.

## 1. Lo que nunca entra en el repositorio
Están excluidos por `.gitignore` y además los bloquea la comprobación previa:
- **Contenido del usuario:** videos y audio, bases de datos, registros, copias de seguridad.
- **Descargas:** modelos y navegadores descargados.
- **Secretos:** archivos `.env`, claves y certificados.
- **Restos de compilación y prueba:** cachés, compilaciones e instaladores, resultados de pruebas.
- **Entorno local:** configuraciones del IDE y de agentes.

Los datos de cada usuario se crean en su primera ejecución, en su directorio de datos y en la carpeta de almacenamiento que elija.

## 2. Comprobación previa a cada commit
```bash
git config core.hooksPath .githooks         # una vez por clon
python3 scripts/privacy_check.py --all      # revisar todo el repositorio
python3 scripts/privacy_check.py --staged   # lo que va a confirmarse (lo hace el hook)
```
La comprobación bloquea:
- tipos de archivo de datos o medios y binarios no permitidos;
- rutas absolutas de usuario de macOS y Windows, y rutas de volúmenes externos;
- correos (salvo en los avisos de licencia de terceros);
- claves y tokens con forma conocida (Anthropic, GitHub, AWS, Hugging Face y claves privadas); las claves ficticias de las pruebas usan el prefijo reservado `sk-ant-test-`, que ninguna clave real tiene;
- **términos privados del mantenedor**, que se listan en `.privacy-terms.local`. Ese archivo no se versiona: así la propia lista de términos tampoco se publica.

Si `gitleaks` está instalado, se ejecuta además sobre lo preparado.

## 3. Antes de publicar
1. `python3 scripts/privacy_check.py --all` y `gitleaks git --redact .` sin hallazgos.
2. Revisar el autor de los commits: usar un correo de publicación, por ejemplo el `noreply` de GitHub, nunca uno personal.
3. Comprobar que no hay remotos inesperados (`git remote -v`) y que no se suben etiquetas ni ramas ajenas.
4. Elegir la licencia del código original (ver `docs/LICENSING.md`).
