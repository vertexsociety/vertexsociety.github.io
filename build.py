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
# 6. Template  (Yale-inspired: blue + white, serif display, photographic hero)
# ----------------------------------------------------------------------------
NAV = [  # (label, target page id)
    ("Home", 25), ("About", 30), ("Admission", 31),
    ("Fellows", 32), ("Tests", 33), ("Contact", 199),
]
FOOTER = [("Dedication", 504), ("FAQ", 79), ("Distinguished Fellows Selection", 294)]

def _href(routes, prefix, pid):
    d = routes[pid]
    return prefix + d if d else (prefix or "./")

def nav_html(routes, prefix, current_id):
    out = []
    for label, pid in NAV:
        cls = ' class="active"' if pid == current_id else ""
        out.append(f'<a{cls} href="{_href(routes, prefix, pid)}">{label}</a>')
    return "\n".join(out)

def footer_nav(routes, prefix):
    items = NAV[1:] + FOOTER  # skip Home
    return "\n".join(
        f'<a href="{_href(routes, prefix, pid)}">{label}</a>' for label, pid in items)

def page_banner(title, prefix):
    """Blue title band with the skyline faintly behind — used on interior pages."""
    return f"""<section class="banner" style="background-image:url({prefix}assets/img/skyline.jpg)">
  <div class="container banner-inner">
    <p class="kicker">Vertex Society</p>
    <h1>{html.escape(title)}</h1>
  </div>
</section>"""

def home_hero(prefix, routes):
    return f"""<section class="hero" style="background-image:url({prefix}assets/img/skyline.jpg)">
  <div class="container hero-inner">
    <p class="kicker">{SITE_DESC}</p>
    <h1>Order out of chaos.</h1>
    <p class="lead">An international society admitting Fellows at or above 160&nbsp;IQ
      (sd16) &mdash; a rarity of 1 in 11,000 &mdash; by professional, standardized,
      supervised tests of intelligence only.</p>
    <p class="hero-cta">
      <a class="btn btn-solid" href="{_href(routes, prefix, 31)}">Admission</a>
      <a class="btn btn-ghost" href="{_href(routes, prefix, 32)}">Meet the Fellows</a>
    </p>
  </div>
</section>"""

def page_template(title, hero, body, prefix, routes, current_id):
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
    <label for="navtoggle" class="navtoggle-btn" aria-label="Menu">&#9776;</label>
    <nav class="site-nav">
{nav_html(routes, prefix, current_id)}
    </nav>
  </div>
</header>
{hero}
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="container footer-inner">
    <div class="footer-brand">
      <span class="footer-name">{SITE_NAME}</span>
      <p>{SITE_DESC}.<br>Founded 2006.</p>
    </div>
    <nav class="footer-links">
{footer_nav(routes, prefix)}
    </nav>
  </div>
  <div class="container footer-bottom">
    <p>&copy; 2006&ndash;2026 {SITE_NAME}. An International Nonprofit Association.</p>
  </div>
</footer>
</body>
</html>
"""

# ----------------------------------------------------------------------------
# 7. Home page (WP front page has no content) — compose a landing page
# ----------------------------------------------------------------------------
def home_body(pages, routes, prefix):
    quote_src = pages[501]["content"] if 501 in pages else ""
    quote = re.sub(r"</?p>", "", strip_gutenberg(quote_src)).strip()
    intro_src = pages[30]["content"] if 30 in pages else ""
    first_para = intro_src.split("\n\n")[0] if intro_src else ""
    intro = wpautop(first_para)

    def card(pid, title, desc):
        return f"""<a class="card" href="{_href(routes, prefix, pid)}">
      <h3>{title}</h3>
      <p>{desc}</p>
      <span class="arrow">Read more &rarr;</span>
    </a>"""

    cards = "\n    ".join([
        card(31, "Admission",
             "Membership is free and open to anyone scoring at or above 3.75 standard "
             "deviations above the mean on a professional, standardized test."),
        card(33, "Qualifying Tests",
             "The professional, standardized tests of intelligence recognized for "
             "admission, and the score each requires."),
        card(32, "Fellows",
             "The Fellows of the Vertex Society, listed with their first spoken "
             "languages and places of residence."),
    ])

    return f"""<section class="lead-sec">
  <div class="prose">
{intro}
  </div>
</section>
<section class="quote-band">
  <div class="container">
    <p>{quote}</p>
  </div>
</section>
<section class="home-section">
  <p class="section-kicker">Explore</p>
  <h2 class="section-title">Membership</h2>
  <div class="cards">
    {cards}
  </div>
</section>
"""

# ----------------------------------------------------------------------------
# 8. CSS
# ----------------------------------------------------------------------------
CSS = r""":root{
  --yale:#00356b; --yale-dk:#00234a; --yale-dker:#001832;
  --ink:#20242c; --muted:#5b6472; --line:#dfe3ea; --soft:#f5f6f8;
  --gold:#cbb069;
  --serif:Georgia,"Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;font-family:var(--sans);color:var(--ink);background:#fff;
  line-height:1.62;font-size:18px}
