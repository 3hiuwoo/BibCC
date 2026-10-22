# 📚 BibTeX Check & Complete (BibCC)

Un conjunto de herramientas de CLI para autocompletar campos de BibTeX faltantes, verificar la calidad del formato, gestionar plantillas reutilizables y alinear su biblioteca de PDFs con su bibliografía.

> 👋 ¡Gracias por su atención!
>
> Originalmente, esta es una herramienta pequeña optimizada para mi propio flujo de trabajo de recolección de bibliografía. Me alegra ver que el proyecto ha recibido algunas estrellas. Volveré a trabajar en BibCC lo antes posible para hacerlo más universal, versátil y robusto. Espero que pueda ayudar a cualquiera que tenga las mismas necesidades que yo.

## 🚀 Inicio Rápido

```bash
pip install bibtexparser pyyaml
python bibcc.py --help
```

## 🧩 Comandos

BibCC proporciona cinco comandos a través de un único punto de entrada — `bibcc.py`:

| Comando | Descripción |
| --- | --- |
| `check` | Verificaciones de calidad: campos faltantes, mayúsculas en títulos (title case), protección de términos, claves de citación |
| `complete` | Autocompletar campos de BibTeX faltantes a partir de plantillas |
| `librarian` | Alinear la biblioteca de PDF con el archivo `.bib`: faltantes / extra / renombrar |
| `scholar` | Recuentos de citaciones y verificación de títulos mediante APIs externas |
| `compose` | Fusionar archivos `.bib` por carpetas en una sola bibliografía |

Ejecute `python bibcc.py <comando> -h` para obtener ayuda específica de cada comando.

---

### `check` — Verificaciones de Calidad

Ejecute una o más verificaciones de calidad en un archivo `.bib`. Todas las verificaciones son independientes y pueden combinarse en una sola ejecución.

**Campos faltantes** — detecta entradas que carecen de campos obligatorios:

```bash
python bibcc.py check input.bib --fields month
python bibcc.py check input.bib --fields month,publisher --entry-types inproceedings,article
```

**Mayúsculas en títulos (Title case)** — sugiere correcciones de mayúsculas en el título al estilo APA:

```bash
python bibcc.py check input.bib --title-case
python bibcc.py check input.bib --title-case --title-apply          # aplica los cambios directamente
python bibcc.py check input.bib --title-case --title-interactive    # revisar cada sugerencia
```

**Protección inteligente de términos** — sugiere `{llaves}` para términos técnicos, acrónimos y nombres propios:

```bash
python bibcc.py check input.bib --quote
python bibcc.py check input.bib --quote --quote-terms Gaussian,BERT
python bibcc.py check input.bib --quote --quote-vocab-file my_terms.txt
```

**Legibilidad de la clave de citación** — verifica que las claves sigan el formato `METHOD_AUTHOR_VENUEYEAR`:

```bash
python bibcc.py check input.bib --check-keys
```

**Integridad de plantillas** — verifica en `templates.py` si faltan campos:

```bash
python bibcc.py check --check-templates
python bibcc.py check --check-templates --journal-fields publisher,issn --proceedings-fields venue,month,isbn
```

**Combinar verificaciones** en una sola ejecución:

```bash
python bibcc.py check input.bib --fields month --title-case --quote --check-keys
```

<details>
<summary>Todas las opciones de <code>check</code></summary>

| Opción | Descripción |
| --- | --- |
| `--fields FIELDS` | Campos obligatorios separados por comas (predeterminado: `month`) |
| `--entry-types TYPES` | Tipos de entrada a verificar separados por comas (predeterminado: `inproceedings,article,proceedings,conference`) |
| `--title-case` | Verificar mayúsculas en el título (estilo APA) |
| `--title-apply` | Aplicar cambios de title case directamente (implica `--title-case`) |
| `--title-interactive` | Revisión interactiva por sugerencia (implica `--title-case`) |
| `--title-style STYLE` | Estilo de title case (predeterminado: `apa`) |
| `--extra-stopwords WORDS` | Palabras clave adicionales para mantener en minúsculas |
| `--quote` | Ejecutar protección inteligente de términos |
| `--quote-terms TERMS` | Términos adicionales a proteger |
| `--quote-vocab-file FILE` | Archivo de vocabulario delimitado por saltos de línea |
| `--quote-no-default` | Desactivar vocabulario técnico integrado |
| `--protection-min-length N` | Longitud mínima de palabra para detección de acrónimos (predeterminado: `3`) |
| `--check-keys` | Verificar legibilidad de las claves de citación |
| `--check-templates` | Verificar plantillas en busca de campos faltantes |
| `--journal-fields FIELDS` | Campos a verificar en plantillas de revistas (predeterminado: `publisher,issn`) |
| `--proceedings-fields FIELDS` | Campos a verificar en plantillas de actas (predeterminado: `venue,publisher,month`) |

