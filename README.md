# Vertex Society — static site

A self-contained static version of vertexsociety.wordpress.com, generated from the
WordPress export in this repo. No server, no database, no build step required to
host it — plain HTML + one CSS file + two images. It is meant for **free GitHub
Pages** hosting.

The only thing that needs external wiring is the two forms (Application, Contact),
which now post to **Google Forms** — see [Forms](#forms) below.

---

## What's in here

```
index.html                     Home
about/                         About  (+ contact/, faq/)
admission/                     Admission (+ application/  ← the form)
fellows/                       Fellows roster (+ one folder per member)
tests/                         Qualifying tests
dedication/, we-are-gathered/  standalone pages
assets/css/style.css           the single stylesheet
assets/img/                    logo.png, distribution.jpg
.nojekyll                      tells GitHub Pages to serve files as-is
build.py                       regenerates the whole site from the .xml export
vertexsociety.WordPress.*.xml  the source WordPress export
```

Every page is written as `<folder>/index.html`, so URLs stay clean
(`/fellows/olivier-r/`). All internal links are **relative**, so the site works
whether it's served from a domain root *or* a `username.github.io/vertexsociety/`
subfolder — no configuration needed.

## Preview locally

```bash
cd vertexsociety
python3 -m http.server 8137
# open http://127.0.0.1:8137/
```

## Deploy to GitHub Pages (free)

1. Make the repository **public** (Settings → General → Change visibility).
2. Push this folder to the `main` branch.
3. Settings → **Pages** → Source: **Deploy from a branch** → Branch: `main`, folder: `/ (root)` → Save.
4. Wait ~1 minute; your site appears at `https://<username>.github.io/vertexsociety/`.
   - For a root URL / custom domain, either name the repo `<username>.github.io`,
     or set a custom domain under Settings → Pages (add a `CNAME` file).

## Regenerating after a new WordPress export

Drop the new `*.xml` export in this folder and run:

```bash
python3 build.py
```

It overwrites the generated pages (newest `.xml` wins). Re-apply your Google Form
IDs afterward, or keep them — see the note at the end of Forms.

---

## Forms

Both forms submit to Google Forms and stay on the page (a hidden iframe receives
the response and a "Thank you" message is shown). Before they work you must create
the Google Form(s) and paste in the IDs. Two placeholders per form need replacing:

| Placeholder in the HTML | Replace with |
|---|---|
| `GOOGLE_FORM_ACTION_APPLICATION` (in `admission/application/index.html`) | your Application form's POST URL |
| `GOOGLE_FORM_ACTION_CONTACT` (in `about/contact/index.html`) | your Contact form's POST URL |
| `entry.REPLACE_application_*` (19 of them) | the real `entry.<id>` for each question |
| `entry.REPLACE_contact_*` (3 of them) | the real `entry.<id>` for each question |

### Step 1 — create the Google Form(s)

Create a Google Form with **exactly these questions, in this order** (question type
in parentheses). Keep the labels identical so responses are easy to read.

**Application form** (mark the ones noted as Required):

1. Test(s) and score(s) you wish to submit — Short answer — *Required*
2. First Name — Short answer — *Required*
3. Middle Name — Short answer
4. Last Name — Short answer — *Required*
5. Gender — Multiple choice: Female, Male
6. Birth Year — Short answer — *Required*
7. Your Email — Short answer — *Required*
8. Street — Short answer — *Required*
9. Postal Code — Short answer — *Required*
10. City — Short answer — *Required*
11. Phone Number — Short answer — *Required*
12. Country — Short answer — *Required*
13. First Spoken Language — Short answer — *Required*
14. Occupation — Short answer — *Required*
15. Education — Short answer — *Required*
16. HIQ Society Memberships — Short answer
17. Interests — Paragraph — *Required*
18. Website — Short answer
19. Comment — Paragraph — *Required*

**Contact form**:

1. Name — Short answer — *Required*
2. Email — Short answer — *Required*
3. Your Message — Paragraph — *Required*

> Note: Google Forms' own required-field validation won't run on these custom
> pages (the browser's `required` attribute does the client-side checking, which is
> already set to match the list above).

### Step 2 — get the POST URL

Open the form → **Send** → the `<>` (embed) tab, or just open the live form and
copy its URL. The POST endpoint is:

```
https://docs.google.com/forms/d/e/<LONG_FORM_ID>/formResponse
```

Paste that in place of `GOOGLE_FORM_ACTION_APPLICATION` (and the contact one).

### Step 3 — get each field's `entry.<id>`

Easiest way: on the live form, click the **⋮ → Get pre-filled link**, fill every
field with a recognizable dummy value, click **Get link**, and copy it. The URL
contains `entry.123456789=YourDummyValue` for each question. Match each id to its
question and replace the corresponding `entry.REPLACE_...` token in the HTML.

(Alternatively: open the live form, View Source, and search for `entry.`.)

### Step 4 — test

Submit the page's form once; confirm the row lands in the Google Form's Responses
tab and the "Thank you" message appears.

> **Re-running `build.py`** regenerates the form pages with the `entry.REPLACE_*`
> placeholders again. Either keep a note of your IDs and re-apply them, or set them
> once in `build.py` (search for `REPLACE_` / `GOOGLE_FORM_ACTION_`) so they persist
> across rebuilds.

---

## Notes on the migration

- **Images** were downloaded from the old site into `assets/img/` (the logo and the
  distribution diagram), so the static site has no dependency on wordpress.com.
- **`/fellows/vittorio-emanuel-lestat`** in the roster used a WordPress old-slug
  redirect; the actual page slug is `vittorio-e-lestat`. That link is remapped in
  `build.py` (`PERMALINK_ALIAS`) so it resolves.
- The **FAQ** page was marked *private* in WordPress. It's generated here and linked
  in the footer — delete `about/faq/` (and its footer entry in `build.py`) if you'd
  rather keep it unpublished.
- The **Fellows roster** is the hand-maintained list from the WordPress page, carried
  over as-is. Adding a new fellow means adding their `<li>` to `fellows/index.html`
  (or the Fellows page in the export before regenerating) and creating their page.
