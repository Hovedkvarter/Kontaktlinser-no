"""Own vector package illustrations; never manufacturer packaging artwork.

Run from the repository root. Product names/counts come from reviewed metadata.
These are deliberately stylized, with an embedded illustration label.
"""
from html import escape
from pathlib import Path

ITEMS = {
    'freshlook-oneday-30pk': ('FreshLook', ['ONE-DAY COLOR'], '30', 'linser', '#a95a87', '#f1deeb'),
    'myday-misight-1day-90pk': ('MyDay', ['MiSight 1 day'], '90', 'linser', '#52859a', '#d7edf2'),
    'clearlii-daily-90pk': ('Clearlii', ['Daily'], '90', 'linser', '#7964a2', '#eae3f3'),
    'clearlii-monthly-6pk': ('Clearlii', ['Hydrogel', 'Månedslinser'], '6', 'linser', '#7964a2', '#eae3f3'),
    'clearlii-vitamin-30pk': ('Clearlii', ['Vitamin'], '30', 'linser', '#7964a2', '#eae3f3'),
    'proclear-toric-3pk': ('Proclear', ['Toric'], '3', 'linser', '#b5794b', '#f4e5d7'),
    'proclear-multifocal-3pk': ('Proclear', ['Multifocal'], '3', 'linser', '#b5794b', '#f4e5d7'),
    'biofinity-toric-3pk': ('Biofinity', ['Toric'], '3', 'linser', '#528da2', '#dceef2'),
    'biofinity-multifocal-3pk': ('Biofinity', ['Multifocal'], '3', 'linser', '#528da2', '#dceef2'),
    'biofinity-xr-toric-6pk': ('Biofinity', ['XR Toric'], '6', 'linser', '#528da2', '#dceef2'),
    'optifree-express-120ml': ('Opti-Free', ['Express'], '120', 'ml', '#477b88', '#dcebed'),
}


def illustration(brand, lines, count, unit, accent, tint):
    title = escape(' '.join([brand] + lines + [count, unit]))
    variant = ''.join(f'<text x="135" y="{258+i*39}" font-size="31" fill="{accent}">{escape(line)}</text>' for i, line in enumerate(lines))
    # A generic illustrated carton, not a reconstruction of official packaging.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="540" viewBox="0 0 900 540" role="img" aria-labelledby="title desc">
<title id="title">Egen illustrasjon av {title}</title>
<desc id="desc">Ikke et ekte produktbilde. Emballasjens utforming og farger er illustrert.</desc>

<ellipse cx="447" cy="460" rx="343" ry="18" fill="#0b2545" opacity=".07"/>
<path d="M90 131 165 80 811 80 736 131Z" fill="#f9fbfc" stroke="#d6e0e6" stroke-width="2"/>
<path d="M736 131 811 80 811 381 736 432Z" fill="{tint}" stroke="#c8d4dc" stroke-width="2"/>
<path d="M90 131H736V432H90Z" fill="#f7fafb" stroke="#c8d4dc" stroke-width="2"/>
<path d="M90 131H736V145H90Z" fill="{accent}"/>
<path d="M736 131 811 80V94L736 145Z" fill="{accent}" opacity=".72"/>
<g font-family="Arial, sans-serif">
 <text x="688" y="113" text-anchor="end" font-size="15" letter-spacing="2" fill="#6b7e8a">EGEN ILLUSTRASJON</text>
 <text x="132" y="212" font-size="49" font-weight="600" fill="#153449">{escape(brand)}</text>
 {variant}
 <text x="135" y="379" font-size="48" font-weight="600" fill="#153449">{count}<tspan dx="12" font-size="23" font-weight="400">{unit}</tspan></text>
 <circle cx="624" cy="302" r="83" fill="{tint}"/>
 <circle cx="624" cy="302" r="59" fill="none" stroke="{accent}" stroke-width="2" opacity=".65"/>
 <circle cx="624" cy="302" r="42" fill="#fff" opacity=".8"/>
 <path d="M603 310Q624 325 645 310" fill="none" stroke="{accent}" stroke-width="2" opacity=".6"/>
 <text x="782" y="271" text-anchor="middle" transform="rotate(90 782 271)" font-size="15" letter-spacing="1.7" fill="#5a707d">ILLUSTRASJON</text>
</g>
</svg>'''


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'static/product-illustrations'
    out.mkdir(exist_ok=True)
    for product_id, args in ITEMS.items():
        (out / (product_id + '.svg')).write_text(illustration(*args), encoding='utf-8')
    print(f'Wrote {len(ITEMS)} own illustrations')