</details>

---

### `complete` — Autocompletar Campos Faltantes

Rellena campos de BibTeX faltantes (editor, ISSN, sede, mes, …) a partir de una base de datos de plantillas integrada.

```bash
python bibcc.py complete input.bib                    # previsualización (dry-run)
python bibcc.py complete input.bib --output out.bib   # escribir salida completada
```

Cuando faltan plantillas, se genera un archivo `*.missing_templates.yaml`. Los campos se **deducen automáticamente** a partir de los patrones de nombre de la sede y se **pre-rellenan** a partir de entradas existentes en la misma revista/conferencia, por lo que solo necesita completar lo que no se pudo inferir.

**Flujo de trabajo en un paso** — generar YAML, actualizar plantillas y volver a completar:

```bash
# 1. Ejecutar para generar el YAML (campos deducidos pre-rellenados)
python bibcc.py complete input.bib

# 2. Rellenar los campos restantes en input.bib.missing_templates.yaml

# 3. Actualizar plantillas y volver a completar en un solo paso
python bibcc.py complete input.bib --output out.bib --update-templates
```

<details>
<summary>Todas las opciones de <code>complete</code></summary>

| Opción | Descripción |
| --- | --- |
| `--output FILE` | Ruta para guardar el archivo `.bib` mejorado (omitir para dry-run) |
| `--log-dir DIR` | Directorio para escribir logs (predeterminado: directorio actual) |
| `--update-templates` | Invocar `yaml2templates` en el YAML generado y luego ejecutar la completación nuevamente |

</details>

---

### `librarian` — Alineación de Biblioteca PDF

Alinea tu biblioteca de PDF con tu bibliografía. Tres subcomandos:

```bash
# Encontrar entradas de bib cuyos PDFs faltan en tu biblioteca
python bibcc.py librarian missing input.bib papers.txt

# Encontrar PDFs en la biblioteca que no están referenciados en el bib
python bibcc.py librarian extra input.bib papers.txt

# Renombrar PDFs según los nombres de las claves de citación mediante coincidencia de títulos
python bibcc.py librarian rename input.bib ~/Downloads/papers --dry-run   # previsualización
python bibcc.py librarian rename input.bib ~/Downloads/papers             # aplicar
```

**Flujo de renombrado**: Exporta los PDFs desde Zotero (o similar) con los títulos completos en el nombre del archivo (ej., `Autor et al - 2025 - Título Completo del Artículo.pdf`). La herramienta extrae los títulos de los nombres de archivo, los normaliza y los coteja con las entradas de bib para un renombrado exacto; no se requiere orden manual.

---

### `scholar` — Citaciones y Verificación de Títulos

Dos subcomandos para la gestión de bibliografías basada en la web.

**`cite`** — URLs de citaciones de Google Scholar y relleno interactivo de citaciones:

```bash
python bibcc.py scholar cite input.bib                         # dry-run: mostrar URLs
python bibcc.py scholar cite input.bib -i                      # interactivo: rellenar recuentos
python bibcc.py scholar cite input.bib --open --batch-size 10  # abrir en lote en el navegador
python bibcc.py scholar cite input.bib -i --include-filled     # volver a verificar entradas ya rellenadas
```

**`titles`** — Verificar títulos de artículos contra CrossRef, DBLP, Semantic Scholar, arXiv:

```bash
python bibcc.py scholar titles input.bib
python bibcc.py scholar titles input.bib --retry-errors report.txt  # reintentar fallos
python bibcc.py scholar titles input.bib --ids ID1,ID2              # entradas específicas
```

<details>
<summary>Todas las opciones de <code>scholar</code></summary>

**cite:**

| Opción | Descripción |
| --- | --- |
| `--interactive`, `-i` | Relleno interactivo de citaciones (recomendado) |
| `--open` | Abrir URLs en lote en el navegador |
| `--batch-size N` | URLs por lote (predeterminado: `5`) |
| `--include-filled` | Incluir entradas que ya tienen valores de citación |
| `--output`, `-o FILE` | Archivo de salida (omitir para dry-run) |

**titles:**

| Opción | Descripción |
| --- | --- |
| `--delay`, `-d SECS` | Retraso en las solicitudes a la API (predeterminado: `0.5`) |
| `--quiet`, `-q` | Suprimir la salida de progreso |
| `--retry-errors REPORT` | Volver a verificar solo las entradas con error de un reporte previo |
| `--ids IDS` | IDs de entrada separados por comas para verificar |

</details>

---

### `compose` — Fusionar Archivos `.bib`

Combina archivos `.bib` de un árbol de carpetas en una sola bibliografía:

