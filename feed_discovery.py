"""Feed-only discovery. Never changes product mappings, prices or published pages.
TD fullfeed contract: https://dev.tradedoubler.com/products/publisher/#unlimited
"""
import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
import requests

ROOT = Path(__file__).resolve().parent
HEADERS = {'User-Agent': 'kontaktlinser.no-feed-discovery/1.0'}
RELEVANT = re.compile(r'\b(?:kontaktlinse\w*|linse(?:r|[væe]ske\w*|etui\w*|beholder\w*)|contact lenses|lens case|øyedrå\w*|øyendrå\w*|øyegel\w*|øyesalve\w*|øyelokk\w*|øyemaske\w*|øyebad\w*|øyelapp\w*|opticlude|kompress øye|øyedråpeflaske|øyeskyll\w*|ögondropp\w*|eye drops|dry eyes|blepha\w*|hylo\w*|systane\w*|optive\w*|renu|aosept|ao sept|opti.?free|biotrue|medipearl|thealoz|evotears|posiforlid|desodrop|desosept|ocuvite|oxy[ai]l|blink contacts|blink intensive|clear.?eyes|drop.it|hyprosan|hyabak|vitapos|vit-a-pos|thea.?gel|soft clean)\b', re.I)
COSMETIC = re.compile(r'øyekrem|øyesmink|eye cream|eye makeup|mascara|eyeliner|eyeshadow|eyebrow|øyenbryn',re.I)
LENS_BRANDS = re.compile(r'\b(?:acuvue|biofinity|biomedics|dailies|air optix|proclear|purevision|soflens|clariti|myday|misight|avaira|miru|iwear|everclear|freshlook|clearcolor|supra 55|precision1|precision7)\b',re.I)


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def active_sources(config):
    for key, cfg in config.items():
        if key.startswith('$') or not isinstance(cfg, dict):
            continue
        if cfg.get('default_source') == 'affiliate_feed':
            yield key, cfg
        for brand, override in cfg.get('brand_overrides', {}).items():
            if override.get('source') == 'affiliate_feed':
                yield key+'--'+brand, dict(cfg, **override)


def td_url(cfg, endpoint='productsUnlimited.json'):
    original = cfg['feed_urls'][0]
    fid = re.search(r';fid=(\d+)', original).group(1)
    token = parse_qs(urlsplit(original).query)['token'][0]
    return f'https://api.tradedoubler.com/1.0/{endpoint};fid={fid}?token={token}'


def get(url):
    # Exception text can contain the access token: callers record only its class/status.
    response = requests.get(url, headers=HEADERS, timeout=(15, 120))
    response.raise_for_status()
    return response


def validate_td(data):
    if not isinstance(data, dict) or not isinstance(data.get('products'), list) or not data['products']:
        raise ValueError('Full feed missing products or empty; not a successful scan')
    return data['products']


