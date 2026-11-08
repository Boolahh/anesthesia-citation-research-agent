"""Extract citations *as displayed* and annotations from chat-export PDFs.

This does not check whether a source exists. A PDF annotation can be attached to the same
visible label multiple times; those annotation duplicates are *not* separate citations.
True repeated citation entries within one answer are retained as separate rows.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict
import re
from urllib.parse import urlparse, unquote
import fitz

DOI_RE=re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+',re.I)
PMID_RE=re.compile(r'\bPMID\s*[:#]?\s*(\d{6,9})\b',re.I)
REF_HEADER=re.compile(r'^(?:key|selected|main|primary|suggested|important|additional)?\s*(?:references|guidelines(?: and references)?|sources|bibliography)\s*:?',re.I)
YEAR_RE=re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
GENERIC_LINKS={'full','article','full article','pubmed','pubmed central','pmc','doi','clinical review','ncbi bookshelf','read more','source','link','view article','asra pain medicine'}


def flatten_text(s):
    return re.sub(r'\s+', ' ', s).strip()


def normalize(s):
    return re.sub(r'[^a-z0-9]+','',s.lower())


def trim_tracking(url):
    # Do not strip user-visible URLs in blue cells. This function is for matching IDs only.
    return url.split('?',1)[0].split('#',1)[0]


def ids_as_shown(text,url):
    doi=DOI_RE.search(text) or DOI_RE.search(unquote(url))
    pmid=PMID_RE.search(text)
    if not pmid:
        pmid=re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/',url,re.I)
    return ((doi.group(0).rstrip('.,;') if doi else 'NR'), (pmid.group(1) if pmid else 'NR'))


def rough_fields(text,url):
    doi,pmid=ids_as_shown(text,url)
    year=YEAR_RE.search(text)
    author='NR'
    ma=re.match(r'\s*([A-Z][\w\-\u00C0-\u024F ]{1,45}(?:\s+et al\.?)?)\s*[,.]',text)
    if ma and (re.search(r'\bet al\b',ma.group(1),re.I) or re.match(r'^[A-Z][a-z-]+\s+[A-Z]{1,3}\b',ma.group(1))):
        author=ma.group(1).strip()
    journal='NR'
    mj=re.search(r'(?:\s+—\s+|\s+[-–]\s+)(NEJM|BJA Education|Anesthesia & Analgesia|Anesthesiology|CMAJ|JACC)(?:\b|,)',text,re.I)
    if mj:journal=mj.group(1)
    title = text if text else 'NR'
    if author!='NR':
        title=flatten_text(text[ma.end():]).lstrip('.:, ') or 'NR'
    # Do NOT silently replace original wording with a researched/corrected title.
    return {'citation':text or 'NR','title':title,'authors':author,
            'year':year.group() if year else 'NR','journal':journal,'doi':doi,'pmid':pmid}


def page_lines(page):
    lines=[]
    for block in page.get_text('dict',sort=True).get('blocks',[]):
        if block.get('type') != 0:continue
        for line in block.get('lines',[]):
            t=flatten_text(''.join(span['text'] for span in line.get('spans',[])))
            if t:
                lines.append({'text':t,'box':fitz.Rect(line['bbox'])})
    lines.sort(key=lambda x:(round(x['box'].y0,1),x['box'].x0))
    return lines


def text_for_link(page,lines,boxes):
    # Determine the citation shown, not merely a tooltip / shortened in-text footnote.
    boxes=sorted(boxes,key=lambda x:(x.y0,x.x0))
    first=boxes[0]
    overlaps=[]
    for line in lines:
        overlap=line['box'] & first
        if not overlap.is_empty and overlap.get_area() >= 0.015 * max(line['box'].get_area(),1):
            overlaps.append(line)
    if overlaps:
        first_line=overlaps[0]
        idx=lines.index(first_line)
    else:
        idx=min(range(len(lines)),key=lambda i:abs(lines[i]['box'].y0-first.y0))
        first_line=lines[idx]
    # Work out actual clickable phrase to distinguish a short "Full article" label.
    words=[]
    for b in boxes:
        for w in page.get_text('words'):
            rect=fitz.Rect(w[:4]); inter=rect&b
            if not inter.is_empty and inter.get_area() >= 0.20*max(rect.get_area(),1):
                words.append(w[4])
    anchor=flatten_text(' '.join(words))
    s=first_line['text']
    if anchor.lower() in GENERIC_LINKS or len(anchor)<12:
        # A footnote link like "Full article" belongs to the preceding source entry.
        if idx>0 and not re.match(r'^\d+[\.)]\s', first_line['text']) and not REF_HEADER.match(lines[idx-1]['text']):
            p=lines[idx-1]
            if abs(p['box'].y1-first_line['box'].y0)<12 and \
               (re.match(r'^\d+\.',p['text']) or len(s)<30):
                s=p['text']+' '+s
    # Join continuation of wrapped reference entries (but not next numbered entry).
    if idx+1<len(lines) and not re.match(r'^\d+[\.)]\s',lines[idx+1]['text']):
        nextline=lines[idx+1]
        if nextline['box'].y0-first_line['box'].y1<6 and \
           (nextline['text'].lower() in GENERIC_LINKS or nextline['text'].startswith('Management') or \
            s.endswith((',', ' and', ' of', 'Blood', 'Prediction,'))):
            s+=' '+nextline['text']
    return re.sub(r'^(?:Key|Selected|Main|Primary) references\s*:\s*', '', flatten_text(s),flags=re.I).rstrip(' .')


def get_question_for_file(pages, questions, filename):
    samples=flatten_text(' '.join(p.get_text() for p in pages[:2]))
    norm=normalize(samples)
    matched=[]
    for code, q in questions.items():
        qn=normalize(q)
        if qn in norm or (len(qn)>40 and qn[:60] in norm): matched.append(code)
    if len(matched)==1:return matched[0],[]
    m=re.search(r'(?i)(?:^|[_\s\-])Q\s*0?([1-9]|1[0-2])(?:[^0-9]|$)',filename)
    if m:return f'Q{int(m.group(1)):02d}',(['Multiple question statements detected; filename Q ID used'] if len(matched)>1 else [])
    if len(matched)>1:return matched[0],[f'Multiple question statements {matched}; split this PDF by question to ensure accurate assignment']
    return None,['Could not identify question from PDF; name file Q01_*.pdf, etc.']


def extract_links(pages):
    groups=[]
    for pno,page in enumerate(pages):
        annotations=[]
        for a in page.get_links():
            u=a.get('uri')
            if not u or not u.startswith(('https://','http://')):continue
            annotations.append((u,fitz.Rect(a['from'])))
        # Collapse duplicated annotation rectangles within a single reference entry.
        byurl=defaultdict(list)
        for u,rect in annotations:byurl[u].append(rect)
        for u,rects in byurl.items():
            clusters=[]
            for rect in sorted(rects,key=lambda v:v.y0):
                if clusters and rect.y0-clusters[-1][-1].y0<27:
                    clusters[-1].append(rect)
                else:
                    clusters.append([rect])
            for rectgroup in clusters:
                lines=page_lines(page)
                citation=text_for_link(page,lines,rectgroup)
                groups.append({'page':page.number+1,'y':rectgroup[0].y0,'x':rectgroup[0].x0,
                               'url':u,'citation':citation,'kind':'linked'})
    return sorted(groups,key=lambda g:(g['page'],g['y'],g['x']))


def unlinked_reference_lines(page):
    lines=page_lines(page)
    out=[]
    active=False
    for i,line in enumerate(lines):
        text=line['text']
        if REF_HEADER.match(text) and len(text)<70:
            active=True
            continue
        if not active:continue
        if re.match(r'^(?:Bottom line|The central principle|This is an educational|Reset checklist|Key clinical takeaways)',text,re.I):
            active=False
            continue
        if line['box'].x0 < 53 or len(text)<12 or text.lower() in GENERIC_LINKS: continue
        if re.match(r'^[1-9]\.|^\d{4}\s|^[A-Z]',text):
            # An explicit list item or heading-like line after the references heading.
            if text.endswith(':'):active=False;continue
            out.append({'page':page.number+1,'y':line['box'].y0,'x':line['box'].x0,
                        'citation':text,'url':'','kind':'unlinked'})
    return out



def fallback_named_sources(pages):
    """Conservative recovery when PDFs flattened all links; never add guessed URLs.

    Only use explicit publication / guideline naming patterns from the actual export.
    Ambiguous site labels like 'PMC +1' are not automatically counted as papers.
    """
    full=' '.join(page.get_text() for page in pages)
    flat=flatten_text(full)
    out=[]
    # A named journal guideline with author + publication year in a prose citation.
    for m in re.finditer(r'((?:First|Second|Third|Fourth|Fifth|Sixth) Consensus Guidelines\s+for\s+.{10,130}?\([^()]{8,120}?(?:19|20)\d{2}\))',flat,re.I):
        out.append({'page':0,'x':0,'y':float(m.start()),'citation':m.group(1),'url':'','kind':'named_unlinked'})
    # Guideline organizations appearing as explicit source names (not general clinical claims).
    # These may be incomplete bibliography entries; human review is mandatory.
    if 'The principal recommendations from recent guidelines are' in flat:
        candidates=re.findall(r'(?:20\d{2})\s+(?:ACC/AHA|POQI consensus|ESAIC|Association of Anaesthetists)',flat,re.I)
        seen=set()
        for idx,item in enumerate(candidates):
            if item not in seen:
                out.append({'page':0,'x':0,'y':100000+idx,'citation':item,'url':'','kind':'named_unlinked'})
                seen.add(item)
    return out


def _parse_pages(pages, tool, q, path, api=None):
        warnings=[]
        links=extract_links(pages)
        # For PDFs with an explicit references section, find unlinked entries as well.
        unlinked=[]
        for page in pages:
            unlinked.extend(unlinked_reference_lines(page))
        for u in unlinked:
            if not any(g['page']==u['page'] and abs(g['y']-u['y'])<=7 for g in links):
                # Avoid treating random text following a heading as a citation.
                if len(u['citation'])>15 and len(u['citation'])<350 and not any(g['page']==u['page'] and \
                     0 < u['y']-g['y'] < 30 and (g['citation'].endswith((',', ' and', ' of','Prediction,')) or \
                       u['citation'].startswith(('Prevention,','Pain Management','Management'))) for g in links):
                    links.append(u)
        links.sort(key=lambda g:(g['page'],g['y'],g['x']))
        if not links:
            links.extend(fallback_named_sources(pages))
        text='\n'.join(page.get_text(sort=True) for page in pages)
        if re.search(r'\+\d+', text):
            warnings.append('Collapsed +N citation labels found; verify any additional citations hidden by the export')
        if api:
            try:
                returned=api.extract_citations(text, links, tool, q)
                if returned:
                    enriched=[]
                    for item in returned:
                        src=item.get('url','')
                        if src and src!='NR' and src not in [g['url'] for g in links]:
                            src='' # Model cannot invent / replace original URLs.
                        raw=item.get('citation','')
                        if raw and normalize(raw) not in normalize(text):
                            # PDF line wrapping alters whitespace; reject out-of-text citations.
                            if normalize(raw)[:35] not in normalize(text): continue
                        enriched.append({'citation':raw,'url':src,'kind':'model','page':0,
                                         'title':item.get('title','NR'), 'authors':item.get('authors','NR'),
                                         'year':item.get('year','NR'),'journal':item.get('journal','NR')})
                    if enriched:links=enriched
            except Exception as exc:
                warnings.append('AI extraction failed; used deterministic PDF links: '+str(exc)[:220])
        if not links:
            warnings.append('No extractable citations; PDF may have lost all source links')
        elif not any(g.get('url') for g in links):
            warnings.append('No clickable URLs found; extracted text-only references where possible')
        if not any(g.get('url') for g in links) and not api:
            warnings.append('Enable OPENAI_API_KEY to identify unlinked citations from narrative text')
        # Preserve apparent references in order; never dedupe actual citation occurrences.
        citations=[];seen=set()
        for order, g in enumerate(links,1):
            raw=flatten_text(g.get('citation',''))
            url=g.get('url','')
            rough=rough_fields(raw,url)
            for field in ['title','authors','year','journal']:
                if g.get(field) and g[field]!='NR':rough[field]=g[field]
            doi,pmid=ids_as_shown(raw,url)
            identity=(doi if doi!='NR' else pmid if pmid!='NR' else trim_tracking(url) or normalize(raw))
            repeat='Y' if identity in seen else 'N';seen.add(identity)
            citations.append({'tool':tool,'question':q,'order':order,'url':url or 'NR',
                'repeat':repeat,**rough,'source_file':path.name,'source_page':g.get('page',0),
                'extraction_method':g.get('kind','unknown')})
        return citations,warnings


def parse_pdf(path, tool, questions, api=None):
    path=Path(path)
    with fitz.open(str(path)) as doc:
        pages=list(doc)
        # Combined PDF export: identify each fresh question at the start of its first page.
        # If two questions start on one page, export that conversation as separate PDFs.
        changes=[]
        for i,page in enumerate(pages):
            beginning=normalize(page.get_text(sort=True)[:1300])
            match=[]
            for code,question in questions.items():
                qn=normalize(question)
                if qn in beginning:match.append(code)
            if len(match)==1 and (not changes or changes[-1][1]!=match[0]):
                changes.append((i,match[0]))
        if len(changes)>1:
            all_rows=[];warnings=[]
            for index,(start,q) in enumerate(changes):
                end=changes[index+1][0] if index+1<len(changes) else len(pages)
                result,problems=_parse_pages(pages[start:end],tool,q,path,api)
                all_rows.extend(result)
                warnings.extend(f'{q}: {x}' for x in problems)
            if changes[0][0]>0:warnings.append('Unassigned pages before first detected question were skipped')
            return all_rows,warnings
        q,warnings=get_question_for_file(pages,questions,path.stem)
        if not q:return [],warnings
        result,problems=_parse_pages(pages,tool,q,path,api)
        return result,warnings+problems
