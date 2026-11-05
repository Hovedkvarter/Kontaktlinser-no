from pathlib import Path
import base64, io, json, shutil
from urllib.parse import urlsplit
from lxml import html
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright
build=Path('site_generator/build')
out=Path('preview-images');out.mkdir(exist_ok=True)
pages={
 'linse-sitter-fast-i-oyet': ['/oyedraper/'],
 'vedlikehold-av-kontaktlinser': ['/tilbehor/','/linsevaeske/'],
 'manedslinser-vs-dagslinser': ['/linsevaeske/'],
 'reising-med-kontaktlinser': ['/linsevaeske/','/oyedraper/'],
 'kan-man-dusje-med-kontaktlinser': ['/linsevaeske/'],
 'kjope-kontaktlinser-for-tre-seks-eller-tolv-maneder': ['/linsevaeske/'],
}
for slug,targets in pages.items():
 doc=html.fromstring((build/'guide'/slug/'index.html').read_text())
 body=doc.xpath('//div[@style="max-width:640px;"]')[0]
 for dst in targets:
  assert body.xpath('.//a[@href=$dst]',dst=dst), (slug,dst)
  assert (build/dst.strip('/')/'index.html').exists()
 schemas=[json.loads(t) for t in doc.xpath('//script[@type="application/ld+json"]/text()')]
 article=next(s for s in schemas if s.get('@type')=='Article')
 assert article['dateModified']=='2026-11-05'
 assert doc.xpath('//link[@rel="canonical"]/@href')==['https://kontaktlinser.no/guide/'+slug+'/']
 print(slug,targets)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=shutil.which('google-chrome'),args=['--no-sandbox'])
 for width,height in [(375,812),(1440,900)]:
  ctx=browser.new_context(viewport={'width':width,'height':height})
  ctx.route('**/*',lambda r:r.continue_() if urlsplit(r.request.url).hostname=='127.0.0.1' else r.abort())
  tab=ctx.new_page()
  for i,(s,dst) in enumerate(pages.items()):
   assert tab.goto('http://127.0.0.1:8117/guide/'+s+'/',wait_until='networkidle').status==200
   b=tab.get_by_role('button',name='Kun nødvendige'); 
   if b.count() and b.first.is_visible(): b.first.click()
   target=tab.locator('div[style="max-width:640px;"] a[href="'+dst[0]+'"]').first
   target.evaluate("e=>e.scrollIntoView({block:'center'})")
   assert target.is_visible() and tab.evaluate('document.documentElement.scrollWidth')<=width
   if i<2: tab.screenshot(path=out/f'{width}-{i}.png')
   target.click(); assert urlsplit(tab.url).path==dst[0]
  ctx.close()
 browser.close()
for width in [375,1440]:
 sheet=Image.new('RGB',(600,640) if width==375 else (960,310),'white')
 for i in range(2):
  im=ImageOps.contain(Image.open(out/f'{width}-{i}.png'),(sheet.width//2,sheet.height))
  sheet.paste(im,(sheet.width//2*i,0))
 stream=io.BytesIO();sheet.save(stream,'WEBP',quality=85)
 val=base64.b64encode(stream.getvalue()).decode('ascii')
 for off in range(0,len(val),4000): print(f'GUIDE_IMAGE_{width} '+val[off:off+4000])
print('12 nettleserscenarier bestod.')