def load_source(key, cfg, cache, offline=False):
    is_td = 'feed_urls' in cfg
    path = cache/(key+('.json' if is_td else '.csv'))
    stamp_path = cache/(key+'.stamp.json')
    if not offline:
        if is_td:
            stamp = get(td_url(cfg, 'productsUnlimited/lastUpdated.json')).json()
            if not stamp.get('lastUpdatedTime'):
                raise ValueError('Missing feed version')
            reuse = path.exists() and read_json(stamp_path) == stamp
            if not reuse:
                response = get(td_url(cfg))
                data = response.json()
                # The provider creates a first fullfeed asynchronously. Retry once.
                if data.get('message') and 'products' not in data:
                    time.sleep(30)
                    response = get(td_url(cfg)); data = response.json()
                validate_td(data)
                path.write_bytes(response.content)
                stamp_path.write_text(json.dumps(stamp))
        elif 'feed_url' in cfg:
            response = get(cfg['feed_url'])
            # Do not overwrite a usable cache with an HTML error page returned as 200.
            if not {'id','title','link'}.issubset(csv.DictReader(io.StringIO(response.text)).fieldnames or []):
                raise ValueError('Unexpected CSV schema')
            path.write_text(response.text, encoding='utf-8')
        else:
            raise ValueError('No supported live feed URL')
    if is_td:
        products=validate_td(read_json(path))
        rows=[]
        for p in products:
            for o in p.get('offers', []):
                price=(o.get('priceHistory') or [{}])[0].get('price', {})
                rows.append(dict(sku=str(o.get('sourceProductId') or ''), name=p.get('name',''),
                    category=' | '.join(c.get('name') or c.get('tdCategoryName','') for c in p.get('categories',[])),
                    description=p.get('description',''), brand=p.get('brand',''),
                    price=price.get('value'), currency=price.get('currency'), availability=o.get('availability',''),
                    url=o.get('productUrl',''), image_url=(p.get('productImage') or {}).get('url',''),
                    gtin=(p.get('identifiers') or {}).get('ean','')))
    else:
        reader=csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig')))
        if not {'id','title','link'}.issubset(reader.fieldnames or []):
            raise ValueError('Unexpected CSV schema')
        rows=[dict(sku=r['id'],name=r['title'],category=r.get('product_type',''),description=r.get('description',''),
            brand=r.get('brand',''),price=r.get('sale_price') or r.get('price'),currency='NOK',
            availability=r.get('availability',''),url=r.get('link',''),image_url=r.get('image_link',''),gtin=r.get('gtin','')) for r in reader]
    if not rows or any(not r['sku'] or not r['name'] for r in rows):
        raise ValueError('Empty feed or missing row identifiers')
    unique={}
    for r in rows:
        if r['sku'] in unique and unique[r['sku']] != r:
            raise ValueError('Conflicting duplicate SKU')
        unique[r['sku']]=r
    return list(unique.values())


def destination(url):
    match=re.search(r'url\((.*)\)$',url)
    if match: url=unquote(match.group(1))
    else:
        q=parse_qs(urlsplit(url).query)
        if q.get('url'):url=q['url'][0]
    parts=urlsplit(url)
    return parts.scheme+'://'+parts.netloc+parts.path if parts.scheme in ('http','https') else ''


def normal_name(name):
    name=unicodedata.normalize('NFKC',html.unescape(name)).lower()
    name=name.replace('1-day','1 day').replace('1day','1 day').replace('purevision2','purevision 2')
    name=re.sub(r'\b(\d+)\s*(?:pack|pk|pakk|stk|p)\b',r'\1 pack',name)
    return re.sub(r'[^\w]+','',name)


def relevant(row, mapped=False):
    if mapped:return True
    title=row['name'];cat=row['category']
    if COSMETIC.search(title) or re.search(r'kosmetikk|hudpleie|dyre|intim|bind & tamponger',cat,re.I):return False
    if re.search(r'kontaktlinser\s*>\s*briller',cat,re.I):return False
    if re.search(r'^(?:Kontaktlinser|Linser|Contact Lenses)(?:\s*[>|]|$)',cat,re.I):return True
    if re.search(r'(?:^|>)\s*(?:Øyne|Øyedråper|Øyendråper|Ögon)\s*(?:>|$)',cat,re.I):return True
    return bool(RELEVANT.search(title) or LENS_BRANDS.search(title))


