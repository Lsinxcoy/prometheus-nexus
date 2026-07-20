"""AST scan: find except handlers that swallow errors silently.

A handler is flagged as 'silent' when its body contains no:
  - logger.* call
  - any .error/.warning/.critical/.exception/.info call
  - raise statement
  - return of an error-ish value (return alone is ambiguous; we surface it)
We group by file and print (lineno, handler-type, body summary).
"""
import ast
import os
import sys

ROOT = "src"
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}

LOG_ATTRS = {"error", "warning", "critical", "exception", "info", "debug", "log"}


def has_log_or_raise(node):
    """Return True if subtree contains a logging call or raise."""
    found = False

    class V(ast.NodeVisitor):
        def visit_Call(self, n):
            nonlocal found
            if isinstance(n.func, ast.Attribute):
                if n.func.attr in LOG_ATTRS:
                    found = True
            if isinstance(n.func, ast.Name) and n.func.id in ("print",):
                found = True
            self.generic_visit(n)

        def visit_Raise(self, n):
            nonlocal found
            found = True
            self.generic_visit(n)

    V().visit(node)
    return found


def scan_file(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(0, f"SYNTAXERR {e}", "")]
    res = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            # a bare 'pass' or 'continue' or 'return None' with nothing else
            body_src = ast.get_source_segment(src, ast.Module(body, [])) or ""
            silent = not has_log_or_raise(ast.Module(body, []))
            # also record whether body is just pass/continue/return None
            simple = False
            if len(body) == 1:
                b = body[0]
                if isinstance(b, (ast.Pass, ast.Continue)):
                    simple = True
                if isinstance(b, ast.Return) and (b.value is None or isinstance(b.value, ast.Constant)):
                    simple = True
            res.append((node.lineno,
                        ast.unparse(node.type) if node.type else "Exception",
                        simple, silent, body_src.strip().splitlines()[0][:60] if body_src.strip() else ""))
    return res


def main():
    hits = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            for item in scan_file(p):
                if len(item) == 3:
                    # syntax error marker
                    hits.append((p, item[0], item[1], False, item[2]))
                    continue
                lineno, htype, simple, silent, first = item
                if silent:
                    hits.append((p, lineno, htype, simple, first))
    hits.sort()
    print(f"=== {len(hits)} silent except handlers (no log/raise) ===")
    for p, lineno, htype, simple, first in hits:
        tag = "BARE" if simple else "soft"
        print(f"{p}:{lineno} [{tag} {htype}] {first}")


if __name__ == "__main__":
    main()
