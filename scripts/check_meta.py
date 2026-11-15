#!/usr/bin/env python3
"""Validate a Shorts meta.json before it is uploaded to Colab.

Usage: check_meta.py META.json [--year 2026]
Prints one PASS/FAIL line per rule. Exit code 0 only if every rule passes.
"""
import argparse, datetime, json, re, sys

DEV = re.compile(r"[\u0900-\u097F]")
LAT = re.compile(r"[A-Za-z]")
HASHTAG = re.compile(r"#\S+")
PUNCT = ".,;:!?\"'()[]{}—-–।"
KEYS = {"title", "description", "copyright"}


def words(text):
    """Whitespace tokens without hashtags, stripped of surrounding punctuation."""
    out = []
    for tok in HASHTAG.sub(" ", text).split():
        tok = tok.strip(PUNCT)
        if tok:
            out.append(tok)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("meta")
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    args = ap.parse_args()

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""))

    try:
        meta = json.load(open(args.meta, encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL json_utf8 -- {exc}")
        sys.exit(1)
    if not isinstance(meta, dict):
        print("FAIL json_object -- top level is not an object")
        sys.exit(1)

    check("keys_exact", set(meta) == KEYS, f"found {sorted(meta)}, need {sorted(KEYS)}")
    title = str(meta.get("title", ""))
    desc = str(meta.get("description", ""))
    copyright_ = str(meta.get("copyright", ""))

    check("title_has_#Shorts", "#Shorts" in title)
    title_words = words(title)
    title_dev = [w for w in title_words if DEV.search(w)]
    check("title_is_hindi", bool(title_words) and len(title_dev) == len(title_words),
          f"{len(title_dev)}/{len(title_words)} words in Devanagari")

    ws = words(desc)
    check("description_word_count_150_250", 150 <= len(ws) <= 250, f"{len(ws)} words (hashtags excluded)")
    dev_ws = [w for w in ws if DEV.search(w) and not LAT.search(w)]
    check("description_mostly_hindi", len(dev_ws) >= 100, f"{len(dev_ws)} Hindi words, need >=100")
    english = [w for w in ws if LAT.search(w) and not DEV.search(w) and len(w) >= 3]
    check("description_has_english_search_terms", len(english) >= 3, f"{len(english)} English words: {english[:6]}")
    mixed = [w for w in words(title + " " + desc) if DEV.search(w) and LAT.search(w)]
    check("no_mixed_script_words", not mixed, f"broken tokens: {mixed[:5]}")

    tags = [t.rstrip(PUNCT) for t in HASHTAG.findall(desc)]
    check("description_hashtags_3_to_5", 3 <= len(tags) <= 5, f"{len(tags)} hashtags: {tags}")
    check("copyright_has_year", str(args.year) in copyright_, f"copyright={copyright_!r}, expected year {args.year}")

    print("RESULT " + ("PASS" if all(results) else "FAIL"))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
