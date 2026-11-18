"""Interactive terminal chat over the extracted corpus."""
from __future__ import annotations

import argparse

from . import docstore
from .rag import answer_question


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=None, help="document id (run without to list)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    docstore.init()
    if args.list:
        for d in docstore.list_documents():
            print(f"{d['id']:34s} {d['company']:45s} {d['doc_type']:22s} {d['pages']} pp")
        return
    doc_id = args.doc
    if not doc_id:
        print("Documents:")
        for d in docstore.list_documents():
            print(f"  {d['id']:34s} {d['company']}")
        print("\nUse --doc <id> to scope, or just ask across all documents.\n")
    print("DocIntel chat. /exit to quit, /docs to list.\n")
    history = []
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in ("/exit", "/quit"):
            break
        if q == "/docs":
            for d in docstore.list_documents():
                print(f"  {d['id']:34s} {d['company']}")
            continue
        r = answer_question(q, doc_id=doc_id, history=history)
        print(f"\ndocintel [{r['mode']}]\n{r['answer']}")
        if r["sources"]:
            print("\nsources:")
            seen = set()
            for s in r["sources"][:8]:
                key = (s["company"], s["page"])
                if key in seen:
                    continue
                seen.add(key)
                print(f"  - {s['company']} p.{s['page']} ({s['doc_type']})")
        print()
        history.extend([{"role": "user", "content": q}, {"role": "assistant", "content": r["answer"]}])


if __name__ == "__main__":
    main()
