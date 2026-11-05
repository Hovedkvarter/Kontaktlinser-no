from pathlib import Path
import json, sys, urllib.parse
from lxml import html, etree
from playwright.sync_api import sync_playwright
r=Path.cwd(); sys.path.insert(0,str(r/'site_generator'))
from price_guides import PRICE_GUIDES
build=r/'site_generator/build'
xml=etree.parse(str(r/'sitemap-guider.xml'))
targets=list(PRICE_GUIDES)
photos=Path('preview-images');photos.mkdir(exist_ok=True)
for n,slug in enumerate(targets,1):
    path=f'/guide/{slug}/'
    doc=html.fromstring((build/path.strip('/')/'index.html').read_text())
    assert len(doc.xpath('//h1'))==1
    assert doc.xpath('//link[@rel="canonical"]/@href')==['https://kontaktlinser.no'+path]
    assert doc.xpath('//meta[@name="description"]/@content')[0]
    assert len(xml.xpath('//*[local-name()="loc" and text()=$uri]',uri='https://kontaktlinser.no'+path))==1
    for container in [build/'index.html',build/'guider/index.html']:
        assert path in container.read_text()
    schemas=[json.loads(s) for s in doc.xpath('//script[@type="application/ld+json"]/text()')]
    assert {'Article','FAQPage','BreadcrumbList'}<={d['@type'] for d in schemas}
    for href in doc.xpath('//div[contains(@class,"price-study")]//a/@href'):
        assert href.startswith('/') and (build/href.strip('/')/'index.html').is_file(), href
    assert len(doc.xpath('//table'))>0
    print(slug,len(doc.xpath('//table//tbody/tr')), 'tabellrader, metadata og internlenker OK')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=__import__('shutil').which('google-chrome'),args=['--no-sandbox'])
    for width,height in [(320,780),(390,844),(1440,960)]:
        con=browser.new_context(viewport={'width':width,'height':height})
        con.route('**/*',lambda route:route.continue_() if urllib.parse.urlparse(route.request.url).hostname=='127.0.0.1' else route.abort())
        page=con.new_page()
        for n,slug in enumerate(targets,1):
            resp=page.goto(f'http://127.0.0.1:8117/guide/{slug}/',wait_until='networkidle')
            assert resp.status==200
            page.evaluate("document.fonts.ready")
            # Dismiss once as a reader would; all outbound traffic is disabled.
            btn=page.get_by_role('button',name='Kun nødvendige')
            if btn.count() and btn.first.is_visible(): btn.first.click()
            metrics=page.evaluate("""() => ({width:innerWidth,doc:document.documentElement.scrollWidth,
              tables:[...document.querySelectorAll('table')].map(t=>[t.scrollWidth,t.clientWidth]),
              image:document.querySelector('.guide-hero-thumb img').naturalWidth})""")
            assert metrics['doc']<=width and metrics['image']>0, metrics
            page.locator('table').first.scroll_into_view_if_needed()
            page.screenshot(path=photos/f'{n}-{width}-table.png')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=photos/f'{n}-{width}.png')
            print(width, n, metrics)
        con.close()
    browser.close()

from PIL import Image, ImageOps, ImageDraw
import base64, io
for width in (390,1440):
    w,h=(300,650) if width==390 else (480,320)
    sheet=Image.new('RGB',(w*3,h*2),(240,240,240))
    for col in range(3):
        for row,kind in enumerate(('', '-table')):
            with Image.open(photos/f'{col+1}-{width}{kind}.png') as screenshot:
                sheet.paste(ImageOps.contain(screenshot,(w,h)),(w*col,h*row))
    sheet.thumbnail((1100,900))
    output=io.BytesIO()
    sheet.save(output,'WEBP',quality=74)
    (photos/f'oversikt-{width}.webp').write_bytes(output.getvalue())
    encoded=base64.b64encode(output.getvalue()).decode()
    for offset in range(0,len(encoded),4000):
        print(f'PREVIEW_IMAGE_{width} '+encoded[offset:offset+4000])
