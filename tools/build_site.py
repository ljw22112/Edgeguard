"""site/page.html (the artifact body) -> site/index.html (a standalone page for GitHub Pages or any web server)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
body = open(os.path.join(ROOT, "site", "page.html"), encoding="utf-8").read()
head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n')
open(os.path.join(ROOT, "site", "index.html"), "w", encoding="utf-8").write(head + body + "\n</body>\n</html>\n")
print("site/index.html written")
