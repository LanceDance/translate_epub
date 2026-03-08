# translate_epub.py

A command-line tool that translates EPUB books into any language using **Claude** (Anthropic) or **GPT-4.1** (OpenAI). It reads the whole book first to build a detailed translation style guide, then translates chapter by chapter with full context awareness.

---

## Features

- **Any target language** — pass any language name as an argument; the LLM handles it
- **Style guide** — reads the entire book before translating; builds a *Translation Blueprint* covering narrative voice, authorial fingerprints, characters with grammatical gender, places, recurring terminology, and cultural specifics
- **Dialogue detection** — paragraphs starting with `"`, `„`, `'`, `–`, `—` get a colloquial translation style; narration gets a literary one
- **Chapter summaries** — a brief summary of each chapter is generated and passed as context before translating it
- **Sentence continuity** — the last translated paragraph is passed as context to the next batch, preventing jarring transitions
- **Translation memory** — paragraphs that have already been translated (identical text) are cached and never sent to the API twice
- **Progress saving** — progress is saved after every chapter to `<epub>.<LANG>.progress.json`; can be interrupted and resumed at any time
- **`--proofread`** — optional second pass per chapter: fixes grammar, awkward phrasing, and inconsistent declension while preserving style
- **`--threadweave`** — after translation is complete, runs a full consistency audit across the whole book; automatically applies fixes (e.g. a character name that was translated two different ways); saves a JSON report
- **`--lore "World Name"`** — fetches lore data for known fantasy/sci-fi universes from their Fandom wiki via the MediaWiki API, builds a glossary (what to keep, what to translate, what to adapt), and injects it into every translation prompt

---

## Installation

```bash
pip install anthropic        # for Claude (default)
pip install openai           # for OpenAI (optional)
```

No other dependencies — uses only Python standard library.

---

## Usage

```
python translate_epub.py <epub> <api_key> <language> [options] [title] [author]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `epub` | yes | Path to the input EPUB file |
| `api_key` | yes | `sk-ant-...` for Anthropic, `sk-...` for OpenAI |
| `language` | yes | Target language (see below) |
| `title` | no | Override book title (read from metadata if omitted) |
| `author` | no | Override author name (read from metadata if omitted) |

**Options:**

| Flag | Description |
|---|---|
| `--provider openai` | Use OpenAI GPT-4.1 instead of Anthropic Claude |
| `--proofread` | Proofread each chapter after translation |
| `--threadweave` | Consistency audit + auto-fix after all chapters |
| `--lore "Name"` | Load lore glossary from Fandom wiki |

### Examples

```bash
# Basic translation to German
python translate_epub.py "book.epub" "sk-ant-api03-..." german

# French with proofreading
python translate_epub.py "book.epub" "sk-ant-api03-..." french --proofread

# Full pipeline: translate + proofread + consistency audit
python translate_epub.py "book.epub" "sk-ant-api03-..." czech --proofread --threadweave

# Fantasy book with lore glossary
python translate_epub.py "drizzt.epub" "sk-ant-api03-..." czech --lore "Forgotten Realms"

# Using OpenAI
python translate_epub.py "book.epub" "sk-openai-..." --provider openai spanish

# Override title and author
python translate_epub.py "book.epub" "sk-ant-..." german "My Book" "Author Name"

