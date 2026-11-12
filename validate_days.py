#!/usr/bin/env python3
"""Өдрийн файлуудыг launch-аас өмнө шалгана (public + private).

Жишээ:
  python3 validate_days.py --public ~/repo/days --private private/english-a2b1 --upto 7
  python3 validate_days.py --public ~/repo/days --private private/english-a2b1 --days 28

Алдаа (❌) байвал гарах код 1. Анхааруулга (⚠️) нь зөвхөн зөвлөмж.
"""
import argparse
import json
import os
import sys

import logic

ORDER = ["listen", "phrases", "contrast", "read", "task"]
SECTIONS = set(ORDER)                 # хуучин хэлбэрийн түлхүүрүүд
BLOCK_TYPES = SECTIONS | {"text"}      # "blocks" хэлбэрт зөвшөөрөгдөх төрлүүд
LEAK_KEYS = {"answer_key", "model_reply", "model_notes", "hints"}


def load(path, errors):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        errors.append(f"файл алга: {path}")
    except json.JSONDecodeError as e:
        errors.append(f"JSON буруу ({os.path.basename(path)}): мөр {e.lineno}, багана {e.colno}: {e.msg}")
    return None


def is_str(x):
    return isinstance(x, str) and x.strip() != ""


def is_list_of(x, n, pred=is_str):
    return isinstance(x, list) and len(x) == n and all(pred(i) for i in x)