def group(row):
    if re.search(r'linseetui|lens case|øyemaske|eye mask|medipearl|kompress|øyelapp|dråpeflaske',row['name'],re.I):return 'Tilbehør'
    if re.search(r'blepha|øyelokk|desosept|eye wipes|eye spray',row['name'],re.I):return 'Øyelokkspleie'
    if re.search(r'^\s*(?:kontaktlinser|linser|contact lenses|lenses)(?:\s*[>|]|$)',row['category'],re.I) and not re.search(r'væske|solution',row['category'],re.I):return 'Kontaktlinser'
    if re.search(r'(?:Linser|Kontaktlinser|Contact Lenses).*?(?:dags|tor|måned|linser|lenses)|\b(?:iwear|supra 55)',row['category']+' '+row['name'],re.I) and not RELEVANT.search(row['name']):return 'Kontaktlinser'
    if LENS_BRANDS.search(row['name']) and not re.search(r'solution|refresh|clean',row['name'],re.I):return 'Kontaktlinser'
    if re.search(r'væske|solution|renu|aosept|ao sept|opti.?free|saline|soft clean',row['name'],re.I):return 'Linsevæske'
    if re.search(r'kaps|tablett|ocuvite|kosttilskudd',row['name'],re.I):return 'Kosttilskudd – vurder relevans'
    return 'Øyepleie – vurder variant'


def suggestions(row, products):
    name=normal_name(row['name'])
    exact=[p for p in products if normal_name(p['name'])==name]
    if exact:return 'Mulig eksisterende produkt', exact[:3]
    # Hints only: pack sizes, toric/multifocal, formulation and aliases MUST be reviewed.
    scores=sorted([(SequenceMatcher(None,name,normal_name(p['name'])).ratio(),p) for p in products],key=lambda x:x[0],reverse=True)
    generic={'day','pack','stk','ml','gram','for','with','thea','bausch','lomb','øye','øyedråper','øyegel','eye','care','drops','duo','1','3','6','10','30','60','90'}
    def words(text):
        return {w for w in re.findall(r'[^\W\d_]+',text.lower()) if w not in generic and len(w)>2}
    near=[p for score,p in scores if score>=0.66 and words(row['name']) & words(p['name'])][:3]
    return ('Avklar variant/pakning' if near else 'Ny produktkandidat'),near


def fingerprint(row):
    fields={k:row.get(k) for k in ['name','category','brand','gtin','url']}
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()[:16]


def audit(config, matching, products, previous, decisions, cache, offline=False):
    now=datetime.now(timezone.utc).isoformat()
    by_id={p['id']:p for p in products}
    old={r['key']:r for r in previous.get('candidates',[])}
    candidates=[];sources=[];seen=set()
    for key,cfg in active_sources(config):
        source={'key':key,'name':cfg.get('display_name',key),'network':cfg['network'],'status':'ok'}
        prior=next((s for s in previous.get('sources',[]) if s['key']==key),{})
        previous_count=prior.get('last_success_rows',prior.get('rows',0))
        try:
            rows=load_source(key,cfg,cache,offline)
            if previous_count and len(rows)<previous_count*0.5:
                raise ValueError('Feed row count collapsed below 50%')
        except Exception as error:
            source.update(status='error',last_success_rows=previous_count,error=type(error).__name__+(f' HTTP {error.response.status_code}' if isinstance(error,requests.HTTPError) else ''))
            # Preserve candidates during outages instead of falsely marking them removed.
            candidates.extend(dict(r,observation='Ikke kontrollert – feedfeil') for r in old.values() if r['source']==key)
            sources.append(source);continue
        match=matching.get(cfg['network'],{})
        source.update(rows=len(rows),last_success_rows=len(rows),relevant=0,mapped=0,candidates=0)
        for row in rows:
            mapped=match.get(row['sku'],[]);mapped=[mapped] if isinstance(mapped,str) else mapped
            if not relevant(row,bool(mapped)):continue
            source['relevant']+=1
            if mapped and all(pid in by_id for pid in mapped):
                source['mapped']+=1;continue
            source['candidates']+=1
            item_key=key+':'+row['sku'];seen.add(item_key)
            kind,near=suggestions(row,products)
            if mapped:kind='Kobling peker på upublisert produkt'
            row['url']=destination(row['url'])
            sig=fingerprint(row);last=old.get(item_key,{})
            decision=decisions.get(item_key,{})
            decision_valid=decision.get('fingerprint')==sig
            raw_price=str(row['price'] or '');num=re.search(r'\d+(?:[.,]\d+)?',raw_price)
            item={k:row[k] for k in ['sku','name','category','brand','availability','url','image_url','gtin','currency']}
            item.update(key=item_key,source=key,retailer=source['name'],group=group(row),kind=kind,
                price=float(num.group().replace(',','.')) if num else None,
                suggestions=[{'id':p['id'],'name':p['name']} for p in near],fingerprint=sig,
                first_seen=last.get('first_seen',now),last_seen=now,
                observation='Ny' if not last else ('Endret' if last.get('fingerprint')!=sig else 'Uendret'),
                review_status=decision.get('status','Åpen') if decision_valid else 'Åpen',
                review_note=decision.get('note','') if decision_valid else '',
                review_family=decision.get('family',row['name']) if decision_valid else row['name'])
            candidates.append(item)
        source['excluded']=source['rows']-source['relevant']
        sources.append(source)
    ok={s['key'] for s in sources if s['status']=='ok'}
    resolved=[{'key':key,'name':row['name'],'reason':'Koblet eller ikke lenger relevant/til stede i feed'} for key,row in old.items() if row['source'] in ok and key not in seen]
    return dict(checked_at=now,complete=all(s['status']=='ok' for s in sources),sources=sources,
        candidates=sorted(candidates,key=lambda r:(r['group'],r['name'].casefold(),r['source'])),resolved=resolved)


