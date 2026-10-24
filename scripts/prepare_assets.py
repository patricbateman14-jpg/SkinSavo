"""Vendor Steam CDN artwork for existing products; never seed or alter stock."""
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((Path(os.environ['TEMP']) / 'skinsavo-artwork.json').read_text(encoding='utf-8'))
conn = sqlite3.connect(ROOT / 'skinsavo.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT id,name,image FROM skins').fetchall()
print('Existing catalog records:', len(rows))
assets = ROOT / 'static' / 'assets'
assets.mkdir(exist_ok=True)
manifest = {}
sources = {}
def download(name, filename):
    normalized = name.replace('★ ', '').strip()
    match = next((x for x in data if x['name'].replace('★ ', '').strip() == normalized), None)
    if not match:
        print('No matching artwork:', name)
        return
    path = assets / filename
    if not path.exists():
        urllib.request.urlretrieve(match['image'], path)
    manifest[name] = '/static/assets/' + filename
    sources[filename] = {'item': name, 'source': match['image']}
for row in rows:
    download(row['name'], f"skin-{row['id']}.png")
download('AK-47 | Redline', 'hero-redline.png')
(assets / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
(assets / 'sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
print('Vendored artwork:', len(sources))