def find_leaks(obj, path=""):
    """Public файлд нууц түлхүүр байгаа эсэх."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in LEAK_KEYS:
                out.append(f"{path}/{k}")
            out += find_leaks(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += find_leaks(v, f"{path}[{i}]")
    return out


def normalize(d):
    """Хоёр хэлбэрийг (хуучин түлхүүрүүд / blocks) нэг жагсаалт болгоно: [(type, data), ...]"""
    if isinstance(d.get("blocks"), list):
        return [(b.get("type"), b) for b in d["blocks"] if isinstance(b, dict)]
    steps = d.get("steps")
    if isinstance(steps, list) and steps:
        ids = [x[0] for x in steps if isinstance(x, list) and x]
    else:
        ids = [k for k in ORDER if k in d]
    out = []
    for k in ids:
        v = d.get(k)
        if v is None:
            continue
        b = {"items": v} if isinstance(v, list) else dict(v) if isinstance(v, dict) else {}
        if k == "listen" and "video" in d:
            b["video"] = d["video"]
        out.append((k, b))
    return out


def check_block(t, b, where, errors, warns):
    if t not in BLOCK_TYPES:
        errors.append(f"public: {where}: үл мэдэгдэх төрөл '{t}' (боломжит: {', '.join(sorted(BLOCK_TYPES))})")
        return
    if t == "text":
        if not (is_str(b.get("title")) or b.get("paragraphs") or b.get("bullets")):
            errors.append(f"public: {where}: text-д title, paragraphs, bullets-ийн аль нэг нь байх ёстой")
    elif t == "listen":
        if not is_str(b.get("lead")) or not b.get("questions") or not b.get("transcript"):
            errors.append(f"public: {where}: listen дутуу (lead, questions, transcript)")
        elif not all(is_str(q) for q in b["questions"]) or not all(is_list_of(x, 2) for x in b["transcript"]):
            errors.append(f"public: {where}: listen доторх бүтэц буруу")
        v = b.get("video", "")
        if not v:
            warns.append(f"public: {where}: video хоосон байна")
        elif not isinstance(v, str) or len(v) != 11:
            warns.append(f"public: {where}: video ID '{v}' 11 тэмдэгт биш")
    elif t == "phrases":
        if not (isinstance(b.get("items"), list) and b["items"] and all(is_list_of(x, 3) for x in b["items"])):
            errors.append(f"public: {where}: phrases бүр [англи, монгол, хэзээ] гэсэн 3 хэсэгтэй байх ёстой")
    elif t == "contrast":
        c = b.get("items")
        if not (isinstance(c, list) and c and all(
            isinstance(x, list) and len(x) == 2 and is_str(x[0]) and isinstance(x[1], list) and x[1]
            and all(is_list_of(r, 2) for r in x[1]) for x in c
        )):
            errors.append(f"public: {where}: contrast бүтэц буруу ([гарчиг, [[нөхцөл, хэллэг], ...]])")
    elif t == "read":
        has_chat = isinstance(b.get("chat"), list) and b["chat"] and all(is_list_of(m, 3) for m in b["chat"])
        has_text = isinstance(b.get("paragraphs"), list) and b["paragraphs"] and all(is_str(x) for x in b["paragraphs"])
        if not is_str(b.get("lead")) or not (has_chat or has_text) or not b.get("questions"):
            errors.append(f"public: {where}: read дутуу (lead, chat эсвэл paragraphs, questions)")
    elif t == "task":
        if not all(is_str(b.get(k)) for k in ("title", "lead", "message")) or not b.get("problems") or not b.get("rules"):
            errors.append(f"public: {where}: task дутуу (title, lead, message, problems, rules)")


def check_public(d, n, errors, warns):
    for key in ("day", "total", "title"):
        if key not in d:
            errors.append(f"public: '{key}' алга")
    if errors:
        return
    if d["day"] != n:
        errors.append(f"public: day={d['day']} боловч файл day-{n:02d}")
    if isinstance(d.get("redirect"), str):
        return          # огт өөр хуудас руу шилждэг өдөр: дотор нь шалгах зүйлгүй

    if isinstance(d.get("blocks"), list):
        if not d["blocks"]:
            errors.append("public: blocks хоосон байна")
            return
        if "steps" in d:
            warns.append("public: blocks ашиглаж байгаа үед steps хэрэглэгдэхгүй")
    else:
        steps = d.get("steps")
        if steps is not None:
            if not isinstance(steps, list) or not steps:
                errors.append("public: steps хоосон байна (хэрэггүй бол бүр устгана)")
                return
            seen = set()
            for s_ in steps:
                if not (isinstance(s_, list) and len(s_) == 3 and is_str(s_[0]) and is_str(s_[1]) and isinstance(s_[2], int)):
                    errors.append(f"public: steps дахь мөр буруу: {s_}")
                    continue
                if s_[0] not in SECTIONS:
                    errors.append(f"public: үл мэдэгдэх section '{s_[0]}' (боломжит: {', '.join(sorted(SECTIONS))})")
                if s_[0] in seen:
                    errors.append(f"public: section '{s_[0]}' хоёр удаа орсон (ижил төрлийг олон удаа ашиглах бол blocks хэрэглэнэ)")
                seen.add(s_[0])
                if s_[0] in SECTIONS and s_[0] not in d:
                    errors.append(f"public: steps-д '{s_[0]}' байгаа ч '{s_[0]}' өгөгдөл алга")
            total_min = sum(x[2] for x in steps if isinstance(x, list) and len(x) == 3 and isinstance(x[2], int))
            if isinstance(d.get("minutes"), int) and abs(total_min - d["minutes"]) > 10:
                warns.append(f"public: алхмуудын нийлбэр {total_min} мин, minutes={d['minutes']}")
    items = normalize(d)
    if not items:
        errors.append("public: ямар ч хэсэг алга (listen, phrases, contrast, read, task эсвэл blocks)")
        return
    for idx, (t, b) in enumerate(items, 1):
        check_block(t, b, f"{idx}-р хэсэг ({t})", errors, warns)


def count_questions(d):
    return sum(len(b.get("questions", [])) for t, b in normalize(d) if t in ("listen", "read") and isinstance(b.get("questions"), list))


def check_private(p, pub, n, errors, warns):
    lo, hi = p.get("min_words"), p.get("max_words")
    if not (isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi):
        errors.append("private: min_words / max_words буруу эсвэл алга")
        lo = hi = None
    # answer_key, model_reply заавал биш: байхгүй бол bot хариулт үзүүлэхгүй
    key = p.get("answer_key")
    if key is not None:
        if not (isinstance(key, list) and key and all(is_str(a) for a in key)):
            errors.append("private: answer_key хоосон эсвэл буруу")
        elif pub and count_questions(pub) != len(key):
            errors.append(f"private: answer_key {len(key)} хариутай, public дээр {count_questions(pub)} асуулт байна")
    model = p.get("model_reply")
    if model is not None and not is_str(model):
        errors.append("private: model_reply хоосон эсвэл буруу")
    elif is_str(model) and lo:
        words = logic.count_words(model)
        if not lo <= words <= hi:
            errors.append(f"private: model_reply {words} үгтэй, дүрэм {lo}–{hi}")
    hints = p.get("hints", [])
    if hints and not all(isinstance(h, dict) and is_str(h.get("label")) and h.get("keywords") for h in hints):
        errors.append("private: hints бүр label ба keywords-той байх ёстой")
    elif hints and is_str(model):
        missed = [h["label"] for h in hints if not any(k.lower() in model.lower() for k in h["keywords"])]
        if missed:
            warns.append(f"private: жишээ хариу эдгээр зөвлөмжийг хангахгүй: {missed}")
    if pub and lo:
        rules = " ".join(r for t, b in normalize(pub) if t == "task" for r in b.get("rules", []) if isinstance(r, str))
        if f"{lo}–{hi}" not in rules and f"{lo}-{hi}" not in rules:
            warns.append(f"public task.rules дотор үгийн хязгаар '{lo}–{hi}' байхгүй байна")
    if pub and p.get("title") and pub.get("title") != p["title"]:
        warns.append("private title нь public title-тай ялгаатай")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--public", required=True, help="public days/ хавтас (day-01.json ...)")
    ap.add_argument("--private", required=True, help="private хавтас (day-01.json ...)")
    ap.add_argument("--days", type=int, default=28, help="Нийт өдөр (default 28)")
    ap.add_argument("--upto", type=int, help="Зөвхөн эхний N өдрийг шалгах")
    args = ap.parse_args()

    last = args.upto or args.days
    bad_days = 0
    for n in range(1, last + 1):
        name = f"day-{n:02d}.json"
        errors, warns = [], []
        pub_path = os.path.join(args.public, name)
        pub = load(pub_path, errors)
        priv = load(os.path.join(args.private, name), errors)
        if pub is not None:
            check_public(pub, n, errors, warns)
            leaks = find_leaks(pub)
            if leaks:
                errors.append(f"public файлд нууц өгөгдөл байна: {', '.join(leaks)}")
            if priv and is_str(priv.get("model_reply")) and priv["model_reply"][:40] in open(pub_path, encoding="utf-8").read():
                errors.append("public файлд жишээ хариуны текст орсон байна")
        if priv is not None:
            check_private(priv, pub, n, errors, warns)
        status = "❌" if errors else ("⚠️ " if warns else "✅")
        print(f"{status} {name}")
        for e in errors:
            print(f"    ❌ {e}")
        for w in warns:
            print(f"    ⚠️  {w}")
        bad_days += bool(errors)

    print(f"\nШалгасан: {last} өдөр, алдаатай: {bad_days}")
    sys.exit(1 if bad_days else 0)


if __name__ == "__main__":
    main()
