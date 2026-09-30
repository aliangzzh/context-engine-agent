"""把项目自身的文档与代码灌进知识库（"代码/技术文档助手"演示用）。

这就是所谓的 **dogfooding（自举）**：拿这个项目自己的文档和代码当知识库，
然后问它"上下文引擎怎么做的""评测回归门怎么配的"——答案可验证，因为你就站在那份代码旁边。

用法（**在 backend/ 目录下执行**）::

    python scripts/upload_corpus.py --dry-run      # ① 先看会传哪些，不真传
    python scripts/upload_corpus.py                # ② 真传（默认：文档 + 应用代码）
    python scripts/upload_corpus.py --no-code      # 只传文档，不传代码
    python scripts/upload_corpus.py --with-tests   # 连测试代码一起传
    python scripts/upload_corpus.py --clear        # 先按 source 删掉已传的，再重传

设计说明
--------
* **进程内直接调 `KnowledgeBase`，不走 HTTP**：不需要先起服务，也不会被上传接口的
  2MB 限制挡住（`MAX_UPLOAD_BYTES` 只作用于 HTTP 层）。
* **`source` 用"相对仓库的路径"**（如 ``docs/architecture.md``、``backend/app/config.py``），
  这样答案里能直接引用到具体位置，而不是只看到一个裸文件名。
* **天然幂等**：入库按内容 MD5 去重，同一个文件重复跑只会显示 ``skipped``。
* 向量索引会跟着同步（`knowledge._sync_vector`）；同步失败只会降级 BM25，
  不会让入库失败——所以这个脚本在没装 faiss 的环境里同样能跑。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许 `python scripts/upload_corpus.py` 这种直接执行的方式
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.retrieval.knowledge import KnowledgeBase  # noqa: E402
from app.retrieval.retriever import get_retriever  # noqa: E402

#: 默认语料：项目文档（.md）
DOC_GLOBS = ["README.md", "docs/**/*.md"]

#: 默认代码语料：应用实现（不含 __pycache__）
CODE_GLOBS = ["backend/app/**/*.py"]

#: `--with-tests` 时追加的语料
TEST_GLOBS = ["backend/tests/**/*.py", "backend/eval/**/*.py"]


def _collect(patterns: list[str]) -> list[Path]:
    """按 glob 收集文件，去重、排除 __pycache__，按路径排序。"""
    root = config.PROJECT_DIR
    found: dict[Path, None] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                found[path] = None
    return sorted(found)


def _rel(path: Path) -> str:
    """相对仓库根目录的路径，作为 source（跨平台统一用 /）。"""
    return path.relative_to(config.PROJECT_DIR).as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把项目文档/代码灌进知识库")
    parser.add_argument("--dry-run", action="store_true", help="只列出会传哪些文件，不真传")
    parser.add_argument("--no-code", action="store_true", help="只传文档，不传代码")
    parser.add_argument("--with-tests", action="store_true", help="连测试与评测代码一起传")
    parser.add_argument("--clear", action="store_true",
                        help="先删除这些 source 已入库的内容，再重新传（避免旧分块残留）")
    args = parser.parse_args(argv)

    patterns = list(DOC_GLOBS)
    if not args.no_code:
        patterns += CODE_GLOBS
    if args.with_tests:
        patterns += TEST_GLOBS

    files = _collect(patterns)
    if not files:
        print("没有匹配到任何文件，检查是否在仓库根目录下的 backend/ 里执行。")
        return 1

    print(f"仓库根目录: {config.PROJECT_DIR}")
    print(f"匹配到 {len(files)} 个文件：")
    for path in files:
        print(f"  {_rel(path)}  ({path.stat().st_size} bytes)")

    if args.dry_run:
        print("\n--dry-run：只列清单，没有真的入库。去掉 --dry-run 即执行。")
        return 0

    retriever = get_retriever()
    kb = KnowledgeBase(retriever)
    print(f"\n当前知识库: {len(retriever.texts)} 个分块"
          f"    检索后端配置={config.effective_retrieval_backend()}"
          f"    实际生效={retriever.effective_backend()}")

    if args.clear:
        for path in files:
            kb.delete_source(_rel(path))
        print("已按 source 清掉旧内容，开始重新入库。\n")
    else:
        print()

    stats = {"ingested": 0, "skipped": 0, "unsupported": 0, "failed": 0}
    total_chunks = 0
    for path in files:
        name = _rel(path)
        try:
            res = kb.ingest_file(path, source=name)
        except Exception as exc:  # 单个文件出错不该中断整批
            stats["failed"] += 1
            print(f"  [error] {name}: {exc.__class__.__name__}: {exc}")
            continue
        status = res.get("status", "failed")
        stats[status] = stats.get(status, 0) + 1
        total_chunks += int(res.get("chunks") or 0)
        mark = {"ingested": "add", "skipped": "dup", "unsupported": "skip"}.get(status, "!!!")
        print(f"  [{mark}] {name}  chunks={res.get('chunks', 0)}")

    print("\n汇总："
          f"新增 {stats.get('ingested', 0)}，"
          f"重复跳过 {stats.get('skipped', 0)}，"
          f"类型不支持 {stats.get('unsupported', 0)}，"
          f"失败 {stats.get('failed', 0)}")
    print(f"本次新增分块 {total_chunks} 个；知识库现有 {len(retriever.texts)} 个分块")

    # 向量索引状态：装没装 faiss、索引新不新鲜，都在这里
    print("\n向量索引: "
          f"status={retriever.vector_status()}  "
          f"effective_backend={retriever.effective_backend()}")
    if retriever.vector_status() != "ready" and config.effective_retrieval_backend() != "bm25":
        print("  提示：索引不是 ready（依赖缺失 / 语料变了）。检索会自动降级 BM25，不会报错。")
        print("  手动重建：python -m app.retrieval.vector_index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
