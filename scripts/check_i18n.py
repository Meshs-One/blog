#!/usr/bin/env python3
"""Meshs One i18n guard — verify every EN blog post emits correct hreflang set.

Read-only check. The script:
  1. Parses every post's front matter under content/**/posts/*.md
  2. Rebuilds the site to an isolated temp dir (no files touched in repo)
  3. Validates the generated <link rel="alternate" hreflang="..."> tags on each
     EN original page

Business rule enforced (the real requirement, not just Hugo's internal pairing):
  For every translation file that EXISTS for an article, its EN canonical page
  MUST emit an hreflang for that language. A translation is "for an article" if
  it shares the EN original's translationKey OR (when unkeyed) the same basename.

This catches the silent regression we hit on 2026-07-22:
  - EN original missing a translationKey while translations have it
    -> translation becomes "dangling" (no EN match) -> guarded
  - EN original present but paired page drops a language -> guarded

The guard FAILS (exit 1, blocking `git push`) when:
  - an EN canonical page is missing an hreflang for a translation that exists
  - an EN page lacks self-reference (en) or x-default
  - a translation file cannot be paired with any EN original (orphaned)
"""
import os
import re
import sys
import glob
import shutil
import subprocess
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(REPO, "content")


def parse_fm(path):
    """Minimal YAML front-matter parser (keys + scalar values only)."""
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception:
        return {}
    if not txt.startswith("---"):
        return {}
    end = txt.find("\n---", 3)
    if end < 0:
        return {}
    block = txt[3:end]
    d = {}
    for line in block.splitlines():
        m = re.match(r"\s*([A-Za-z_][\w-]*):\s*(.*)", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
                v = v[1:-1]
            d[m.group(1)] = v
    return d


def detect_languages():
    """Language codes present: en (always) + any content/<lang>/posts dir."""
    langs = {"en"}
    if os.path.isdir(CONTENT):
        for name in os.listdir(CONTENT):
            p = os.path.join(CONTENT, name)
            if os.path.isdir(p) and name != "posts" and os.path.isdir(os.path.join(p, "posts")):
                langs.add(name)
    return langs


def collect_posts():
    """Yield post records for every *.md under content/**/posts/ (excludes _index etc.)."""
    recs = []
    for f in glob.glob(os.path.join(CONTENT, "**", "posts", "*.md"), recursive=True):
        rel = f.replace("\\", "/")
        parts = rel[len(CONTENT) + 1:].split("/")
        if len(parts) < 2 or parts[-2] != "posts":
            continue
        base = re.sub(r"\.md$", "", parts[-1])
        if base.startswith("_"):  # _index.md, _test.md ...
            continue
        lang = "en" if parts[0] == "posts" else parts[0]
        fm = parse_fm(f)
        recs.append({
            "path": f,
            "lang": lang,
            "base": base,
            "slug": fm.get("slug") or base,
            "tk": fm.get("translationKey", ""),
            "draft": fm.get("draft", "false") == "true",
        })
    return recs


def compute_expected(recs):
    """Return (expected, errors).

    expected: EN slug -> set of languages that SHOULD be linked (incl. 'en' self).
    errors:   list of dangling/orphaned translation descriptions.
    """
    en_by_key = {r["tk"]: r for r in recs if r["lang"] == "en" and r["tk"] and not r["draft"]}
    en_by_base = {r["base"]: r for r in recs if r["lang"] == "en" and not r["draft"]}

    expected = {}
    errors = []
    for r in recs:
        if r["lang"] == "en" or r["draft"]:
            continue
        counterpart = None
        if r["tk"]:
            counterpart = en_by_key.get(r["tk"])
        if counterpart is None and not r["tk"]:
            counterpart = en_by_base.get(r["base"])
        if counterpart is None:
            errors.append(
                f"translation '{r['base']}' (lang {r['lang']}, key='{r['tk']}') "
                f"has no matching EN original — orphaned translation"
            )
            continue
        expected.setdefault(counterpart["slug"], set()).add(r["lang"])
    # every EN page must at least self-reference
    for r in recs:
        if r["lang"] == "en" and not r["draft"]:
            expected.setdefault(r["slug"], set()).add("en")
    return expected, errors


def extract_hreflangs(html_path):
    try:
        txt = open(html_path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None
    return set(re.findall(r'hreflang\s*=\s*["\']?([a-zA-Z-]+)', txt))


def main():
    print("[i18n-guard] scanning content ...")
    langs = detect_languages()
    recs = collect_posts()
    expected, pair_errors = compute_expected(recs)
    en_recs = [r for r in recs if r["lang"] == "en" and not r["draft"]]

    tmp = tempfile.mkdtemp(prefix="meshs-i18n-")
    try:
        print(f"[i18n-guard] building site to temp dir ({len(en_recs)} EN posts) ...")
        r = subprocess.run(
            ["hugo", "--minify", "--destination", tmp],
            cwd=REPO, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print("[i18n-guard] ERROR: hugo build failed:\n" + r.stderr[:2000])
            return 1

        errors = list(pair_errors)
        for r in en_recs:
            slug = r["slug"]
            html = os.path.join(tmp, "posts", slug, "index.html")
            actual = extract_hreflangs(html)
            if actual is None:
                errors.append(f"EN post '{slug}': built HTML not found at posts/{slug}/index.html")
                continue
            exp = expected.get(slug, {"en"})
            if "en" not in actual:
                errors.append(f"EN post '{slug}': missing self-reference hreflang=en")
            if "x-default" not in actual:
                errors.append(f"EN post '{slug}': missing hreflang=x-default")
            for l in exp:
                if l == "en":
                    continue
                if l not in actual:
                    errors.append(
                        f"EN post '{slug}': MISSING hreflang={l} "
                        f"(translation exists but not linked — i18n pairing broken)"
                    )

        if errors:
            print("\n[i18n-guard] FAILED — push blocked. Fix translation pairing:\n")
            for e in errors:
                print("  - " + e)
            print("\nTip: ensure every translation's translationKey matches its EN original "
                  "(or filenames align across languages).")
            return 1

        print(f"[i18n-guard] OK — all {len(en_recs)} EN posts emit correct hreflang "
              f"(languages: {', '.join(sorted(langs))} + x-default).")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
