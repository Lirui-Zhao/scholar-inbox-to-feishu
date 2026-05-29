#!/usr/bin/env python3
"""
fetch_images.py — 为 paper-daily 抓取论文配图。

从四个来源收集候选图片，自动过滤图标/重复图，输出到 <out>/images/
并写一份 manifest.json，方便上层挑图 + 写准确的图注。

来源（可任意组合）：
  --arxiv ID     从 arxiv.org/html/<ID> 解析 <img> 并下载（论文里所有图的栅格版）
  --page URL     从项目主页解析 <img>/<source>/poster 并下载
  --pdf  PATH    用 pdfimages 抽取 PDF 内嵌位图
  --pdf-render-pages SPEC  矢量图兜底：整页渲染（'3,5,7-9' 或 'all'）。
                 ⚠️ pdfimages 抽不到矢量图(matplotlib/TikZ)，这类图必须靠整页渲染
  --repo PATH    扫描已克隆仓库目录里的图片资源（assets/ 等，常含架构图）

用法示例：
  python fetch_images.py --out /tmp/paper_imgs \
      --arxiv 2605.24934 \
      --page https://humanego-ai.github.io/ \
      --repo /tmp/paper_code

过滤规则：最长边 < --min-px(默认200) 的丢弃（图标/项目符号）；按内容 md5 去重；
SVG 保留（矢量图，尺寸记为未知）。最多保留 --max(默认40) 张。

依赖：PIL（量尺寸/去重，缺了也能跑）、pdfimages（PDF 抽图，缺了跳过 PDF）。
      无需 requests —— 已迁移到 stdlib urllib，与 scholar_inbox.py 保持零外部依赖。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener

try:
    from PIL import Image
except ImportError:
    Image = None

IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"}
HEADERS = {"User-Agent": "Mozilla/5.0 (paper-daily image fetcher)"}
# 站点装饰物：arXiv logo、知识共享许可图标、ORCID 等，不是论文内容
CHROME_PAT = re.compile(
    r"(arxiv-logo|/static/browse|cc[._-]?(by|sa|nc|zero)|creativecommons|orcid|favicon)",
    re.I)


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def _http_get(url, binary=False, timeout=30):
    """GET 一个 URL，返回 (final_url, bytes_or_text) 或 None（stdlib urllib）。

    保持与原 requests 版同样的语义：4xx/5xx 与网络错误均打印警告并返回 None
    （优雅降级），跟随重定向并用 resp.geturl() 取最终 URL，binary=False 时按
    UTF-8 解码（坏字节 replace），binary=True 时返回原始 bytes。
    """
    try:
        req = Request(url, headers=HEADERS)
        with build_opener().open(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            content = resp.read()
        if binary:
            return (final_url, content)
        return (final_url, content.decode("utf-8", "replace"))
    except HTTPError as e:
        print(f"  [!] HTTP {e.code} 下载失败 {url}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  [!] 网络错误 {url}: {repr(getattr(e, 'reason', e))[:100]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [!] 下载失败 {url}: {repr(e)[:100]}", file=sys.stderr)
        return None


def _img_dims(path):
    """返回 (w, h)；SVG 或读不出返回 (None, None)。"""
    if path.suffix.lower() == ".svg":
        return (None, None)
    if Image is None:
        return (None, None)
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (None, None)


def _md5(path, _cache={}):
    if path in _cache:
        return _cache[path]
    h = hashlib.md5(path.read_bytes()).hexdigest()
    _cache[path] = h
    return h


def _safe_name(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._")
    return s[:80] or "img"


def _extract_img_urls(html, base_url):
    """从 HTML 文本里抠出图片 URL（不依赖 bs4）。"""
    urls = []
    # <img src=...>  和  <source src=/srcset=...>  和 video poster=...
    for m in re.finditer(r"""<img\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"][^>]*>""", html, re.I):
        alt = re.search(r"""\balt\s*=\s*['"]([^'"]*)['"]""", m.group(0), re.I)
        urls.append((m.group(1), alt.group(1) if alt else ""))
    for m in re.finditer(r"""<(?:source|video)\b[^>]*?\b(?:src|poster)\s*=\s*['"]([^'"]+)['"]""", html, re.I):
        urls.append((m.group(1), ""))
    # 解析相对路径，去掉 data: 和过滤扩展名
    out = []
    seen = set()
    for u, alt in urls:
        if u.startswith("data:"):
            continue
        full = urljoin(base_url, u)
        ext = os.path.splitext(urlparse(full).path)[1].lower()
        if ext not in IMG_EXTS:
            continue
        if CHROME_PAT.search(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append((full, alt))
    return out


# ----------------------------------------------------------------------------
# 四个来源
# ----------------------------------------------------------------------------
def from_arxiv(arxiv_id, raw_dir):
    """从 arxiv HTML 页解析并下载图片。返回 [(path, source, origin, alt)]。"""
    arxiv_id = arxiv_id.strip()
    # 容错：用户可能传了完整 url
    m = re.search(r"(\d{4}\.\d{4,5}(v\d+)?)", arxiv_id)
    if m:
        arxiv_id = m.group(1)
    url = f"https://arxiv.org/html/{arxiv_id}"
    print(f"[arxiv] 抓取 {url}")
    got = _http_get(url)
    if not got:
        return []
    final_url, html = got
    pairs = _extract_img_urls(html, final_url)
    print(f"[arxiv] 页面发现 {len(pairs)} 个候选图")
    results = []
    for i, (u, alt) in enumerate(pairs):
        got = _http_get(u, binary=True)
        if not got:
            continue
        ext = os.path.splitext(urlparse(u).path)[1].lower() or ".png"
        name = f"arxiv_{i:02d}_{_safe_name(os.path.basename(urlparse(u).path))}"
        if not name.endswith(ext):
            name += ext
        p = raw_dir / name
        p.write_bytes(got[1])
        results.append((p, "arxiv_html", u, alt))
    return results


def from_page(page_url, raw_dir):
    print(f"[page] 抓取 {page_url}")
    got = _http_get(page_url)
    if not got:
        return []
    final_url, html = got
    pairs = _extract_img_urls(html, final_url)
    print(f"[page] 页面发现 {len(pairs)} 个候选图")
    results = []
    for i, (u, alt) in enumerate(pairs):
        got = _http_get(u, binary=True)
        if not got:
            continue
        ext = os.path.splitext(urlparse(u).path)[1].lower() or ".png"
        name = f"page_{i:02d}_{_safe_name(os.path.basename(urlparse(u).path))}"
        if not name.endswith(ext):
            name += ext
        p = raw_dir / name
        p.write_bytes(got[1])
        results.append((p, "project_page", u, alt))
    return results


def _parse_pages(spec):
    """页码规格解析：None->不渲染；'all'->全部页(None)；'3,5,7-9'->[(3,3),(5,5),(7,9)]"""
    if spec is None:
        return "skip"
    if spec.strip().lower() == "all":
        return None
    ranges = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ranges.append((int(a), int(b)))
        else:
            ranges.append((int(part), int(part)))
    return ranges


def from_pdf(pdf_path, raw_dir, render_pages=None):
    """
    PDF 抽图，两条路：
      (1) pdfimages 抽内嵌位图（照片、扫描图）。
      (2) pdftoppm 整页渲染兜底 —— 关键：pdfimages 抽不到矢量图(matplotlib/TikZ)，
          这类图只能靠整页渲染拿到。render_pages 指定渲染哪些页。
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"[pdf] 文件不存在: {pdf_path}", file=sys.stderr)
        return []
    results = []
    tmp = Path(tempfile.mkdtemp(prefix="pdfimg_"))

    # (1) 抽内嵌位图
    if shutil.which("pdfimages"):
        print(f"[pdf] pdfimages 抽内嵌位图: {pdf_path}")
        try:
            subprocess.run(["pdfimages", "-png", "-p", str(pdf_path), str(tmp / "pg")],
                           check=True, capture_output=True, timeout=300)
            for f in sorted(tmp.glob("pg-*.png")):
                dest = raw_dir / f"pdf_{f.name}"
                shutil.move(str(f), dest)
                results.append((dest, "pdf", str(pdf_path), ""))
            print(f"[pdf] 抽出 {sum(1 for r in results if r[1] == 'pdf')} 张位图（过滤前）")
        except Exception as e:
            print(f"[pdf] pdfimages 失败: {repr(e)[:120]}", file=sys.stderr)
    else:
        print("[pdf] 未找到 pdfimages，跳过位图抽取", file=sys.stderr)

    # (2) 矢量图兜底：整页渲染
    rp = _parse_pages(render_pages)
    if rp != "skip":
        if not shutil.which("pdftoppm"):
            print("[pdf] 未找到 pdftoppm，无法整页渲染兜底", file=sys.stderr)
        else:
            print(f"[pdf] pdftoppm 整页渲染兜底（补矢量图）: pages={render_pages}")
            try:
                if rp is None:  # 全部页
                    subprocess.run(["pdftoppm", "-png", "-r", "150", str(pdf_path), str(tmp / "page")],
                                   check=True, capture_output=True, timeout=600)
                else:
                    for a, b in rp:
                        subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", str(a), "-l", str(b),
                                        str(pdf_path), str(tmp / f"page_{a}_{b}")],
                                       check=True, capture_output=True, timeout=600)
                for f in sorted(tmp.glob("page*.png")):
                    dest = raw_dir / f"pdfpage_{f.stem}.png"
                    shutil.move(str(f), dest)
                    results.append((dest, "pdf_page", f"{pdf_path.name} 整页渲染", ""))
                print(f"[pdf] 渲染出 {sum(1 for r in results if r[1] == 'pdf_page')} 张整页图")
            except Exception as e:
                print(f"[pdf] pdftoppm 失败: {repr(e)[:120]}", file=sys.stderr)

    shutil.rmtree(tmp, ignore_errors=True)
    return results


def from_repo(repo_dir, raw_dir):
    repo_dir = Path(repo_dir)
    if not repo_dir.exists():
        print(f"[repo] 目录不存在: {repo_dir}", file=sys.stderr)
        return []
    print(f"[repo] 扫描 {repo_dir} 内的图片资源")
    results = []
    i = 0
    for f in sorted(repo_dir.rglob("*")):
        if ".git" in f.parts:
            continue
        if f.is_file() and f.suffix.lower() in IMG_EXTS:
            # 跳过明显的图标按钮目录
            low = str(f).lower()
            if any(k in low for k in ["btn_", "/icons/", "favicon", "logo"]):
                continue
            dest = raw_dir / f"repo_{i:02d}_{_safe_name(f.name)}"
            shutil.copy2(f, dest)
            results.append((dest, "repo", str(f.relative_to(repo_dir)), ""))
            i += 1
    print(f"[repo] 发现 {len(results)} 张图片资源（过滤前）")
    return results


# ----------------------------------------------------------------------------
# 主流程：过滤 + 去重 + 落盘 + manifest
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="抓取论文配图")
    ap.add_argument("--out", required=True, help="输出目录（会创建 <out>/images/）")
    ap.add_argument("--arxiv", help="arXiv ID，如 2605.24934")
    ap.add_argument("--page", help="项目主页 URL")
    ap.add_argument("--pdf", help="本地 PDF 路径")
    ap.add_argument("--pdf-render-pages",
                    help="矢量图兜底：整页渲染指定页，如 '3,5,7-9' 或 'all'。"
                         "用于 pdfimages 抽不到的矢量图(matplotlib/TikZ)，需配合 --pdf")
    ap.add_argument("--repo", help="已克隆仓库的本地目录")
    ap.add_argument("--min-px", type=int, default=200, help="最长边小于此像素则丢弃（默认200）")
    ap.add_argument("--max", type=int, default=40, help="最多保留张数（默认40）")
    args = ap.parse_args()

    if not any([args.arxiv, args.page, args.pdf, args.repo]):
        ap.error("至少要给一个来源：--arxiv / --page / --pdf / --repo")

    out_dir = Path(args.out)
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(tempfile.mkdtemp(prefix="rawimg_"))

    collected = []
    if args.arxiv:
        collected += from_arxiv(args.arxiv, raw_dir)
    if args.page:
        collected += from_page(args.page, raw_dir)
    if args.pdf:
        collected += from_pdf(args.pdf, raw_dir, render_pages=args.pdf_render_pages)
    elif args.pdf_render_pages:
        print("[!] --pdf-render-pages 需要配合 --pdf 使用", file=sys.stderr)
    if args.repo:
        collected += from_repo(args.repo, raw_dir)

    print(f"\n共收集 {len(collected)} 张原始候选图，开始过滤/去重 ...")

    manifest = []
    seen_hashes = set()
    kept = 0
    for path, source, origin, alt in collected:
        if kept >= args.max:
            break
        if not path.exists() or path.stat().st_size == 0:
            continue
        w, h = _img_dims(path)
        # 尺寸过滤（SVG 例外，w/h 为 None 时放行）
        if w is not None and h is not None and max(w, h) < args.min_px:
            continue
        digest = _md5(path)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)

        dest = img_dir / path.name
        # 防重名
        n = 1
        while dest.exists():
            dest = img_dir / f"{path.stem}_{n}{path.suffix}"
            n += 1
        shutil.copy2(path, dest)
        manifest.append({
            "file": f"images/{dest.name}",
            "source": source,
            "origin": origin,
            "alt": alt,
            "width": w,
            "height": h,
            "bytes": dest.stat().st_size,
        })
        kept += 1

    shutil.rmtree(raw_dir, ignore_errors=True)

    manifest_path = img_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # 打印摘要表
    print(f"\n保留 {len(manifest)} 张 -> {img_dir}")
    print(f"{'FILE':<34}{'SOURCE':<14}{'SIZE':<12}{'KB':>7}  ORIGIN/ALT")
    print("-" * 100)
    for m in manifest:
        dim = f"{m['width']}x{m['height']}" if m["width"] else "vector"
        hint = (m["alt"] or os.path.basename(m["origin"]))[:34]
        print(f"{os.path.basename(m['file']):<34}{m['source']:<14}{dim:<12}{m['bytes']//1024:>7}  {hint}")
    print(f"\nmanifest: {manifest_path}")
    print("下一步：读 manifest 挑出架构图 / 关键结果图，cd 到 images/ 目录后用")
    print("       lark-cli docs +media-insert --doc <DOC_ID> --file ./<name>.png")
    print("       --caption \"Figure N. ...\" --align center 把图插进飞书文档。")


if __name__ == "__main__":
    main()
