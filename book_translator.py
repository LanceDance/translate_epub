#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB translator to any language using Claude AI (or OpenAI)
Pouziti:
  1. Install:   pip install anthropic
  2. Run:        python translate_epub.py <epub> <api_key> [options] [language] [title] [author]

  Options:
    --provider openai   use OpenAI instead of Anthropic
    --proofread         run a proofreading pass after each chapter
    --threadweave       consistency audit across the whole translated book
    --lore "Name"       fetch lore data from fandom wiki (Forgotten Realms, Dragonlance...)

  Examples:
  python translate_epub.py "book.epub" "sk-ant-api03-..."
  python translate_epub.py "book.epub" "sk-ant-api03-..." --proofread
  python translate_epub.py "book.epub" "sk-ant-api03-..." --proofread --threadweave
  python translate_epub.py "book.epub" "sk-ant-api03-..." german
  python translate_epub.py "book.epub" "sk-ant-api03-..." --lore "Forgotten Realms"
  python translate_epub.py "book.epub" "sk-ant-api03-..." --lore "Dragonlance" --proofread
  python translate_epub.py "book.epub" "sk-ant-api03-..." slovak "Title" "Author"

  Language (3rd argument, required):
    czech, slovak, german, french, spanish,
    italian, polish, russian, japanese, dutch, portuguese, ...
    or any other language name - passed directly to the LLM

  If title and author are not provided, they are read from EPUB metadata.

