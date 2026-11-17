"""Aggregate statistics over parsed example CVs. Usage: python3 -I cvstats.py parsed.jsonl"""
import sys, json, re, statistics as st, collections as C
rows=[json.loads(l) for l in open(sys.argv[1])]
MARK=['gpa of 3.9','employee of the month','top 5% of the program','graduated with distinction','dance club','recognized as employee','achieved a gpa']
for r in rows:
    if r['site']=='kick':
        txt=' '.join(s['text'] for s in r['sections']).lower()
        tm=any(m in txt for m in MARK)
        r['site']='kick_tmpl' if tm else ('kick_real' if r.get('hired_by') else 'kick_other')
def med(x): return round(st.median(x),1) if x else None
def pct(a,b): return f"{100*a/b:.1f}%" if b else "n/a"
def q(x,p):
    x=sorted(x); return x[int(p*(len(x)-1))] if x else None
STOP=set("a an the and of to in for with on at by from as".split())
for site in ['kick_real','kick_other','kick_tmpl','enh','cf']:
    R=[r for r in rows if r['site']==site]
    if not R: continue
    n=len(R); print(f"\n================ {site}  n={n}")
    order=C.Counter(); first=C.Counter(); pres=C.Counter(); edu_before=0; both=0
    nroles=[]; bpr=[]; blen=[]; bnum=0; btot=0; fw=C.Counter(); sumlen=[]; words=[]; nsk=[]; nsec=[]
    listfmt=0; ent_tot=0; other=C.Counter(); datefmt=C.Counter(); labels=C.Counter(); long_b=0; pron=0
    for r in R:
        names=[s['name'] for s in r['sections']]
        core=[x for x in names if not x.startswith('other:')]
        for x in names:
            if x.startswith('other:'): other[x[6:]]+=1
        nsec.append(len(names))
        seen=[]; [seen.append(x) for x in core if x not in seen]
        order[' > '.join(seen[:5])]+=1
        if seen: first[seen[0]]+=1
        for x in set(seen): pres[x]+=1
        if 'education' in seen and 'experience' in seen:
            both+=1; edu_before+= seen.index('education')<seen.index('experience')
        w=0
        for s in r['sections']:
            w+=len(s['text'].split())
            if s['name']=='summary': sumlen.append(len(s['text'])-len(s['raw']))
            if s['name']=='skills':
                k=sum(max(1,len(e['bullets'])) for e in s['entries']) if s['entries'] else len(re.split(r'[,•|]| {2,}',s['text']))
                nsk.append(k)
            if s['name']=='experience':
                nroles.append(len(s['entries']))
                for e in s['entries']:
                    ent_tot+=1; listfmt+= bool(e.get('list'))
                    m=re.search(r'(\d{2}/\d{4})|(\b(19|20)\d{2}\b)|([A-Z][a-z]{2,8} (19|20)\d{2})',e['head'])
                    if m: datefmt['MM/YYYY' if m.group(1) else ('Mon YYYY' if m.group(4) else 'YYYY')]+=1
                    bl=e['bullets']
                    # kick paragraphs: split sentences when not a list
                    bpr.append(len(bl))
                    for b in bl:
                        btot+=1; blen.append(len(b)); bnum+= bool(re.search(r'\d',b)); long_b+= len(b)>240
                        pron+= bool(re.search(r"\b(I|my|me)\b",b))
                        t=re.sub(r'^[^A-Za-z]+','',b).split()
                        if t: fw[t[0].lower().strip('.,:;')]+=1
        words.append(w)
        for l in r.get('contact_labels',[]): labels[l]+=1
    print("sections per CV (median):",med(nsec),"| words per CV median:",med(words),"IQR",q(words,.25),q(words,.75))
    print("first section:",[(k,pct(v,n)) for k,v in first.most_common(4)])
    print("presence:",[(k,pct(v,n)) for k,v in pres.most_common(12)])
    print("education before experience:",pct(edu_before,both),f"(of {both})")
    print("top orders:"); [print("   ",pct(v,n),k) for k,v in order.most_common(6)]
    print("roles per CV median:",med(nroles),"| bullets/lines per role median:",med(bpr),"IQR",q(bpr,.25),q(bpr,.75))
    print("bullet length chars: median",med(blen),"IQR",q(blen,.25),q(blen,.75),"| >240 chars:",pct(long_b,btot))
    print("bullets with a digit:",pct(bnum,btot),f"(of {btot}) | with I/my/me:",pct(pron,btot))
    print("entries written as bullet lists:",pct(listfmt,ent_tot))
    print("summary length chars: median",med(sumlen),"IQR",q(sumlen,.25),q(sumlen,.75),"| has summary:",pct(len(sumlen),n))
    print("skills items median:",med(nsk))
    print("date format in role heads:",dict(datefmt))
    print("top first words:",[(k,pct(v,btot)) for k,v in fw.most_common(28)])
    print("first-word concentration: top10 share",pct(sum(v for k,v in fw.most_common(10)),btot),"| distinct",len(fw))
    print("other headings:",other.most_common(14))
    if labels: print("contact labels:",[(k,pct(v,n)) for k,v in labels.most_common(12)])
    if site=='enh':
        pg=C.Counter(r.get('pages') for r in R); cols=C.Counter(r.get('cols') for r in R)
        fonts=C.Counter(); size=C.Counter(); col=C.Counter()
        for r in R:
            if r['fonts']: fonts[max(r['fonts'],key=r['fonts'].get)]+=1
            if r['sizes_px']: size[max(r['sizes_px'],key=r['sizes_px'].get)]+=1
            cs=[c for c in r['colors'] if c not in('#000000','#000','#FFFFFF','#FFF')]
            if cs: col[max(cs,key=lambda c:r['colors'][c])]+=1
        print("pages:",dict(pg),"| columns:",dict(cols)); print("body font:",fonts.most_common(8)); print("body size px:",size.most_common(6)); print("accent colours:",col.most_common(8))
