"""WPO HAPP rescue: restore partial verified feed when one remote is slow.

The existing asynchronous WPO handler unconditionally sends HTTP 503 when
*any* selected node is not ready. This discards all healthy verified links
including the primary node. Replace only the known blocking branch.
Never generate fake credentials; remote-only with zero ready remains 503.
"""
from __future__ import annotations
import ast
import re

MARK = "# WPO_HAPP_RESILIENT_FEED_V1"
OLD = '''                if pending:
                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return
                lines.extend(remote_links)'''
NEW = '''                # WPO_HAPP_RESILIENT_FEED_V1
                # Import usable verified links even when another node needs time.
                # For remote-only with zero verified links, keep honest 503.
                lines.extend(remote_links)
                if pending and not lines:
                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return
                if pending:
                    print("wpo happ partial feed:",len(remote_links),"verified remote links",
                          pending,"nodes pending",file=sys.stderr,flush=True)'''


def patch_panel(source):
    if MARK in source:
        raise ValueError("Subscription rescue already installed")
    if source.count(OLD) != 1:
        raise ValueError("WPO does not have the expected async 503 subscriber code; no files changed")
    method='    def serve_subscription(self,token):'
    if source.count(method)!=1:
        raise ValueError("Unknown controller subscription handler")
    begin=source.index(method)
    end=source.find('    def serve_direct_profile(self,token):',begin)
    if end<0:
        raise ValueError("Subscription handler boundary missing")
    if not begin < source.index(OLD) < end:
        raise ValueError("Async readiness code not in the subscription endpoint")
    output=source.replace(OLD,NEW,1)
    # The new code is longer. Recompute the method boundary before rewriting
    # the failover line, or the old index truncates the updated method.
    begin=output.index(method)
    end=output.find('    def serve_direct_profile(self,token):',begin)
    if end<0:raise ValueError("Subscription endpoint boundary changed")
    # The previous REALITY migration substituted len(chosen)>1 for
    # len(distinct_nodes)>1, enabling HAPP auto-failover even if only one
    # verified node survived. Use real returned host diversity instead.
    body=output[begin:end]
    lines=body.splitlines(keepends=True)
    indices=[i for i,line in enumerate(lines)
             if line.lstrip().startswith("failover=") and "len(chosen)>1" in line]
    if indices:
        if len(indices)!=1 or "distinct_nodes=" not in body:
            raise ValueError("Unexpected failover guard in subscription handler")
        idx=indices[0]
        lines[idx]=lines[idx].replace("len(chosen)>1","len(distinct_nodes)>1",1)
        output=output[:begin]+"".join(lines)+output[end:]
    ast.parse(output)
    return output


def patch_feed(source):
    """Only add sanitized failure categories and shorten repeated recovery.

    This intentionally does not change UUIDs, protocols, cache keys, verified
    link checks or the worker pool. An actual HTTP 503 is still reported.
    """
    if "# WPO_HAPP_FEED_RECOVERY_V1" in source:
        raise ValueError("Feed recovery already installed")
    old = 'RETRY_DELAY = 30'
    if source.count(old)!=1:
        raise ValueError("Unexpected asynchronous retry schedule")
    source=source.replace(old,
        '# WPO_HAPP_FEED_RECOVERY_V1: prompt recovery without hot-looping Node API.\n'
        'RETRY_DELAY = 8',1)
    old='''        print("wpo asynchronous node sync failed:", key[0], error_kind,
              file=sys.stderr, flush=True)'''
    new='''        # Emit only an HTTP code and exception class; never a node ID,
        # access token, UUID, profile link or server response body.
        source_error = getattr(exc, "__cause__", None)
        status_code = getattr(source_error, "code", None)
        safe_http = str(status_code) if isinstance(status_code, int) and 400 <= status_code <= 599 else "unknown"
        print("wpo async sync failed:", error_kind, "HTTP", safe_http,
              file=sys.stderr, flush=True)'''
    if source.count(old)!=1:
        raise ValueError("Unexpected asynchronous failure log format")
    source=source.replace(old,new,1)
    ast.parse(source)
    return source