Progress is saved to <epub>.progress.json - can be interrupted and resumed.
"""

import sys, os, json, time, zipfile, io, struct, zlib, re
from html.parser import HTMLParser


# ================================================================
#  LLM WRAPPER - supports Anthropic and OpenAI
# ================================================================

def call_llm(client, provider, prompt, max_tokens):
    if provider == 'openai':
        resp = client.chat.completions.create(
            model='gpt-4.1',
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return resp.choices[0].message.content
    else:
        msg = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return msg.content[0].text


# ================================================================
#  TRANSLATION MEMORY (cache)
# ================================================================

import hashlib

def load_memory(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_memory(memory, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def hash_text(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


# ================================================================
#  EPUB PARSER
# ================================================================

class ParaExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paras = []
        self._tag = None
        self._buf = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip = True
        elif tag in ('p', 'h1', 'h2', 'h3', 'h4'):
            self._tag = tag
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip = False
        elif tag in ('p', 'h1', 'h2', 'h3', 'h4') and self._tag:
            text = ''.join(self._buf).strip()
            if text and 'OceanofPDF' not in text:
                self.paras.append({'tag': tag, 'text': text})
            self._tag = None
            self._buf = []

    def handle_data(self, data):
        if not self._skip and self._tag:
            self._buf.append(data)


def extract_paras(xhtml, book_title=''):
    # Kobo self-closing <script .../> breaks HTML5 parser - remove first
    cleaned = re.sub(r'<script[^>]*/>', '', xhtml, flags=re.IGNORECASE)
    cleaned = re.sub(r'<style[^>]*/>', '', cleaned, flags=re.IGNORECASE)
    p = ParaExtractor()
    p.feed(cleaned)
    # Filter out book title header that appears on every page in some epubs
    if book_title:
        return [x for x in p.paras if x['text'] != book_title]
    return p.paras



def is_dialogue(text):
    """Detect whether a paragraph is dialogue - use a different translation style."""
    return text.startswith(('"', '„', '“', '‘', "– ", "— ", "- "))


def read_opf_metadata(files):
    """Read title and author from OPF package file."""
    title, author = '', ''
    for name, data in files.items():
        if name.endswith('.opf'):
            text = data.decode('utf-8', errors='replace')
            m = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', text)
            if m:
                title = m.group(1).strip()
            m = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', text)
            if m:
                author = m.group(1).strip()
            break
    return title, author


def load_epub(path, book_title=''):
    z = zipfile.ZipFile(path)
    files = {}
    for name in z.namelist():
        files[name] = z.read(name)

    # Find NCX/NAV file - can have any name
    toc = ''
    for candidate in ['OEBPS/toc.ncx', 'OEBPS/nav.xhtml', 'OEBPS/toc.xhtml']:
        if candidate in files:
            toc = files[candidate].decode('utf-8', errors='replace')
            break
    if not toc:
        # Search for anything ending in .ncx or nav.xhtml
        for name in files:
            if name.endswith('.ncx') or name.endswith('nav.xhtml'):
                toc = files[name].decode('utf-8', errors='replace')
                break

    # Names to skip (frontmatter/backmatter)
    SKIP_KEYWORDS = {
        'cover', 'title', 'copyright', 'contents', 'dedication', 'ded',
        'ack', 'acknowledgement', 'acknowledgment', 'adcard', 'about',
        'author', 'nav', 'toc', 'epigraph', 'next-reads', 'torad', 'ata',
        'copyrightnotice', 'backmatter', 'frontmatter', 'halftitle',
        'also', 'newsletter', 'bonus'
    }
    seen = set()
    chapters = []

    for m in re.finditer(r'content src="(?:xhtml/)?([\w/. -]+\.xhtml)"', toc):
        fname = m.group(1).strip()
        basename = os.path.basename(fname)
        slug_check = re.sub(r'^\d+_', '', basename).replace('.xhtml', '').lower()

        # Skip frontmatter/backmatter by keyword
        if any(kw in slug_check for kw in SKIP_KEYWORDS):
            continue
        if fname in seen:
            continue
        seen.add(fname)

        # Search for the file in various epub locations
        key = 'OEBPS/xhtml/' + basename
        if key not in files:
            key = 'OEBPS/' + fname
        if key not in files:
            # Try to find the file by basename anywhere
            matches = [k for k in files if k.endswith('/' + basename)]
            if matches:
                key = matches[0]
            else:
                continue

        xhtml = files[key].decode('utf-8', errors='replace')
        paras = extract_paras(xhtml, book_title)
        if not paras:
            continue

        slug = basename.replace('.xhtml', '')
        # Try to detect chapter label from first heading paragraph
        label = None
        for p in paras[:3]:
            if p['tag'] in ('h1','h2','h3') or (p['tag'] == 'p' and len(p['text']) < 40):
                candidate = p['text'].upper()
                if re.match(r'^(CHAPTER|PROLOGUE|EPILOGUE|PROLOG|PART|\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)', candidate):
                    label = p['text']
                    break
        if not label:
            if 'prologue' in slug:    label = 'Prologue'
            elif 'epilogue' in slug:  label = 'Epilogue'
            elif re.search(r'\d+', slug):
                num = re.search(r'\d+', slug).group()
                label = 'Chapter ' + num
            else:
                label = slug.capitalize()

        chapters.append({'slug': slug, 'label': label, 'file_key': key, 'paras': paras})

    return files, chapters


# ================================================================
#  ZIP / EPUB BUILDER
# ================================================================

def crc32b(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def write_zip(file_list):
    buf = io.BytesIO()
    cd = []
    for name, data in file_list:
        nb = name.encode('utf-8')
        offset = buf.tell()
        crc = crc32b(data)
        buf.write(struct.pack('<IHHHHHIIIHH',
            0x04034b50, 20, 0, 0, 0, 0,
            crc, len(data), len(data), len(nb), 0))
        buf.write(nb)
        buf.write(data)
        cd.append((nb, crc, len(data), offset))

    cd_offset = buf.tell()
    for nb, crc, sz, offset in cd:
        buf.write(struct.pack('<IHHHHHHIIIHHHHHII',
            0x02014b50, 20, 20, 0, 0, 0, 0,
            crc, sz, sz, len(nb), 0, 0, 0, 0, 0, offset))
        buf.write(nb)

    cd_size = buf.tell() - cd_offset
    buf.write(struct.pack('<IHHHHIIH',
        0x06054b50, 0, 0, len(cd), len(cd), cd_size, cd_offset, 0))
    return buf.getvalue()


def make_xhtml(label, paras, czech_title):
    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    body = '\n'.join('    <' + p['tag'] + '>' + esc(p['text']) + '</' + p['tag'] + '>'
                     for p in paras)
    return ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
            '<head><title>' + esc(czech_title) + ' - ' + esc(label) + '</title>\n'
            '<meta http-equiv="default-style" content="text/html; charset=utf-8"/>\n'
            '<link rel="stylesheet" type="text/css" href="../styles/stylesheet.css"/></head>\n'
            '<body>\n' + body + '\n</body></html>')


def build_epub(orig_files, translated_chapters, czech_title):
    replaced = set()
    for ch in translated_chapters:
        replaced.add(ch['file_key'])

    file_list = [('mimetype', b'application/epub+zip')]
    for name, data in orig_files.items():
        if name != 'mimetype' and name not in replaced:
            file_list.append((name, data))

    for ch in translated_chapters:
        xhtml = make_xhtml(ch['label'], ch['paras'], czech_title)
        file_list.append((ch['file_key'], xhtml.encode('utf-8')))

    return write_zip(file_list)


# ================================================================
#  STEP 1: CHARACTER INDEXING & STYLE GUIDE
# ================================================================

def get_book_sample(chapters, max_chars=80000):
    """Uniform sample from the whole book - beginning, middle, end.
    Limited to 80k chars (~25k tokens) to stay within rate limits."""
    all_paras = [p['text'] for ch in chapters for p in ch['paras']]
    n = len(all_paras)
    sample = (
        all_paras[:int(n * 0.35)] +
        all_paras[int(n * 0.45):int(n * 0.70)] +
        all_paras[int(n * 0.82):]
    )
    return '\n'.join(sample)[:max_chars]


def build_character_index(client, provider, chapters, book_title, author, target_lang='cestina'):
    total = sum(len(ch['paras']) for ch in chapters)
    print('(Reading book to build style guide - ' + str(total) + ' paragraphs...)')

    # Split indexing into 3 parts to stay within the 30k token/min rate limit
    all_paras = [p['text'] for ch in chapters for p in ch['paras']]
    n = len(all_paras)

    sections = [
        ('BEGINNING', all_paras[:int(n * 0.33)]),
        ('MIDDLE',    all_paras[int(n * 0.33):int(n * 0.66)]),
        ('END',       all_paras[int(n * 0.66):]),
    ]

    partial_results = []
    for i, (label, paras) in enumerate(sections):
        text = '\n'.join(paras)[:80000]
        print('  Analysing part ' + str(i+1) + '/3 (' + label + ')...')

        prompt = (
            'You are a translator. Read this section (' + label + ') of the book "'
            + book_title + '" by ' + author + '. '
            + 'Extract from this section:\n'
            + '- Characters: NAME | GENDER | NICKNAMES | ROLE\n'
            + '- Specific terminology, slang, recurring phrases\n'
            + '- Places and organizations\n'
            + 'Be concise, facts only, no explanations.\n\n'
            + 'TEXT:\n' + text
        )

        partial_results.append(call_llm(client, provider, prompt, 1500))

        if i < 2:
            print('  Waiting 65s (rate limit)...')
            time.sleep(65)

    # Synthesise into a single style guide
    print('  Building final style guide...')
    time.sleep(65)

    synthesis_prompt = (
        'You are an experienced literary translator. '
        + 'I have 3 analysis sections of the book "' + book_title + '" by ' + author + '. '
        + 'Compile them into one COMPLETE TRANSLATION BLUEPRINT for translation into: ' + target_lang + '.\n\n'

        + '## 1. THEMATIC CORE AND ATMOSPHERE\n'
        + 'Main theme, tone, atmosphere. What the translation must preserve at all costs.\n'
        + 'Describe the narrative voice (first/third person, intimate/distant, humour/tension...).\n\n'

        + '## 2. AUTHORIAL STYLE - FINGERPRINTS\n'
        + 'Specific features of the author\'s style: sentence length, rhythm, favourite turns of phrase, '
        + 'use of metaphor, dialogue style. How to replicate them in the target language.\n\n'

        + '## 3. CHARACTERS\n'
        + 'Format: NAME | GENDER | NICKNAMES | ROLE | GRAMMATICAL GENDER + TRANSLATION NOTE\n'
        + 'Note: keep proper names in English, translate titles/ranks.\n\n'

        + '## 4. PLACES AND ORGANIZATIONS\n'
        + 'What to keep in English, what to translate, what to adapt.\n\n'

        + '## 5. TERMINOLOGY AND RECURRING PHRASES\n'
        + 'Key terms, slang, recurring phrases - how to translate them consistently.\n\n'

        + '## 6. CULTURAL SPECIFICS\n'
        + 'British/American idioms and references - suggest equivalents in the target language.\n\n'

        + 'ANALYZY 3 CASTI:\n\n'
        + '--- BEGINNING ---\n' + partial_results[0] + '\n\n'
        + '--- MIDDLE ---\n'   + partial_results[1] + '\n\n'
        + '--- END ---\n'       + partial_results[2]
    )

    return call_llm(client, provider, synthesis_prompt, 3000)

def make_chapter_summary(client, provider, paras, book_title):
    """Brief chapter summary as context for translation prompts."""
    text = ' '.join(p['text'] for p in paras)[:6000]
    prompt = 'Summarize this chapter briefly (3-4 sentences):\n\n' + text
    return call_llm(client, provider, prompt, 300)


def translate_batch(client, provider, paras, chapter_label, char_index,
                    book_title, author, target_lang, memory, memory_file,
                    chapter_summary='', previous_paragraph=''):

    lines_to_translate = []
    cached_results = {}

    # Check translation memory
    for i, p in enumerate(paras):
        h = hash_text(p['text'])
        if h in memory:
            cached_results[i] = {'tag': p['tag'], 'text': memory[h]}
        else:
            lines_to_translate.append((i, p))

    if not lines_to_translate:
        return cached_results  # all from cache, no API call

    # Split into dialogue and narration
    dialogue_idxs = {i for i, p in lines_to_translate if is_dialogue(p['text'])}
    has_dialogue   = bool(dialogue_idxs)
    has_narration  = len(dialogue_idxs) < len(lines_to_translate)

    lines_str = '\n'.join(
        '[' + str(i) + '|' + p['tag'] + '] ' + p['text']
        for i, p in lines_to_translate
    )

    # Context
    context_parts = ['STYLE GUIDE:\n' + char_index]
    if chapter_summary:
        context_parts.append('CHAPTER SUMMARY:\n' + chapter_summary)
    if previous_paragraph:
        context_parts.append('PREVIOUS PARAGRAPH:\n' + previous_paragraph)
    context = '\n\n'.join(context_parts)

    if has_dialogue and has_narration:
        style_note = (
            'STYLE by paragraph type:\n'
            '- Paragraphs starting with a quote or dash = DIALOGUE: colloquial, preserve character voice\n'
            '- Others = NARRATION: literary style, preserve the author\'s rhythm\n'
        )
    elif has_dialogue:
        style_note = 'DIALOGUE: translate colloquially, preserve the character\'s voice and personality.\n'
    else:
        style_note = 'NARRATION: literary style, preserve the author\'s rhythm and tone.\n'

    prompt = (
        'You are a literary translator. Translate chapter "' + chapter_label
        + '" from the book "' + book_title + '" by ' + author
        + ' into language: ' + target_lang + '.\n\n'
        + context + '\n\n'
        + style_note + '\n'
        + 'ADDITIONAL RULES:\n'
        + '- *   *   * preserve exactly as *   *   *\n'
        + '- Quotation marks: \u201etext\u201c\n'
        + '- Translate chapter headings (PROLOGUE, EPILOGUE, ONE, TWO ...) to their natural equivalent in the target language.\n\n'
        + 'Format: [INDEX|TAG] TEXT -> [INDEX|TAG] TRANSLATED TEXT\n'
        + 'Each paragraph on its own line, no other text.\n\n'
        + 'PARAGRAPHS:\n' + lines_str
    )

    response = call_llm(client, provider, prompt, 8000)

    result = dict(cached_results)

    for line in response.split('\n'):
        line = line.strip()
        if not line.startswith('[') or '|' not in line:
            continue
        try:
            end = line.index(']')
            idx_s, tag = line[1:end].split('|')
            text = line[end+1:].strip()
            idx = int(idx_s)
            if tag and text:
                result[idx] = {'tag': tag, 'text': text}
                orig_matches = [p for i, p in lines_to_translate if i == idx]
                if orig_matches:
                    memory[hash_text(orig_matches[0]['text'])] = text
        except (ValueError, IndexError):
            pass

    # Save new translations to memory after each batch
    save_memory(memory, memory_file)
    return result


# ================================================================
#  PROOFREADER PASS
# ================================================================

def proofread_chapter(client, provider, paras, chapter_label, book_title, target_lang):
    """Proofreading pass: fix grammar, awkward sentences, preserve style."""
    lines = '\n'.join('[' + str(i) + '|' + p['tag'] + '] ' + p['text']
                       for i, p in enumerate(paras))
    prompt = (
        'You are a copy-editor. Proofread this translated chapter from "' + book_title + '" '
        + 'in language ' + target_lang + '.\n\n'
        + 'FIX ONLY:\n'
        + '- Grammar errors and typos\n'
        + '- Awkward sentences that sound unnatural\n'
        + '- Inconsistent declension of names\n\n'
        + 'DO NOT CHANGE:\n'
        + '- Author\'s style and tone\n'
        + '- Word choices that are correct\n'
        + '- *   *   * scene break markers\n\n'
        + 'If a paragraph is fine, return it unchanged.\n'
        + 'Format: [INDEX|TAG] CORRECTED TEXT\n\n'
        + 'PARAGRAPHS:\n' + lines
    )
    response = call_llm(client, provider, prompt, 8000)
    result = {}
    for line in response.split('\n'):
        line = line.strip()
        if not line.startswith('[') or '|' not in line:
            continue
        try:
            end = line.index(']')
            idx_s, tag = line[1:end].split('|')
            text = line[end+1:].strip()
            idx = int(idx_s)
            if tag and text:
                result[idx] = {'tag': tag, 'text': text}
        except (ValueError, IndexError):
            pass
    # Return corrected; fall back to original for unchanged paragraphs
    return [result.get(i, paras[i]) for i in range(len(paras))]


# ================================================================
#  THREADWEAVER - consistency audit
# ================================================================

def threadweave(client, provider, translated_chapters, book_title, char_index, target_lang):
    """
    1. Reads the full translated text and builds a consistency map
    2. Generates a list of fixes as JSON
    3. Returns (map_text, fix_list) where fixes are [{"from": ..., "to": ...}, ...]
    """
    print('\nThreadweaver: reading translated text...')

    all_translated = ''
    for ch in translated_chapters:
        all_translated += '\n\n--- ' + ch['label'] + ' ---\n'
        for p in ch['paras']:
            all_translated += p['text'] + '\n'

    # Step 1: consistency map
    map_prompt = (
        'You are a consistency editor. Read the translated text of "' + book_title + '" '
        + 'in language ' + target_lang + '.\n\n'
        + 'Build a CONSISTENCY MAP. For each element list:\n'
        + 'ELEMENT | TRANSLATION_VARIANTS | OCCURRENCES | CONSISTENT\n\n'
        + 'Track: character names and their declension, key recurring phrases, '
        + 'place names and organizations, thematic motifs.\n\n'
        + 'TEXT:\n' + all_translated[:40000]
    )
    consistency_map = call_llm(client, provider, map_prompt, 2000)
    print('  Map built. Generating fixes...')
    time.sleep(65)

    # Step 2: fixes as machine-readable JSON
    fix_prompt = (
        'You are a consistency editor. I have a consistency map of the translation of "' + book_title + '":\n\n'
        + consistency_map + '\n\n'
        + 'STYLE GUIDE (authoritative source of correct forms):\n' + char_index + '\n\n'
        + 'Generate a list of all necessary text replacements. '
        + 'ONLY for elements where consistency IS NOT in order.\n\n'
        + 'Reply with ONLY a valid JSON array, no other text:\n'
        + '[\n'
        + '  {"from": "inconsistent form", "to": "correct form", "reason": "why"},\n'
        + '  ...\n'
        + ']\n\n'
        + 'Rules:\n'
        + '- "from" must be the exact string that occurs in the text\n'
        + '- Do not include fixes you are unsure about\n'
        + '- Max 30 fixes, only the most important ones\n'
        + '- If nothing needs fixing, return an empty array []'
    )
    fixes_raw = call_llm(client, provider, fix_prompt, 2000)

    # Parse JSON - strip possible markdown fences
    fixes_raw = re.sub(r'^```[\w]*\n?', '', fixes_raw.strip(), flags=re.MULTILINE)
    fixes_raw = re.sub(r'\n?```$', '', fixes_raw.strip(), flags=re.MULTILINE)
    try:
        fixes = json.loads(fixes_raw.strip())
        if not isinstance(fixes, list):
            fixes = []
    except json.JSONDecodeError:
        print('  Warning: could not parse JSON fixes, attempting rescue...')
        # Rescue at least partially parseable fixes
        fixes = []
        for m in re.finditer(r'\{"from":\s*"([^"]+)",\s*"to":\s*"([^"]+)"', fixes_raw):
            fixes.append({"from": m.group(1), "to": m.group(2), "reason": ""})

    print('  Threadweaver audit done: ' + str(len(fixes)) + ' fixes proposed.')
    return consistency_map, fixes


def apply_threadweave_fixes(translated_chapters, fixes):
    """Apply a list of {"from":..., "to":...} fixes to all paragraphs in all chapters."""
    total_replacements = 0
    fix_log = []

    for ch in translated_chapters:
        for p in ch['paras']:
            original = p['text']
            for fix in fixes:
                if fix['from'] in p['text']:
                    p['text'] = p['text'].replace(fix['from'], fix['to'])
            if p['text'] != original:
                total_replacements += 1
                fix_log.append(ch['label'] + ': ' + original[:60] + ' -> ' + p['text'][:60])

    return total_replacements, fix_log
# ================================================================
#  LORE FETCHER - downloads lore data from fandom wiki via MediaWiki API
# ================================================================

LORE_WIKIS = {
    'forgotten realms':   'forgottenrealms.fandom.com',
    'dragonlance':        'dragonlance.fandom.com',
    'eberron':            'eberron.fandom.com',
    'wheel of time':      'wot.fandom.com',
    'witcher':            'witcher.fandom.com',
    'stormlight':         'coppermind.net',
    'cosmere':            'coppermind.net',
    'game of thrones':    'gameofthrones.fandom.com',
    'asoiaf':             'awoiaf.westeros.org',
    'star wars':          'starwars.fandom.com',
    'lord of the rings':  'lotr.fandom.com',
    'tolkien':            'lotr.fandom.com',
    'warhammer':          'warhammer40k.fandom.com',
    'discworld':          'wiki.lspace.org',
    'ravenloft':          'ravenloft.fandom.com',
    'spelljammer':        'spelljammer.fandom.com',
    'greyhawk':           'greyhawk.fandom.com',
}

LORE_CATEGORIES = {
    'forgottenrealms.fandom.com': ['Locations', 'Characters', 'Races', 'Organizations', 'Deities'],
    'dragonlance.fandom.com':     ['Locations', 'Characters', 'Races', 'Organizations', 'Deities'],
    'coppermind.net':             ['Locations', 'Characters', 'Races', 'Organizations', 'Magic'],
    '_default':                   ['Locations', 'Characters', 'Races', 'Organizations'],
}


def fetch_wiki_category(wiki_host, category, limit=80):
    import urllib.request, urllib.parse
    if 'fandom.com' in wiki_host:
        api_url = 'https://' + wiki_host + '/api.php'
    elif wiki_host == 'coppermind.net':
        api_url = 'https://coppermind.net/w/api.php'
    else:
        api_url = 'https://' + wiki_host + '/api.php'

    params = urllib.parse.urlencode({
        'action': 'query', 'list': 'categorymembers',
        'cmtitle': 'Category:' + category, 'cmlimit': str(limit),
        'cmtype': 'page', 'format': 'json',
    })
    req = urllib.request.Request(
        api_url + '?' + params,
        headers={'User-Agent': 'BookTranslator/1.0'}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode('utf-8'))
    return [m['title'] for m in data.get('query', {}).get('categorymembers', [])]


def build_lore_glossary(client, provider, lore_name, target_lang, lore_file):
    key = lore_name.lower().strip()
    wiki_host = LORE_WIKIS.get(key)
    if not wiki_host:
        for k, v in LORE_WIKIS.items():
            if key in k or k in key:
                wiki_host = v
                break
    if not wiki_host:
        print('  Warning: unknown wiki for "' + lore_name + '"')
        print('  Known worlds: ' + ', '.join(LORE_WIKIS.keys()))
        print('  Continuing without lore data...')
        return ''

    print('  Wiki: ' + wiki_host)
    categories = LORE_CATEGORIES.get(wiki_host, LORE_CATEGORIES['_default'])
    all_terms = {}

    for cat in categories:
        print('  Fetching category: ' + cat + '...', end='', flush=True)
        try:
            terms = fetch_wiki_category(wiki_host, cat, limit=80)
            all_terms[cat] = terms
            print(' ' + str(len(terms)) + ' entries')
        except Exception as e:
            print(' error: ' + str(e)[:50])
            all_terms[cat] = []
        time.sleep(1)

    terms_text = ''
    for cat, terms in all_terms.items():
        if terms:
            terms_text += cat + ':\n' + ', '.join(terms[:60]) + '\n\n'

    if not terms_text:
        print('  No lore data could be downloaded.')
        return ''

    print('  Generating lore glossary for ' + target_lang + '...')
    prompt = (
        'You are a fantasy literature expert and translator. '
        + 'I have these terms from the world "' + lore_name + '":\n\n'
        + terms_text
        + 'Create a LORE GLOSSARY for translation into: ' + target_lang + '.\n\n'
        + 'Rules:\n'
        + '- Character proper names: do not translate (Drizzt stays Drizzt)\n'
        + '- Place names: translate only if an established translation exists in ' + target_lang + ' literature\n'
        + '- Races and titles: translate (elf, dwarf, high druid...)\n'
        + '- Organizations: translate if it makes sense, otherwise keep\n\n'
        + 'Reply with ONLY valid JSON, no other text:\n'
        + '{"terms": [{"en": "original", "trans": "translation", '
        + '"rule": "keep|translate|adapt", "note": "note"}]}'
    )

    result_raw = call_llm(client, provider, prompt, 4000)
    result_raw = re.sub(r'^```[\w]*\n?', '', result_raw.strip(), flags=re.MULTILINE)
    result_raw = re.sub(r'\n?```$', '', result_raw.strip(), flags=re.MULTILINE)

    try:
        glossary = json.loads(result_raw.strip())
    except json.JSONDecodeError:
        print('  Warning: could not parse glossary as JSON, saving as raw text')
        glossary = {'raw': result_raw, 'terms': []}

    glossary['lore_world'] = lore_name
    glossary['wiki']       = wiki_host
    glossary['language']   = target_lang

    with open(lore_file, 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)

    print('  Lore glossary saved: ' + lore_file
          + '  (' + str(len(glossary.get('terms', []))) + ' terms)')
    return glossary_to_text(glossary)


def glossary_to_text(glossary):
    if not glossary.get('terms'):
        return glossary.get('raw', '')
    lines = ['LORE GLOSSARY - ' + glossary.get('lore_world', '') + ':']
    preserve  = [t for t in glossary['terms'] if t.get('rule') == 'keep']
    translate = [t for t in glossary['terms'] if t.get('rule') != 'keep']
    if preserve:
        lines.append('Keep in original: ' + ', '.join(t['en'] for t in preserve[:40]))
    if translate:
        lines.append('Translate:')
        for t in translate[:60]:
            note = ' (' + t['note'] + ')' if t.get('note') else ''
            lines.append('  ' + t['en'] + ' -> ' + t.get('trans', t['en']) + note)
    return '\n'.join(lines)


def load_lore_glossary(lore_file):
    with open(lore_file, 'r', encoding='utf-8') as f:
        return json.load(f)




# ================================================================
#  MAIN
# ================================================================

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    epub_path   = sys.argv[1]
    api_key     = sys.argv[2]

    # Parse provider and optional flags
    provider   = 'anthropic'
    do_proof   = False
    do_thread  = False
    args = sys.argv[3:]

    if '--provider' in args:
        i = args.index('--provider')
        if i + 1 < len(args):
            provider = args[i + 1].lower()
            args = args[:i] + args[i+2:]

    if '--proofread' in args:
        do_proof = True
        args = [a for a in args if a != '--proofread']

    if '--threadweave' in args:
        do_thread = True
        args = [a for a in args if a != '--threadweave']

    lore_name = None
    if '--lore' in args:
        i = args.index('--lore')
        if i + 1 < len(args):
            lore_name = args[i + 1]
            args = args[:i] + args[i+2:]

    sys.argv = sys.argv[:3] + args

    # Parse language (required 3rd argument).
    # Language is a lowercase word with no spaces. Anything else is an error.
    # The value is passed directly to the LLM, so any language name works.
    LANG_ALIASES = {
        'cs': 'czech', 'cz': 'czech',
        'sk': 'slovak', 'de': 'german', 'fr': 'french',
        'es': 'spanish', 'it': 'italian', 'pl': 'polish',
        'ru': 'russian', 'jp': 'japanese', 'ja': 'japanese',
        'nl': 'dutch', 'pt': 'portuguese', 'ro': 'romanian',
        'hu': 'hungarian', 'sv': 'swedish', 'no': 'norwegian',
        'fi': 'finnish', 'da': 'danish', 'tr': 'turkish',
        'ko': 'korean', 'zh': 'chinese', 'ar': 'arabic', 'he': 'hebrew',
    }

    def _is_lang(s):
        return bool(s and ' ' not in s and len(s) <= 20
                    and not s[0].isupper() and not any(c.isdigit() for c in s))

    arg3 = sys.argv[3] if len(sys.argv) > 3 else ''
    if not arg3 or not _is_lang(arg3.lower()):
        print('ERROR: Target language is required as the 3rd argument.')
        print('  Example: python translate_epub.py book.epub sk-ant-... german')
        print('  Any language name works: german, french, spanish, japanese, dutch ...')
        sys.exit(1)
    target_lang    = LANG_ALIASES.get(arg3.lower(), arg3.lower())
    book_title_arg = sys.argv[4] if len(sys.argv) > 4 else ''
    author_arg     = sys.argv[5] if len(sys.argv) > 5 else ''

    lang_suffix = target_lang[:2].upper()  # CZ, SK, DE, FR...
    base          = epub_path.replace('.epub', '')
    progress_file = base + '.' + lang_suffix + '.progress.json'
    index_file    = base + '.' + lang_suffix + '.index.json'
    memory_file   = base + '.' + lang_suffix + '.memory.json'
    output_file   = base + '_' + lang_suffix + '.epub'

    if provider == 'openai':
        try:
            import openai as openai_lib
        except ImportError:
            print('Error: pip install openai')
            sys.exit(1)
        client = openai_lib.OpenAI(api_key=api_key)
        print('Provider: OpenAI (gpt-4.1)')
    else:
        try:
            import anthropic
        except ImportError:
            print('Error: pip install anthropic')
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
        print('Provider: Anthropic (claude-sonnet-4-6)')

    # --- Load epub and metadata ---
    print('\nLoading epub: ' + epub_path)

    # Read metadata from OPF
    z = zipfile.ZipFile(epub_path)
    raw_files = {n: z.read(n) for n in z.namelist()}
    opf_title, opf_author = read_opf_metadata(raw_files)

    book_title = book_title_arg or opf_title
    author     = author_arg or opf_author
    translated_title = book_title  # keep original title in the translated epub

    print('Title:  ' + (book_title or '(unknown)'))
    print('Author: ' + (author or '(unknown)'))
    print('Lang:   ' + target_lang)
    extras = []
    if do_proof:  extras.append('--proofread')
    if do_thread: extras.append('--threadweave')
    if lore_name: extras.append('--lore ' + lore_name)
    if extras: print('Modes:  ' + ', '.join(extras))

    orig_files, chapters = load_epub(epub_path, book_title)
    total_paras = sum(len(ch['paras']) for ch in chapters)
    print('Loaded ' + str(len(chapters)) + ' chapters, ' + str(total_paras) + ' paragraphs')

    if not chapters:
        print('ERROR: No chapters found. Try providing the title manually as the 3rd argument.')
        sys.exit(1)

    if not book_title:
        book_title = input('Unknown book title, please enter it: ').strip()
    if not author:
        author = input('Unknown author, please enter: ').strip()

    # --- Lore glossary (if --lore was specified) ---
    lore_text = ''
    if lore_name:
        lore_file = base + '.' + lang_suffix + '.lore.json'
        print('\nLoading lore data for: ' + lore_name)
        if os.path.exists(lore_file):
            print('  Loaded cached lore glossary: ' + lore_file)
            lore_text = glossary_to_text(load_lore_glossary(lore_file))
        else:
            lore_text = build_lore_glossary(client, provider, lore_name, target_lang, lore_file)
            time.sleep(65)  # rate limit after lore API call

    # --- Character index ---
    if os.path.exists(index_file):
        with open(index_file, 'r', encoding='utf-8') as f:
            char_index = json.load(f)['index']
        if lore_text:
            char_index = lore_text + '\n\n' + char_index
        print('Character index loaded from file (no spoilers displayed)')
    else:
        char_index = build_character_index(client, provider, chapters, book_title, author, target_lang)
        if lore_text:
            char_index = lore_text + '\n\n' + char_index
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump({'index': char_index}, f, ensure_ascii=False)
        print('Character index built -> ' + index_file + '  (not displayed, no spoilers)')
        print('Tip: to edit the index before translation, interrupt (Ctrl+C),')
        print('     edit the file and restart.')
        print()

    # --- Load translation memory ---
    memory = load_memory(memory_file)
    if memory:
        print('Translation memory: ' + str(len(memory)) + ' cached translations')

    # --- Load progress ---
    if os.path.exists(progress_file):
        with open(progress_file, 'r', encoding='utf-8') as f:
            translated = json.load(f)
        # Validate: discard chapters that are empty (from a broken run)
        valid = [ch for ch in translated if ch.get('paras') and len(ch['paras']) > 0
                 and any(p.get('text','').strip() for p in ch['paras'])]
        if len(valid) < len(translated):
            print('Warning: discarded ' + str(len(translated)-len(valid)) + ' empty chapters from previous run')
        translated = valid
        print('Resuming: ' + str(len(translated)) + ' chapters already done\n')
    else:
        translated = []

    done_slugs = {ch['slug'] for ch in translated}
    BATCH = 25

    # --- Translate ---
    for chapter in chapters:
        slug  = chapter['slug']
        label = chapter['label']
        paras = chapter['paras']

        if slug in done_slugs:
            print('  (skipped) ' + label)
            continue

        print('\n> Translating: ' + label + ' (' + str(len(paras)) + ' paragraphs)')

        # Chapter summary as context (helps with translation continuity)
        print('  Building chapter summary...', end='', flush=True)
        try:
            chapter_summary = make_chapter_summary(client, provider, paras, book_title)
            print(' OK')
            time.sleep(4)
        except Exception as e:
            chapter_summary = ''
            print(' skipped (' + str(e)[:40] + ')')

        translated_paras = [None] * len(paras)
        previous_paragraph = ''

        for i in range(0, len(paras), BATCH):
            batch = paras[i:i+BATCH]
            bn = i // BATCH + 1
            bt = (len(paras) - 1) // BATCH + 1
            print('  Batch ' + str(bn) + '/' + str(bt) +
                  '  (para. ' + str(i) + '-' + str(i+len(batch)-1) + ') ...', end='', flush=True)

            for attempt in range(5):
                try:
                    result = translate_batch(client, provider, batch, label, char_index,
                                             book_title, author, target_lang,
                                             memory, memory_file,
                                             chapter_summary, previous_paragraph)
                    for j in range(len(batch)):
                        translated_paras[i+j] = result.get(j, batch[j])
                    cached = sum(1 for j in range(len(batch)) if hash_text(batch[j]['text']) in memory)
                    cache_note = ', ' + str(cached) + ' from cache' if cached else ''
                    print(' OK (' + str(len(result)) + '/' + str(len(batch)) + cache_note + ')')
                    # Remember last translated paragraph for continuity
                    last = result.get(len(batch)-1)
                    if last: previous_paragraph = last['text']
                    break
                except Exception as e:
                    err_str = str(e)
                    # Rate limit -> wait longer
                    if 'rate_limit' in err_str or '429' in err_str or 'tokens per minute' in err_str:
                        wait = 65
                        print(' Rate limit! Waiting ' + str(wait) + 's...', end='', flush=True)
                    else:
                        wait = 15 * (attempt + 1)
                        print(' Error: ' + err_str[:80] + '  (waiting ' + str(wait) + 's...)', end='', flush=True)
                    time.sleep(wait)
                    if attempt == 4:
                        print(' keeping original')
                        for j in range(len(batch)):
                            translated_paras[i+j] = batch[j]

            time.sleep(4)  # rate limit: 30k tokens/min

        final = [translated_paras[i] or paras[i] for i in range(len(paras))]
        translated.append({
            'slug': slug, 'label': label,
            'file_key': chapter['file_key'], 'paras': final
        })

        # Optional proofreading pass
        if do_proof:
            print('  Proofreading...', end='', flush=True)
            try:
                time.sleep(4)
                final = proofread_chapter(client, provider, final, label, book_title, target_lang)
                translated[-1]['paras'] = final
                print(' OK')
            except Exception as e:
                print(' skipped (' + str(e)[:60] + ')')

        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(translated, f, ensure_ascii=False)
        print('  Saved [' + str(len(translated)) + '/' + str(len(chapters)) + ']')

    # --- Optional Threadweaver audit + automatic application of fixes ---
    if do_thread:
        print('\nRunning Threadweaver consistency audit...')
        tw_file = base + '.' + lang_suffix + '.threadweave.json'
        try:
            tw_map, fixes = threadweave(client, provider, translated, book_title, char_index, target_lang)

            # Save report for review
            report = {
                'consistency_map': tw_map,
                'fixes': fixes
            }
            with open(tw_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print('  Report saved: ' + tw_file)

            if fixes:
                print('  Applying ' + str(len(fixes)) + ' consistency fixes...')
                count, fix_log = apply_threadweave_fixes(translated, fixes)
                print('  Fixed ' + str(count) + ' paragraphs:')
                for line in fix_log[:10]:  # show first 10
                    print('    ' + line)
                if len(fix_log) > 10:
                    print('    ... and ' + str(len(fix_log) - 10) + ' more (see ' + tw_file + ')')

                # Save corrected progress
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(translated, f, ensure_ascii=False)
                print('  Corrected progress saved.')
            else:
                print('  No inconsistencies found - translation is consistent.')

        except Exception as e:
            print('Threadweaver failed: ' + str(e))

    # --- Build epub ---
    print('\nTranslation complete! Building epub...')
    epub_data = build_epub(orig_files, translated, translated_title)
    with open(output_file, 'wb') as f:
        f.write(epub_data)
    print('Saved: ' + output_file + '  (' + str(len(epub_data)//1024) + ' KB)')
    print('Progress file: ' + progress_file + '  (can be deleted)')


if __name__ == '__main__':
    main()