```bash
python bibcc.py compose compose ./my-bibs combined.bib
python bibcc.py compose compose ./my-bibs combined.bib --no-dup-warning
```

Se insertan marcadores de ruta de origen (`% === source: path/file.bib ===`) entre los archivos. Todos los comentarios originales se preservan. Por defecto, se advierte sobre los IDs de entrada duplicados.

---

## 📂 Archivos de Salida

Todos los archivos de salida se generan automáticamente junto al archivo `.bib` de entrada. Los logs van a `logs/`.

| Comando | Archivos de Reporte | Archivos de Log |
| --- | --- | --- |
| `check` | `.missing_fields.txt`, `.title_case.txt`, `.smart_protection.txt`, `.citation_keys.txt` | `logs/*.checker.log` |
| `complete` | `.missing_templates.yaml`, `.missing_templates.txt`, `.conflicts.txt`, `.incomplete_entries.txt` | `logs/*.completer.log` |
| `scholar cite` | `.scholar_urls.txt` | `logs/*.scholar.cite.log` |
| `scholar titles` | `.title_report.txt` | `logs/*.scholar.titles.log` |
| `librarian` | `.missing_pdfs.txt`, `.extra_pdfs.txt`, `.rename_report.txt` | `logs/*.librarian.log` |
| `compose` | (archivo `.bib` compuesto) | `logs/*.composer.log` |

## 🗂️ Sistema de Plantillas

Las plantillas impulsan el comando `complete`. Residen en `templates.py` como dos diccionarios:

- **`JOURNAL_TEMPLATES`** — Indexado por nombre de la revista (independiente del año, ya que las revistas tienen metadatos consistentes)
- **`PROCEEDINGS_TEMPLATES`** — Indexado por una tupla `(nombre_de_la_sede, año)` (las conferencias varían según el año)

### Añadir Nuevas Plantillas

```bash
# 1. Ejecutar complete para generar el YAML de sedes desconocidas
python bibcc.py complete input.bib

# 2. Editar el archivo generado *.missing_templates.yaml — la mayoría de los campos están pre-rellenados

# 3. Actualizar plantillas y completar en un solo paso
python bibcc.py complete input.bib --output out.bib --update-templates
```

Las entradas que carecen de año o sede (ej., preprints de arXiv, entradas misceláneas) se reportan en `*.incomplete_entries.txt` y se omiten.

## 🔗 Recursos Adicionales

No se garantiza que el archivo `.bib` modificado esté perfectamente formateado. Utilice:

- [**BibTeX Tidy**](https://flamingtempura.github.io/bibtex-tidy/) para el formateo final
- La extensión LaTeX Workshop de VS Code para una mejor alineación

## 📋 TODO

- `complete` y plantillas:
  - [x] ~~Integrar el completador con `yaml2templates` para un flujo de gestión de plantillas unificado.~~ Hecho — bandera `--update-templates`.
  - [x] ~~Deducir automáticamente campos a partir de nombres de revistas/conferencias (editor, issn, mes).~~ Hecho — marcadores `# auto-guessed` en YAML.
  - [x] ~~Pre-rellenar YAML a partir de bibliografías existentes en la misma sede.~~ Hecho — campos recolectados de entradas bib.
- `check`:
  - [x] ~~Verificación de legibilidad de claves de citación.~~ Hecho — `--check-keys`.
  - [x] ~~Verificación de campos faltantes específicos de la plantilla.~~ Hecho — `--check-templates`.
  - [x] ~~Protección robusta de términos (omitir números, filtrar nombres de autores).~~ Hecho — `--quote` con filtrado inteligente.
  - [x] ~~Title case robusto (palabras con guion, estilo configurable).~~ Hecho — `--title-case` con manejo de APA.
  - [x] ~~Aplicación interactiva de title case.~~ Hecho — `--title-interactive`.
  - [x] ~~Arquitectura de sub-verificadores modular.~~ Hecho — paquete `checkers/`.
- `librarian`:
  - [x] ~~Alineación unificada de biblioteca PDF (faltantes/extra/renombrar).~~ Hecho.
- `scholar`:
  - [x] ~~Herramienta unificada de citaciones + títulos.~~ Hecho — subcomandos `cite` y `titles`.
- `compose`:
  - [x] ~~Composición de .bib basada en carpetas con preservación de comentarios.~~ Hecho.
- CLI y salida:
  - [x] ~~Punto de entrada CLI unificado.~~ Hecho — `bibcc.py`.
  - [x] ~~Formateo de salida y registro consistente.~~ Hecho — constantes de formato compartido y escritor de reportes.
  - [ ] Refinar y empaquetar el repo como una herramienta de línea de comandos instalable con solo bibcc y plantillas expuestas.