img{max-width:100%;height:auto}
a{color:var(--yale);text-decoration:none}
h1,h2,h3,h4{font-family:var(--serif);color:var(--yale);line-height:1.18;font-weight:600}
.container{max-width:1160px;margin:0 auto;padding:0 26px}
.skip{position:absolute;left:-999px}
.skip:focus{left:8px;top:8px;background:#fff;padding:8px;z-index:20}

/* ---- header ---- */
.site-header{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.header-inner{display:flex;align-items:center;gap:18px;min-height:82px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:13px;color:var(--yale)}
.brand-logo{width:40px;height:40px}
.brand-name{font-family:var(--serif);font-size:1.6rem;font-weight:600;letter-spacing:.01em}
.site-nav{margin-left:auto;display:flex;gap:26px;flex-wrap:wrap}
.site-nav a{font-family:var(--sans);font-size:.78rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.1em;color:var(--yale);padding:6px 0;border-bottom:2px solid transparent}
.site-nav a:hover{border-bottom-color:var(--gold)}
.site-nav a.active{border-bottom-color:var(--yale)}
.navtoggle,.navtoggle-btn{display:none}

/* ---- hero (home) ---- */
.hero{position:relative;background:var(--yale-dk) center/cover no-repeat;color:#fff;
  display:flex;align-items:flex-end;min-height:74vh}
.hero::before{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(0,35,107,.30) 0%,rgba(0,24,50,.55) 55%,rgba(0,24,50,.90) 100%)}
.hero-inner{position:relative;z-index:1;padding:70px 26px 60px}
.kicker{font-family:var(--sans);text-transform:uppercase;letter-spacing:.18em;
  font-size:.8rem;font-weight:700;color:var(--gold);margin:0 0 .8em}
.hero h1{color:#fff;font-size:clamp(2.6rem,6vw,4.6rem);line-height:1.02;margin:0;max-width:16ch}
.hero .lead{font-size:1.2rem;line-height:1.55;color:#e9eef5;max-width:52ch;margin:1.1em 0 0}
.hero-cta{margin:1.8em 0 0;display:flex;gap:14px;flex-wrap:wrap}
.btn{display:inline-block;font-family:var(--sans);font-weight:700;font-size:.82rem;
  text-transform:uppercase;letter-spacing:.09em;padding:14px 28px;border-radius:2px;
  border:2px solid transparent;cursor:pointer}
.btn-solid{background:#fff;color:var(--yale);border-color:#fff}
.btn-solid:hover{background:var(--gold);border-color:var(--gold);color:var(--yale-dk)}
.btn-ghost{background:transparent;color:#fff;border-color:rgba(255,255,255,.7)}
.btn-ghost:hover{background:#fff;color:var(--yale)}

/* ---- interior banner ---- */
.banner{position:relative;background:var(--yale-dk) center/cover no-repeat;color:#fff}
.banner::before{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(0,35,107,.85),rgba(0,24,50,.9))}
.banner-inner{position:relative;z-index:1;padding:52px 26px 46px}
.banner h1{color:#fff;font-size:clamp(2rem,4.5vw,3.2rem);margin:0}
.banner .kicker{color:var(--gold);margin-bottom:.55em}

/* ---- reading content ---- */
.prose{max-width:820px;margin:0 auto;padding:52px 26px 76px}
.prose p{margin:0 0 1.15em}
.prose h2{font-size:1.7rem;margin:1.9em 0 .55em;padding-bottom:.28em;
  border-bottom:2px solid var(--line)}
.prose h3{font-size:1.3rem;margin:1.6em 0 .4em}
.prose a{text-decoration:underline;text-decoration-color:rgba(0,53,107,.35);text-underline-offset:2px}
.prose a:hover{text-decoration-color:var(--yale)}
.prose ul,.prose ol{margin:0 0 1.15em;padding-left:1.4em}
.prose li{margin:.3em 0}
.prose img{border:1px solid var(--line)}
.largefont{font-size:1.1rem;color:#333}
ol.membersclass li{margin:.38em 0}

/* ---- home sections ---- */
.lead-sec .prose{padding-bottom:8px}
.lead-sec .prose p{font-size:1.24rem;line-height:1.6;color:#33383f}
.quote-band{background:var(--yale);color:#fff;padding:56px 26px;margin:40px 0 0;text-align:center}
.quote-band p{font-family:var(--serif);font-style:italic;font-size:1.5rem;line-height:1.5;
  max-width:820px;margin:0 auto;color:#eaf0f7}
.home-section{max-width:1160px;margin:0 auto;padding:60px 26px 72px;text-align:center}
.section-kicker{font-family:var(--sans);text-transform:uppercase;letter-spacing:.18em;
  font-size:.78rem;font-weight:700;color:var(--gold);margin:0 0 .3em}
.section-title{font-size:2rem;margin:0 0 1.4em}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:26px;text-align:left}
.card{display:block;background:#fff;border:1px solid var(--line);border-top:4px solid var(--yale);
  padding:28px 26px;color:var(--ink);transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-4px);box-shadow:0 14px 34px rgba(0,35,107,.14)}
.card h3{font-size:1.45rem;margin:0 0 .5em}
.card p{color:var(--muted);font-size:1rem;margin:0 0 1em;line-height:1.5}
.card .arrow{font-family:var(--sans);text-transform:uppercase;letter-spacing:.08em;
  font-size:.78rem;font-weight:700;color:var(--yale)}

/* ---- forms ---- */
.vx-form{margin:1.6em 0;max-width:640px}
.vx-form .field{margin-bottom:1.15em}
.vx-form label{display:block;font-family:var(--sans);font-size:.9rem;font-weight:600;
  margin-bottom:.4em;color:var(--yale)}
.vx-form input[type=text],.vx-form input[type=email],.vx-form input[type=url],
.vx-form textarea{width:100%;padding:11px 13px;border:1px solid #c9ced9;border-radius:3px;
  font:inherit;font-size:1rem;background:#fff}
.vx-form input:focus,.vx-form textarea:focus{outline:none;border-color:var(--yale);
  box-shadow:0 0 0 3px rgba(0,53,107,.12)}
.vx-form textarea{resize:vertical}
.vx-form .radio-group{display:flex;gap:20px;flex-wrap:wrap}
.vx-form label.radio{font-weight:400;display:inline-flex;align-items:center;gap:7px;color:var(--ink)}
.vx-form button{background:var(--yale);color:#fff;border:0;padding:14px 34px;border-radius:2px;
  font-family:var(--sans);font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  font-size:.82rem;cursor:pointer}
.vx-form button:hover{background:var(--yale-dk)}
.req{color:#b23}
.form-note{font-family:var(--sans);font-size:.85rem;color:var(--muted)}
.form-thanks{background:var(--soft);border:1px solid var(--line);border-left:4px solid var(--yale);
  padding:22px 24px;border-radius:3px}

/* ---- footer ---- */
.site-footer{background:var(--yale-dker);color:#c3d0e2;margin-top:0;padding:52px 0 28px}
.footer-inner{display:flex;justify-content:space-between;gap:40px;flex-wrap:wrap}
.footer-name{font-family:var(--serif);font-size:1.5rem;color:#fff}
.footer-brand p{margin:.6em 0 0;font-size:.92rem;line-height:1.5;color:#9fb2cc}
.footer-links{display:flex;flex-direction:column;gap:11px}
.footer-links a{font-family:var(--sans);font-size:.82rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.07em;color:#c3d0e2}
.footer-links a:hover{color:#fff}
.footer-bottom{border-top:1px solid rgba(255,255,255,.16);margin-top:36px;padding-top:20px}
.footer-bottom p{margin:0;font-size:.82rem;color:#8ea3c0}

@media(max-width:760px){
  body{font-size:17px}
  .hero{min-height:64vh}
  .navtoggle-btn{display:inline-block;margin-left:auto;font-size:1.5rem;
    cursor:pointer;color:var(--yale);line-height:1;padding:4px 8px}
  .site-nav{display:none;flex-direction:column;width:100%;gap:2px;padding:6px 0 10px;margin:0}
  .site-nav a{padding:9px 0}
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
    nf_body = """<div class="prose">
  <p>The page you're looking for doesn't exist or has moved.</p>
  <p class="hero-cta">
    <a class="btn btn-solid" href="/" style="color:#fff;border-color:#00356b;background:#00356b">Return home</a>
    <a class="btn" href="/fellows/" style="color:#00356b;border-color:#00356b">Fellows</a>
  </p>
</div>"""
    write("404.html", page_template("Page not found",
          page_banner("Page not found", "/"), nf_body, "/", routes, None))

    count = 0
    for pid, p in pages.items():
        out = routes[pid]
        prefix = rel_prefix(out)
        if pid == 25:
            hero = home_hero(prefix, routes)
            body = home_body(pages, routes, prefix)
        elif p["slug"] in ("application", "contact"):
            hero = page_banner(p["title"], prefix)
            body = '<div class="prose">\n' + render_form_page(p, routes, wp_perma, pages, rewrite) + '\n</div>'
        else:
            hero = page_banner(p["title"], prefix)
            body = '<div class="prose">\n' + wpautop(p["content"]) + '\n</div>'
        body = apply_rewrites(body, prefix, rewrite)
        page_out = page_template(p["title"], hero, body, prefix, routes, pid)
        write(f"{out}index.html", page_out)
        count += 1
    print(f"Generated {count} pages.")

if __name__ == "__main__":
    main()
