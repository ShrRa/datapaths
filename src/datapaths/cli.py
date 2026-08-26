from __future__ import annotations

import argparse
import json

from .datapaths import Datapaths


def main() -> None:
    p = argparse.ArgumentParser(prog="datapaths")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--name", default=None)
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--tag", default=None)
    p_list.add_argument("--text", default=None)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--type", default=None)
    p_verify.add_argument("--tag", default=None)
    p_verify.add_argument("--name", action="append", default=[])

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--name", required=True)
    p_reg.add_argument("--type", required=True)
    p_reg.add_argument("--file", required=True)
    # No choices: register records a file it does not have to write, so any
    # format label is legitimate here (fits, hdf5, pdf). save() is where the
    # vocabulary is genuinely closed.
    p_reg.add_argument(
        "--fmt", required=True,
        help="format label, e.g. parquet, csv, json, bin, pickle, or any other (fits, hdf5, ...)",
    )
    p_reg.add_argument("--tag", action="append", default=[])
    p_reg.add_argument("--notes", default="")
    p_reg.add_argument("--copy-into-canonical", action="store_true")
    p_reg.add_argument("--force-flat-layout", action="store_true")
    p_reg.add_argument("--overwrite", action="store_true")

    args = p.parse_args()
    dp = Datapaths()

    if args.cmd == "list":
        rows = dp.list(name=args.name, type=args.type, tag=args.tag, text=args.text)
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if args.cmd == "verify":
        names = args.name or None
        rows = dp.verify(names=names, type=args.type, tag=args.tag)
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if args.cmd == "register":
        rec = dp.register(
            name=args.name,
            type=args.type,
            src_path=args.file,
            fmt=args.fmt,
            tags=args.tag,
            notes=args.notes,
            force_flat_layout=args.force_flat_layout,
            copy_into_canonical=args.copy_into_canonical,
            overwrite=args.overwrite,
        )
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
