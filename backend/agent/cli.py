# -*- coding: utf-8 -*-
"""Agent token 管理 CLI —— 操作员(你)签发/吊销 agent token。

代理绝不应能自行签发 token(否则可无限提权)。token 由人工 CLI 铸出后，
以 `Authorization: Bearer <token>` 或 `X-Agent-Token` 头传给网关。

用法(项目根下，用项目解释器 C:\\Python314\\python.exe)：
  python -m backend.agent.cli issue            --scopes RWB --paper-only --agent-id default
  python -m backend.agent.cli list
  python -m backend.agent.cli revoke <token_id>
"""
from __future__ import annotations

import argparse
import sys

from . import store, gateway


def main(argv=None) -> int:
    store.ensure_schema()
    p = argparse.ArgumentParser(prog="backend.agent.cli", description="Agent token 管理")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("issue", help="签发一个新 token(只显示一次)")
    sp.add_argument("--agent-id", default="default")
    sp.add_argument("--scopes", default="R", help="逗号/空格分隔，如 R,W,B,T")
    sp.add_argument("--paper-only", action="store_true", default=True)
    sp.add_argument("--live", action="store_true", help="允许实盘(本部署无实盘，仅占位)")
    sp.add_argument("--rate-limit", type=int, default=60)
    sp.add_argument("--expires", default=None, help="YYYY-MM-DD HH:MM:SS 或留空")

    sl = sub.add_parser("list", help="列出 token(不含哈希)")
    sl.add_argument("--agent-id", default=None)

    sr = sub.add_parser("revoke", help="吊销 token")
    sr.add_argument("token_id", type=int)

    sr2 = sub.add_parser("revoke-all", help="吊销全部 token")

    args = p.parse_args(argv)
    if args.cmd == "issue":
        t = gateway.issue_token(args.agent_id, args.scopes,
                                paper_only=not args.live, rate_limit_per_min=args.rate_limit,
                                expires_at=args.expires)
        print("=" * 56)
        print("token 已签发(仅此一次显示，请立即保存):")
        print(f"  {t['full_token']}")
        print("=" * 56)
        print(f"  id={t['id']}  agent={t['agent_id']}  scopes={','.join(t['scopes'])}")
        print(f"  paper_only={t['paper_only']}  rate={t['rate_limit_per_min']}/min  prefix={t['prefix']}")
        print("调用: Authorization: Bearer <token>")
        return 0
    if args.cmd == "list":
        for r in gateway.list_tokens(args.agent_id):
            print(f"  #{r['id']:<4} {r['prefix']:<16} agent={r['agent_id']:<8} "
                  f"scopes={r['scopes']:<10} paper={bool(r['paper_only'])} "
                  f"revoked={bool(r['revoked'])}  created={r['created_at']}")
        return 0
    if args.cmd == "revoke":
        ok = gateway.revoke_token_record(args.token_id)
        print("已吊销" if ok else "未找到")
        return 0 if ok else 1
    if args.cmd == "revoke-all":
        gateway.revoke_token_record(0, None)
        print("已吊销全部")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