# Resume interrupted translation (just run again - progress is auto-detected)
python translate_epub.py "book.epub" "sk-ant-..." german
```

---

## Language support

Pass any language name as the third argument. Common ISO codes are also accepted:

| Language | Name | Code |
|---|---|---|
| Czech | `czech` | `cs` / `cz` |
| Slovak | `slovak` | `sk` |
| German | `german` | `de` |
| French | `french` | `fr` |
| Spanish | `spanish` | `es` |
| Italian | `italian` | `it` |
| Polish | `polish` | `pl` |
| Russian | `russian` | `ru` |
| Japanese | `japanese` | `jp` / `ja` |
| Dutch | `dutch` | `nl` |
| Portuguese | `portuguese` | `pt` |
| Romanian | `romanian` | `ro` |
| Hungarian | `hungarian` | `hu` |
| Swedish | `swedish` | `sv` |
| Turkish | `turkish` | `tr` |
| Korean | `korean` | `ko` |
| Chinese | `chinese` | `zh` |

Any other language name (e.g. `norwegian`, `hindi`, `catalan`) is passed directly to the LLM.

---

## Lore mode (`--lore`)

For books set in well-known fictional universes, the `--lore` flag fetches terminology from the universe's Fandom wiki and builds a glossary that tells the LLM exactly what to keep in the original language and what to translate.

```bash
python translate_epub.py "book.epub" "sk-ant-..." czech --lore "Forgotten Realms"
python translate_epub.py "book.epub" "sk-ant-..." czech --lore "Dragonlance"
```

**Supported universes** (fetched automatically):

| Universe | Wiki |
|---|---|
| Forgotten Realms | forgottenrealms.fandom.com |
| Dragonlance | dragonlance.fandom.com |
| Eberron | eberron.fandom.com |
| Wheel of Time | wot.fandom.com |
| Witcher | witcher.fandom.com |
| Stormlight / Cosmere | coppermind.net |
| Game of Thrones / ASOIAF | awoiaf.westeros.org |
| Star Wars | starwars.fandom.com |
| Lord of the Rings | lotr.fandom.com |
| Warhammer 40K | warhammer40k.fandom.com |
| Discworld | wiki.lspace.org |
| Ravenloft | ravenloft.fandom.com |
| Spelljammer | spelljammer.fandom.com |
| Greyhawk | greyhawk.fandom.com |

The glossary is cached in `<epub>.<LANG>.lore.json` — the wiki is only queried once per language.

To add a universe, edit the `LORE_WIKIS` dict in the script:
```python
LORE_WIKIS['my world'] = 'mywiki.fandom.com'
```

---

## Output files

| File | Description |
|---|---|
| `<epub>_<LANG>.epub` | Translated EPUB |
| `<epub>.<LANG>.progress.json` | Chapter-by-chapter progress (resume support) |
| `<epub>.<LANG>.index.json` | Style guide / character index (editable before translation) |
| `<epub>.<LANG>.memory.json` | Translation memory cache |
| `<epub>.<LANG>.lore.json` | Lore glossary (if `--lore` was used) |
| `<epub>.<LANG>.threadweave.json` | Consistency audit report (if `--threadweave` was used) |

The `_<LANG>` suffix is a 2-letter language code: `_CZ`, `_DE`, `_FR`, etc.

### Editing the style guide

After the style guide is built but before translation starts, you can interrupt with `Ctrl+C`, open `<epub>.<LANG>.index.json`, edit the `index` field, and restart. Your edits will be used for all subsequent translation.

---

## EPUB compatibility

Tested with:
- Standard EPUB 2 / EPUB 3
- Kobo DRM-free EPUBs (handles self-closing `<script/>` tags that break standard HTML parsers)
- Non-standard NCX filenames (e.g. `9780593833506_ncx.ncx`)
- Chapter filenames with numeric prefixes (`09_Chapter_1.xhtml`)

Frontmatter and backmatter (cover, copyright, dedication, acknowledgements, TOC, etc.) are automatically skipped.

---

## Cost estimates (Claude Sonnet 4.6)

| Book size | Approximate cost |
|---|---|
| Short novel (~1,500 paragraphs) | ~$1.30 |
| Standard novel (~3,000 paragraphs) | ~$2.50 |
| Long novel (~5,000 paragraphs) | ~$4.00 |

Add ~30% for `--proofread`, ~10% for `--threadweave`.

*Prices based on $3/M input tokens, $15/M output tokens (Claude Sonnet 4.6, March 2026).*

---

## Rate limits

The script is designed to stay within Anthropic's free-tier rate limit of **30,000 tokens/minute**:
- 4-second pause between batches
- 65-second pause between the three style-guide analysis passes
- Automatic retry with backoff on HTTP 429

---

## License

MIT