def markdown(report):
    def esc(s):return html.escape(str(s)).replace('|','&#124;').replace('\n',' ')
    lines=['# Feedkontroll – kontaktlinser.no','',f"Kontrollert: {report['checked_at']}",
        '', 'Kun affiliate-feeds. Kandidater er feed-rader, ikke antall nye unike produkter. Ingen automatisk publisering eller kobling.',
        '', 'Navnelikhet er et vurderingsforslag. Pakning, variant og produktidentitet må bekreftes før publisering.',
        '', '| Feed | Status | Rader | Relevante | Koblet | Til vurdering |','|---|---|---:|---:|---:|---:|']
    for s in report['sources']:
        lines.append('| '+' | '.join(esc(s.get(k,'—')) for k in ['name','status','rows','relevant','mapped','candidates'])+' |')
    changes=Counter(r['observation'] for r in report['candidates'])
    lines+=['',f"Nye rader: {changes['Ny']}. Endrede rader: {changes['Endret']}. Ikke lenger på kandidatlisten: {len(report['resolved'])}."]
    lines+=['','## Kandidater','', '| Feed | Produkt | Gruppe | Vurdering | Mulige eksisterende | Endring |','|---|---|---|---|---|---|']
    for r in report['candidates']:
        lines.append('| '+' | '.join(esc(x) for x in [r['retailer'],r['name'],r['group'],r['review_status']+' – '+(r['review_note'] or r['kind']),', '.join(p['name'] for p in r['suggestions']),r['observation']])+' |')
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,default=ROOT/'.feed-discovery-cache');parser.add_argument('--offline',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'reports/feed-discovery');args=parser.parse_args()
    args.cache.mkdir(parents=True,exist_ok=True);args.output.mkdir(parents=True,exist_ok=True)
    previous=read_json(args.output/'latest.json',{})
    report=audit(read_json(ROOT/'sources_config.json'),read_json(ROOT/'product_matching.json'),
        read_json(ROOT/'site_generator/catalog_live.json')['products'],previous,
        read_json(ROOT/'feed_discovery_review.json',{}),args.cache,args.offline)
    (args.output/'latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (args.output/'latest.md').write_text(markdown(report))
    print(json.dumps({'complete':report['complete'],'sources':report['sources'],'candidates':len(report['candidates'])},ensure_ascii=False))
    return 0 if report['complete'] else 1

if __name__=='__main__':sys.exit(main())
