# translate_epub.py — AI-powered EPUB book translator

**Translate any EPUB ebook to any language** using Claude (Anthropic) or GPT-4.1 (OpenAI) — a single Python script with no dependencies beyond the API client.

Translate English novels to German, French, Czech, Spanish, Japanese, or any other language. The script reads the entire book first, builds a detailed style guide, then translates chapter by chapter with full context awareness — producing literary-quality output rather than word-for-word machine translation.

```bash
pip install anthropic
python translate_epub.py "book.epub" "sk-ant-api03-..." german
```

> **Translate EPUB to German · French · Czech · Spanish · Italian · Polish · Japanese · Dutch · Portuguese** and [30+ other languages](#language-support).

---

## Why this tool?

Most AI translation tools send text paragraph by paragraph with no context. This script works the way a professional translator would:

1. **Reads the whole book first** — builds a *Translation Blueprint* covering narrative voice, authorial fingerprints, all characters with grammatical gender, places, recurring terminology, cultural specifics
2. **Translates with context** — each batch gets the style guide + a chapter summary + the previously translated paragraph
3. **Handles dialogue and narration differently** — dialogue gets a colloquial style, narration gets a literary style
4. **Audits consistency** — `--threadweave` scans the finished translation for inconsistencies (e.g. a character name translated two different ways) and auto-fixes them
5. **Supports fantasy/sci-fi lore** — `--lore "Forgotten Realms"` fetches established terminology from Fandom wikis so Drizzt stays Drizzt and Baldur's Gate gets its official translated name

---

## Features

- **Any target language** — pass any language name; the LLM handles it
- **Translation Blueprint** — full-book style guide: narrative voice, authorial fingerprints, characters with grammatical gender, places, recurring terminology, cultural specifics
- **Dialogue detection** — paragraphs starting with `"`, `„`, `'`, `–`, `—` get a colloquial translation style; narration gets a literary one
- **Chapter summaries** — a brief summary is generated and injected as context before each chapter
- **Sentence continuity** — the last translated paragraph is passed as context to the next batch
- **Translation memory** — identical paragraphs are cached and never translated twice
- **Resumable** — progress is saved after every chapter; re-run the same command to continue
- **`--proofread`** — second pass per chapter: fixes grammar, awkward phrasing, inconsistent declension
- **`--threadweave`** — full-book consistency audit with automatic fix application
- **`--lore "World Name"`** — fetches lore glossary from Fandom wiki for fantasy/sci-fi universes

---

## Installation

```bash
pip install anthropic        # for Claude (default)
pip install openai           # for OpenAI (optional)
```

No other dependencies — uses only the Python standard library.

---

## Usage

```
python translate_epub.py <epub> <api_key> <language> [options] [title] [author]
```

| Argument | Required | Description |
|---|---|---|
| `epub` | ✓ | Path to the input EPUB file |
| `api_key` | ✓ | `sk-ant-...` for Anthropic, `sk-...` for OpenAI |
| `language` | ✓ | Target language name or ISO code |
| `title` | — | Override book title (read from EPUB metadata if omitted) |
| `author` | — | Override author name (read from EPUB metadata if omitted) |

| Option | Description |
|---|---|
| `--provider openai` | Use OpenAI GPT-4.1 instead of Claude |
| `--proofread` | Proofread each chapter after translation |
| `--threadweave` | Consistency audit + auto-fix after all chapters |
| `--lore "Name"` | Load lore glossary from Fandom wiki |

### Examples

```bash
# Translate EPUB to German
python translate_epub.py "book.epub" "sk-ant-api03-..." german

# Translate to French with proofreading
python translate_epub.py "book.epub" "sk-ant-api03-..." french --proofread

# Full pipeline: translate + proofread + consistency audit
python translate_epub.py "book.epub" "sk-ant-api03-..." czech --proofread --threadweave

# Translate a Forgotten Realms novel — keeps Drizzt, translates dwarf, adapts place names
python translate_epub.py "drizzt.epub" "sk-ant-api03-..." czech --lore "Forgotten Realms"

# Use OpenAI instead of Claude
python translate_epub.py "book.epub" "sk-openai-..." --provider openai spanish

# Resume an interrupted translation (just run the same command again)
python translate_epub.py "book.epub" "sk-ant-..." german
```

---

## Language support

Any language name works — it is passed directly to the LLM. ISO codes are also accepted:

| Language | Argument | ISO code |
|---|---|---|
| Czech | `czech` | `cs` |
| Slovak | `slovak` | `sk` |
| German | `german` | `de` |
| French | `french` | `fr` |
| Spanish | `spanish` | `es` |
| Italian | `italian` | `it` |
| Polish | `polish` | `pl` |
| Russian | `russian` | `ru` |
| Japanese | `japanese` | `ja` |
| Dutch | `dutch` | `nl` |
| Portuguese | `portuguese` | `pt` |
| Romanian | `romanian` | `ro` |
| Hungarian | `hungarian` | `hu` |
| Swedish | `swedish` | `sv` |
| Norwegian | `norwegian` | `no` |
| Finnish | `finnish` | `fi` |
| Danish | `danish` | `da` |
| Turkish | `turkish` | `tr` |
| Korean | `korean` | `ko` |
| Chinese | `chinese` | `zh` |
| Arabic | `arabic` | `ar` |

Any other name (e.g. `catalan`, `hindi`, `ukrainian`) is passed through directly.

---

## Lore mode — translate fantasy and sci-fi books correctly

When translating books set in well-known fictional universes, the `--lore` flag fetches established terminology from the universe's Fandom wiki. It tells the LLM exactly what to keep untranslated (character names, unique proper nouns) and what to translate or adapt (races, titles, place names with official translations).

```bash
# Translate a D&D / Forgotten Realms novel
python translate_epub.py "book.epub" "sk-ant-..." czech --lore "Forgotten Realms"

# Translate a Dragonlance novel
python translate_epub.py "book.epub" "sk-ant-..." czech --lore "Dragonlance"

# Translate a Witcher book
python translate_epub.py "book.epub" "sk-ant-..." german --lore "Witcher"
```

**Supported universes:**

| Universe | Source wiki |
|---|---|
| Forgotten Realms (D&D) | forgottenrealms.fandom.com |
| Dragonlance | dragonlance.fandom.com |
| Eberron | eberron.fandom.com |
| Wheel of Time | wot.fandom.com |
| The Witcher | witcher.fandom.com |
| Stormlight Archive / Cosmere | coppermind.net |
| Game of Thrones / ASOIAF | awoiaf.westeros.org |
| Star Wars | starwars.fandom.com |
| Lord of the Rings | lotr.fandom.com |
| Warhammer 40,000 | warhammer40k.fandom.com |
| Discworld | wiki.lspace.org |
| Ravenloft | ravenloft.fandom.com |
| Spelljammer | spelljammer.fandom.com |
| Greyhawk | greyhawk.fandom.com |

The glossary is cached locally after the first run. To add any other universe:

```python
# Edit LORE_WIKIS in the script
LORE_WIKIS['my world'] = 'mywiki.fandom.com'
```

---

## How the translation pipeline works

```
EPUB input
    │
    ▼
[1] Parse chapters — skip frontmatter/backmatter (cover, TOC, copyright...)
    │
    ▼
[2] Build Translation Blueprint
    ├── Read book in 3 sections (rate-limit safe)
    ├── Extract: characters + gender, places, terminology, cultural specifics
    └── Synthesise into style guide (narrative voice, authorial fingerprints, ...)
    │
    ▼  (optional)
[3] Fetch lore glossary from Fandom wiki  ──── --lore flag
    │
    ▼
[4] Translate chapter by chapter
    ├── Generate chapter summary (context)
    ├── Detect dialogue vs narration (different prompt style)
    ├── Translate in batches of 25 paragraphs
    ├── Pass previous paragraph for continuity
    └── Save progress after each chapter
    │
    ▼  (optional)
[5] Proofread each chapter  ──────────────── --proofread flag
    │
    ▼  (optional)
[6] Threadweaver consistency audit  ──────── --threadweave flag
    ├── Build consistency map across full translated text
    ├── Generate JSON fix list
    └── Auto-apply fixes to all chapters
    │
    ▼
EPUB output
```

---

## Output files

| File | Description |
|---|---|
| `<epub>_<LANG>.epub` | Translated EPUB, ready to read |
| `<epub>.<LANG>.progress.json` | Per-chapter progress (enables resume) |
| `<epub>.<LANG>.index.json` | Translation Blueprint / style guide |
| `<epub>.<LANG>.memory.json` | Translation memory cache |
| `<epub>.<LANG>.lore.json` | Lore glossary (`--lore` only) |
| `<epub>.<LANG>.threadweave.json` | Consistency audit report (`--threadweave` only) |

The language suffix is a 2-letter code: `_DE`, `_FR`, `_CZ`, `_JA`, etc.

**Tip:** After the style guide is built you can press `Ctrl+C`, open `<epub>.<LANG>.index.json`, edit the `index` field, and restart. Your changes apply to all subsequent translation.

---

## EPUB compatibility

- Standard EPUB 2 / EPUB 3
- Kobo DRM-free EPUBs (handles self-closing `<script/>` tags that break standard HTML parsers)
- Non-standard NCX filenames (e.g. `9780593833506_ncx.ncx`)
- Chapter filenames with numeric prefixes (`09_Chapter_1.xhtml`)

Frontmatter and backmatter are detected and skipped automatically: cover, title page, copyright, table of contents, dedication, acknowledgements, author bio, and more.

---

## Cost estimates

Using **Claude Sonnet 4.6** ($3/M input · $15/M output):

| Book | Paragraphs | Base | + proofread | + threadweave |
|---|---|---|---|---|
| Short novel | ~1,500 | ~$1.30 | ~$1.70 | ~$1.85 |
| Standard novel | ~3,000 | ~$2.50 | ~$3.25 | ~$3.50 |
| Long novel | ~5,000 | ~$4.00 | ~$5.20 | ~$5.60 |

*Prices as of March 2026. OpenAI GPT-4.1 pricing differs — check current rates.*

---

## Rate limits

Designed to stay within Anthropic's **30,000 tokens/minute** free-tier limit:
- 4-second pause between translation batches
- 65-second pause between the three style-guide analysis passes
- Automatic retry with exponential backoff on HTTP 429

---

## License

MIT
