#!/usr/bin/env python3
"""
Static-site generator for Vertex Society.

Reads the WordPress export (WXR) in this directory and produces a self-contained
static website (plain HTML + one CSS file) suitable for free GitHub Pages hosting.

Run:  python3 build.py
Output: index.html and per-page /<path>/index.html folders at the repo root,
        plus assets/ (css, images). Safe to re-run; it overwrites generated pages.

The two Jetpack contact forms (Application, Contact) are re-created as plain HTML
forms that POST to Google Forms. Fill in the placeholders marked GOOGLE_FORM_*
after you create the matching Google Form (see README.md).
"""
import re, os, glob, html

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE_NAME = "Vertex Society"
SITE_DESC = "Fellows Society For Exceptionally And Profoundly Gifted"

# ----------------------------------------------------------------------------
# 1. Parse the export
# ----------------------------------------------------------------------------
def load_export():
    xmls = glob.glob(os.path.join(ROOT, "*.xml"))
    assert xmls, "No WordPress export .xml found in repo root"
    xml = max(xmls, key=os.path.getmtime)
    data = open(xml, encoding="utf-8").read()
    items = re.findall(r"<item>.*?</item>", data, re.S)
    pages = {}
    for it in items:
        def cd(tag):
            m = re.search(rf"<{tag}><!\[CDATA\[(.*?)\]\]></{tag}>", it, re.S)
            return m.group(1) if m else ""
        def fd(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", it, re.S)
            return m.group(1) if m else ""
        if cd("wp:post_type") != "page":
            continue
        pid = int(fd("wp:post_id"))
        pages[pid] = {
            "id": pid,
            "parent": int(fd("wp:post_parent") or 0),
            "order": int(fd("wp:menu_order") or 0),
            "status": cd("wp:status"),
            "slug": cd("wp:post_name"),
            "title": cd("title") or fd("title"),
            "content": cd("content:encoded"),
        }
    return pages

# ----------------------------------------------------------------------------
# 2. Routing: give every page a clean output directory (site-root relative)
# ----------------------------------------------------------------------------
# Clean slug overrides (the WP "About" page slug is the ugly "about-2", etc.)
SLUG_OVERRIDE = {
    30: "about",
    25: "",   # Home is the front page -> site root
    501: "we-are-gathered",
}

# Old permalink -> page id. WordPress kept these working via _wp_old_slug
# redirects; a static site has no redirects, so map them explicitly.
PERMALINK_ALIAS = {
    "fellows/vittorio-emanuel-lestat": 68,
}

def build_routes(pages):
    def clean_slug(p):
        return SLUG_OVERRIDE.get(p["id"], p["slug"])
    def out_dir(pid, _seen=None):
        p = pages[pid]
        cs = clean_slug(p)
        if pid == 25:
            return ""  # home at root
        if p["parent"] and p["parent"] in pages:
            parent_dir = out_dir(p["parent"])
            return f"{parent_dir}{cs}/"
        return f"{cs}/"
    routes = {}          # pid -> output dir ("tests/", "", "fellows/olivier-r/")
    wp_perma = {}        # wp permalink path (no slashes) -> pid  (for link rewriting)
    for pid, p in pages.items():
        routes[pid] = out_dir(pid)
        # WP permalink uses the raw wp slugs of the ancestry
        parts, cur = [], pid
        while cur and cur in pages:
            parts.append(pages[cur]["slug"])
            cur = pages[cur]["parent"]
        wp_perma["/".join(reversed(parts)).strip("/")] = pid
    return routes, wp_perma

# ----------------------------------------------------------------------------
# 3. Link / image rewriting  ->  paths relative to each page
# ----------------------------------------------------------------------------
def rel_prefix(out_dir):
    """'../' * depth so links resolve at any base path (subfolder or root)."""
    depth = out_dir.count("/")
    return "../" * depth

def make_link_rewriter(routes, wp_perma, pages):
    id_dir = routes
    def resolve_internal(path):
        """Return site-root-relative output dir for an internal WP path, or None."""
        norm = path.strip("/")
        # images under wp-content -> local assets
        m = re.search(r"/wp-content/uploads/.*/([^/]+\.(?:jpg|jpeg|png|gif|webp|svg))$", "/" + norm, re.I)
        if m:
            return f"assets/img/{m.group(1)}"
        if norm == "" :
            return ""  # home
        if norm in PERMALINK_ALIAS:
            return id_dir[PERMALINK_ALIAS[norm]]
        if norm in wp_perma:
            return id_dir[wp_perma[norm]]
        # try matching by clean output dirs directly
        for pid, d in id_dir.items():
            if d.strip("/") == norm:
                return d
        # single-segment slug (e.g. "tests", "fellows") -> match any page slug
        for pid, p in pages.items():
            if p["slug"] == norm:
                return id_dir[pid]
        return None

    def rewrite(href, prefix):
        raw = href
        # strip the old site domain
        href = re.sub(r"^https?://vertexsociety\.wordpress\.com", "", href)
        href = re.sub(r"^https?://(www\.)?vertexsociety\.org(/main)?", "", href)
        if href.startswith("http://") or href.startswith("https://") or href.startswith("mailto:") or href.startswith("#"):
            return raw  # external / anchor -> leave as-is
        if not href.startswith("/"):
            return raw  # already relative, leave
        target = resolve_internal(href)
        if target is None:
            return raw
        if target.startswith("assets/"):
            return prefix + target
        return prefix + target  # target already ends with "/" (dir) or is "" (home)
    return rewrite

def apply_rewrites(body, prefix, rewrite):
    def repl_attr(m):
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        return f'{attr}={quote}{rewrite(url, prefix)}{quote}'
    body = re.sub(r'(href|src)=(["\'])(.*?)\2', repl_attr, body)
    return body

# ----------------------------------------------------------------------------
# 4. wpautop  (mimic WordPress paragraph handling for classic-editor content)
# ----------------------------------------------------------------------------
BLOCK = (r"table|thead|tfoot|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|pre|form|"
         r"blockquote|address|p|h[1-6]|hr|fieldset|section|article|aside|"
         r"header|footer|nav|figure|figcaption|details|summary|iframe|img")

def strip_gutenberg(text):
    return re.sub(r"<!--\s*/?wp:.*?-->", "", text)

def wpautop(text):
    text = strip_gutenberg(text).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        return ""
    chunks = re.split(r"\n\s*\n", text)
    out = []
    for c in chunks:
        c = c.strip("\n")
        if not c.strip():
            continue
        if re.match(r"^\s*<(?:" + BLOCK + r")[\s>/]", c, re.I) or c.lstrip().startswith("<!--"):
            out.append(c)
        else:
            out.append("<p>" + c.replace("\n", "<br>\n") + "</p>")
    return "\n\n".join(out)

# ----------------------------------------------------------------------------
# 5. Contact-form shortcode  ->  Google-Forms-connected HTML form
# ----------------------------------------------------------------------------
def parse_contact_fields(shortcode):
    fields = []
    for fm in re.finditer(r"\[contact-field\s+(.*?)\]", shortcode, re.S):
        attrs = dict(re.findall(r"(\w+)\s*=\s*['\"]([^'\"]*)['\"]", fm.group(1)))
        fields.append(attrs)
    return fields

def field_key(label):
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")

def render_google_form(fields, form_slug):
    """form_slug: 'application' or 'contact' -> distinct placeholder namespace."""
    action_token = f"GOOGLE_FORM_ACTION_{form_slug.upper()}"
    iframe = f"gform_target_{form_slug}"
    rows = []
    mapping_comment = ["    <!-- Google Form field mapping — replace each entry.REPLACE_* "
                       "with the real entry.<id> from your Google Form:"]
    for f in fields:
        label = f.get("label", "").strip()
        ftype = f.get("type", "text")
        required = f.get("required", "") in ("1", "true", "yes")
        key = field_key(label)
        name = f"entry.REPLACE_{form_slug}_{key}"
        mapping_comment.append(f"         {label!r:45} -> {name}")
        req_attr = " required" if required else ""
        star = ' <span class="req">*</span>' if required else ""
        fid = f"f_{form_slug}_{key}"
        if ftype == "textarea":
            control = f'<textarea id="{fid}" name="{name}" rows="5"{req_attr}></textarea>'
        elif ftype == "email":
            control = f'<input id="{fid}" type="email" name="{name}"{req_attr}>'
        elif ftype == "url":
            control = f'<input id="{fid}" type="url" name="{name}">'
        elif ftype == "radio":
            opts = [o.strip() for o in f.get("options", "").split(",") if o.strip()]
            radios = "".join(
                f'<label class="radio"><input type="radio" name="{name}" '
                f'value="{html.escape(o)}"{req_attr if i==0 else ""}> {html.escape(o)}</label>'
                for i, o in enumerate(opts))
            control = f'<div class="radio-group">{radios}</div>'
        else:  # name / text / anything else
            control = f'<input id="{fid}" type="text" name="{name}"{req_attr}>'
        rows.append(
            f'    <div class="field">\n'
            f'      <label for="{fid}">{html.escape(label)}{star}</label>\n'
            f'      {control}\n'
            f'    </div>')
    mapping_comment.append("    -->")
    mapping = "\n".join(mapping_comment)
    body = "\n".join(rows)
    return f"""{mapping}
    <form class="vx-form" action="{action_token}" method="POST"
          target="{iframe}" onsubmit="this.dataset.sent='1';">
{body}
      <div class="field">
        <button type="submit">Submit</button>
      </div>
      <p class="form-note"><span class="req">*</span> required</p>
    </form>
    <iframe name="{iframe}" style="display:none" title="hidden"
            onload="var f=document.querySelector('form[target=&quot;{iframe}&quot;]');
                    if(f&&f.dataset.sent){{f.style.display='none';
                    document.getElementById('thanks_{form_slug}').style.display='block';}}"></iframe>
    <div id="thanks_{form_slug}" class="form-thanks" style="display:none">
      <h2>Thank you</h2>
      <p>Your submission has been received. You will be contacted shortly.</p>
    </div>"""

def render_form_page(page, routes, wp_perma, pages, rewrite):
    content = page["content"]
    m = re.search(r"\[contact-form.*?\[/contact-form\]", content, re.S)
    before = wpautop(content[:m.start()]) if m else wpautop(content)
    after = wpautop(content[m.end():]) if m else ""
    fields = parse_contact_fields(m.group(0)) if m else []
    slug = "application" if page["slug"] == "application" else "contact"
    form_html = render_google_form(fields, slug)
    return before + "\n" + form_html + "\n" + after

# ----------------------------------------------------------------------------
# 6. Template
# ----------------------------------------------------------------------------
NAV = [  # (label, target page id)
    ("Home", 25), ("About", 30), ("Admission", 31),
    ("Fellows", 32), ("Tests", 33), ("Contact", 199),
]
FOOTER = [("Dedication", 504), ("FAQ", 79), ("Distinguished Fellows Selection", 294)]

def nav_html(routes, prefix, current_id):
    out = []
    for label, pid in NAV:
        d = routes[pid]
        href = prefix + d if d else (prefix or "./")
        cls = ' class="active"' if pid == current_id else ""
        out.append(f'<a{cls} href="{href}">{label}</a>')
    return "\n".join(out)

def footer_html(routes, prefix):
    out = []
    for label, pid in FOOTER:
        d = routes[pid]
        href = prefix + d if d else (prefix or "./")
        out.append(f'<a href="{href}">{label}</a>')
    return " · ".join(out)

def page_template(title, body, prefix, routes, current_id):
    home = prefix or "./"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — {SITE_NAME}</title>
<meta name="description" content="{SITE_DESC}">
<link rel="icon" href="{prefix}assets/img/logo.png">
<link rel="stylesheet" href="{prefix}assets/css/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="container header-inner">
    <a class="brand" href="{home}">
      <img class="brand-logo" src="{prefix}assets/img/logo.png" alt="">
      <span class="brand-name">{SITE_NAME}</span>
    </a>
    <input type="checkbox" id="navtoggle" class="navtoggle">
    <label for="navtoggle" class="navtoggle-btn" aria-label="Menu">≡</label>
    <nav class="site-nav">
{nav_html(routes, prefix, current_id)}
    </nav>
  </div>
</header>
<main id="main" class="container content">
{body}
</main>
<footer class="site-footer">
  <div class="container">
    <p class="footer-tag">{SITE_NAME} — {SITE_DESC}. Founded 2006.</p>
    <p class="footer-links">{footer_html(routes, prefix)}</p>
  </div>
</footer>
</body>
</html>
"""

# ----------------------------------------------------------------------------
# 7. Home page (WP front page has no content) — compose a landing page
# ----------------------------------------------------------------------------
def home_body(pages, routes, prefix):
    quote = wpautop(pages[501]["content"]) if 501 in pages else ""
    intro_src = pages[30]["content"] if 30 in pages else ""
    first_para = intro_src.split("\n\n")[0] if intro_src else ""
    intro = wpautop(first_para)
    def link(pid, label):
        d = routes[pid]
        return f'<a class="btn" href="{(prefix + d) if d else (prefix or "./")}">{label}</a>'
    return f"""<section class="hero">
  <img class="hero-logo" src="{prefix}assets/img/logo.png" alt="">
  <h1>{SITE_NAME}</h1>
  <p class="hero-tag">{SITE_DESC}</p>
</section>
<section class="home-quote">
{quote}
</section>
<section class="home-intro">
{intro}
</section>
<section class="home-cta">
  {link(31,"Admission")}
  {link(33,"Qualifying Tests")}
  {link(32,"Fellows")}
</section>
"""

# ----------------------------------------------------------------------------
# 8. CSS
# ----------------------------------------------------------------------------
CSS = r""":root{
  --ink:#1c2230; --muted:#5a6376; --bg:#ffffff; --soft:#f4f5f8;
  --line:#e2e5ec; --accent:#3a4a7a; --accent-dark:#26325a; --maxw:820px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;font-family:Georgia,"Times New Roman",serif;color:var(--ink);
  background:var(--bg);line-height:1.65;font-size:18px}
.container{max-width:var(--maxw);margin:0 auto;padding:0 20px}
.content{padding:38px 20px 60px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
img{max-width:100%;height:auto}
h1,h2,h3{line-height:1.25;color:var(--accent-dark);font-weight:600}
h2{margin-top:1.8em;border-bottom:1px solid var(--line);padding-bottom:.3em}
p{margin:0 0 1.1em}
ul,ol{margin:0 0 1.1em;padding-left:1.4em}
li{margin:.25em 0}
.skip{position:absolute;left:-999px}
.skip:focus{left:8px;top:8px;background:#fff;padding:8px;z-index:10}

/* header */
.site-header{background:var(--accent-dark);color:#fff;position:sticky;top:0;z-index:5}
.header-inner{display:flex;align-items:center;gap:16px;min-height:64px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;color:#fff;font-weight:600}
.brand:hover{text-decoration:none}
.brand-logo{width:34px;height:34px}
.brand-name{font-size:1.15rem;letter-spacing:.02em}
.site-nav{margin-left:auto;display:flex;gap:20px;flex-wrap:wrap}
.site-nav a{color:#d7ddf0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  font-size:.95rem;letter-spacing:.02em}
.site-nav a:hover,.site-nav a.active{color:#fff;text-decoration:none}
.navtoggle,.navtoggle-btn{display:none}

/* home */
.hero{text-align:center;padding:34px 0 8px}
.hero-logo{width:96px;height:96px}
.hero h1{font-size:2.4rem;margin:.35em 0 .1em}
.hero-tag{color:var(--muted);font-style:italic;font-size:1.15rem;margin:0}
.home-quote{font-size:1.2rem;text-align:center;color:var(--accent-dark);
  max-width:640px;margin:28px auto;font-style:italic}
.home-intro{color:var(--ink)}
.home-cta{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin:30px 0 10px}
.btn{display:inline-block;background:var(--accent);color:#fff;padding:12px 22px;border-radius:4px;
  font-family:system-ui,sans-serif;font-size:1rem}
.btn:hover{background:var(--accent-dark);text-decoration:none}

/* misc content helpers carried from the old theme */
.largefont{font-size:1.08rem}
ol.membersclass,ul.regular,ol.olnumbers{}
ol.membersclass li{margin:.35em 0}

/* forms */
.vx-form{margin:1.5em 0;max-width:640px}
.vx-form .field{margin-bottom:1.1em}
.vx-form label{display:block;font-family:system-ui,sans-serif;font-size:.95rem;
  font-weight:600;margin-bottom:.35em;color:var(--accent-dark)}
.vx-form input[type=text],.vx-form input[type=email],.vx-form input[type=url],
.vx-form textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:4px;
  font:inherit;font-size:1rem;background:var(--soft)}
.vx-form textarea{resize:vertical}
.vx-form .radio-group{display:flex;gap:18px;flex-wrap:wrap}
.vx-form label.radio{font-weight:400;display:inline-flex;align-items:center;gap:6px}
.vx-form button{background:var(--accent);color:#fff;border:0;padding:12px 28px;border-radius:4px;
  font-family:system-ui,sans-serif;font-size:1rem;cursor:pointer}
.vx-form button:hover{background:var(--accent-dark)}
.req{color:#b23}
.form-note{font-family:system-ui,sans-serif;font-size:.85rem;color:var(--muted)}
.form-thanks{background:var(--soft);border:1px solid var(--line);padding:20px;border-radius:6px}

/* footer */
.site-footer{background:var(--soft);border-top:1px solid var(--line);
  margin-top:40px;padding:26px 0;color:var(--muted)}
.footer-tag{margin:0 0 .4em;font-size:.95rem}
.footer-links{margin:0;font-family:system-ui,sans-serif;font-size:.9rem}

@media(max-width:680px){
  body{font-size:17px}
  .navtoggle-btn{display:inline-block;margin-left:auto;font-size:1.6rem;
    cursor:pointer;color:#fff;line-height:1;padding:4px 8px}
  .site-nav{display:none;flex-direction:column;width:100%;gap:10px;padding:10px 0 4px;margin:0}
  .navtoggle:checked ~ .site-nav{display:flex}
}
"""

# ----------------------------------------------------------------------------
# 9. Build
# ----------------------------------------------------------------------------
def write(path, text):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w", encoding="utf-8").write(text)

def main():
    pages = load_export()
    routes, wp_perma = build_routes(pages)
    rewrite = make_link_rewriter(routes, wp_perma, pages)

    os.makedirs(os.path.join(ROOT, "assets/css"), exist_ok=True)
    write("assets/css/style.css", CSS)
    write(".nojekyll", "")

    # 404 page — served at site root for any unknown path, so it uses
    # absolute "/" links (correct for a <owner>.github.io root site).
    nf_body = """<section class="hero" style="padding-top:10px">
  <img class="hero-logo" src="/assets/img/logo.png" alt="">
  <h1>Page not found</h1>
  <p class="hero-tag">The page you're looking for doesn't exist or has moved.</p>
</section>
<section class="home-cta">
  <a class="btn" href="/">Return home</a>
  <a class="btn" href="/fellows/">Fellows</a>
  <a class="btn" href="/admission/">Admission</a>
</section>"""
    write("404.html", page_template("Page not found", nf_body, "/", routes, None))

    count = 0
    for pid, p in pages.items():
        out = routes[pid]
        prefix = rel_prefix(out)
        # body
        if pid == 25:
            body = home_body(pages, routes, prefix)
        elif p["slug"] in ("application", "contact"):
            body = render_form_page(p, routes, wp_perma, pages, rewrite)
            body = f'<h1>{html.escape(p["title"])}</h1>\n' + body
        else:
            body = wpautop(p["content"])
            body = f'<h1>{html.escape(p["title"])}</h1>\n' + body
        body = apply_rewrites(body, prefix, rewrite)
        page_out = page_template(p["title"], body, prefix, routes, pid)
        write(f"{out}index.html", page_out)
        count += 1
    print(f"Generated {count} pages.")

if __name__ == "__main__":
    main()
