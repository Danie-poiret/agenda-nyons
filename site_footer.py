"""Static footer links shared by the agenda, cinema and weekly pages."""
from pathlib import Path
import re

START = "<!-- AGENDA_FOOTER_LINKS_START -->"
END = "<!-- AGENDA_FOOTER_LINKS_END -->"
STYLE = '<style data-agenda-footer-style>.agenda-site-footer{padding:0 18px 24px}.agenda-footer-links{display:flex;flex-wrap:wrap;justify-content:center;gap:12px 22px;max-width:1060px;margin:22px auto 0;padding:20px;background:#2e3828;border-radius:12px;color:#fff;font:700 16px/1.5 Arial,sans-serif}.agenda-footer-links a{color:#fff;text-decoration:underline;text-underline-offset:3px}.agenda-footer-links a:hover{color:#f4dcab}.agenda-footer-links a:focus-visible{outline:2px solid #fff;outline-offset:4px}</style>'
LINKS = START + '<nav class="agenda-footer-links" aria-label="Les sites et pages de Vivre à Nyons"><a href="https://www.vivreanyons.fr/">Nyons accueil</a><a href="https://www.vivreanyons.fr/toutes-les-pages/">Toutes les pages</a><a href="https://agenda.vivreanyons.fr/">Agenda de Nyons</a><a href="https://agenda.vivreanyons.fr/cinema/">Cinéma à Nyons</a><a href="https://agenda.vivreanyons.fr/semaines/">Agenda par semaine</a><a href="https://drome.vivreanyons.fr/evenements/">Agenda Drôme</a></nav>' + END

def add_footer(source):
    if not re.search(r"<main(?:\s|>)", source, re.I):
        return source
    source = re.sub(re.escape(START) + r".*?" + re.escape(END), "", source, flags=re.S)
    if 'data-agenda-footer-style' not in source:
        source = re.sub(r"</head>", lambda m: STYLE + m[0], source, count=1, flags=re.I)
    if re.search(r"</footer>", source, re.I):
        source = re.sub(r"</footer>", lambda m: LINKS + m[0], source, count=1, flags=re.I)
    else:
        source = re.sub(r"</body>", lambda m: '<footer class="agenda-site-footer">' + LINKS + '</footer>' + m[0], source, count=1, flags=re.I)
    return source

def install_site_footer(root=None):
    root = Path(root or __file__).resolve()
    if root.is_file():
        root = root.parent
    count = 0
    for path in sorted(root.rglob("index.html")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        old = path.read_text(encoding="utf-8")
        new = add_footer(old)
        if new != old:
            path.write_text(new, encoding="utf-8")
            count += 1
        if re.search(r"<main(?:\s|>)", new, re.I):
            assert new.count(START) == 1, path
            assert new.count('data-agenda-footer-style') == 1, path
    print(f"Pied de page : {count} page(s) actualisée(s).")
    return count

if __name__ == "__main__":
    install_site_footer()
