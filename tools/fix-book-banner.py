from pathlib import Path
import re,json
root=Path(__file__).resolve().parents[1]
old='https://danie-poiret.github.io/banniere-nyons/'
new='https://agenda.vivreanyons.fr/banniere-livres/'
generator=root/'update_agenda.py';s=generator.read_text('utf8');before='BANNER_URL = "'+old+'"';after='BANNER_URL = "'+new+'"';assert s.count(before)==1;s=s.replace(before,after);generator.write_text(s,encoding='utf8')
count=0
for p in [root/'index.html',*(root/'evenements').rglob('index.html'),*(root/'semaines').rglob('index.html')]:
 s=p.read_text('utf8');pattern=r'(<iframe\b[^>]*\bsrc=[\"\'])'+re.escape(old)+r'([\"\'])';updated,n=re.subn(pattern,lambda m:m[1]+new+m[2],s)
 if n:p.write_text(updated,encoding='utf8');count+=1
assert count>100,count
assert new in (root/'evenements/quand-je-serai-grande-je-serai-patrick-swayze-2027-03-10/index.html').read_text('utf8')
print(json.dumps({'pages_banner_fixed':count,'generator_fixed':True,'new_banner':new}))
