#!/usr/bin/env python3
"""Gera uma playlist M3U incremental com vídeos de licença aberta."""
from __future__ import annotations
import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "catalogo.json"
PLAYLIST_PATH = ROOT / "playlist.m3u"
USER_AGENT = "BoskuFilm-SSIPTV-Catalog/1.0 (GitHub Actions; public-domain/open-license catalog)"
VIDEO_EXTENSIONS = (".mp4", ".m4v")
ALLOWED_LICENSES = (
    "creativecommons.org/publicdomain/zero/1.0",
    "creativecommons.org/publicdomain/mark/1.0",
    "creativecommons.org/licenses/by/2.0",
    "creativecommons.org/licenses/by/2.5",
    "creativecommons.org/licenses/by/3.0",
    "creativecommons.org/licenses/by/4.0",
    "creativecommons.org/licenses/by-sa/2.0",
    "creativecommons.org/licenses/by-sa/2.5",
    "creativecommons.org/licenses/by-sa/3.0",
    "creativecommons.org/licenses/by-sa/4.0",
)
SEARCH_URL = "https://archive.org/advancedsearch.php"


def request_json(url: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def get_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value or "").strip()


def allowed_license(metadata: dict[str, Any]) -> bool:
    license_url = get_text(metadata.get("licenseurl")).lower()
    rights = get_text(metadata.get("rights")).lower()
    if any(token in license_url for token in ALLOWED_LICENSES):
        return True
    # Some older IA records identify public domain in the rights field without licenseurl.
    if "public domain" in rights or "public-domain" in rights:
        return True
    return False


def safe_title(value: str, fallback: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    title = re.sub(r"[\x00-\x1f]", "", title)
    return title[:180] or fallback


def archive_download_url(identifier: str, filename: str) -> str:
    return "https://archive.org/download/{}/{}".format(
        urllib.parse.quote(identifier, safe=""),
        urllib.parse.quote(filename, safe=""),
    )


def search_items(max_items: int) -> list[dict[str, Any]]:
    # Consultar várias buscas direcionadas evita que resultados em inglês dominem
    # a coleta. A linguagem é confirmada novamente com os metadados completos.
    rights_filter = '(licenseurl:*creativecommons.org* OR rights:"public domain")'
    queries = [
        f'mediatype:movies AND language:por AND {rights_filter}',
        f'mediatype:movies AND language:Portuguese AND {rights_filter}',
        f'mediatype:movies AND (title:português OR title:portuguese OR subject:português OR subject:portuguese) AND {rights_filter}',
        f'mediatype:movies AND (subject:"cinema brasileiro" OR subject:"filme brasileiro" OR title:"cinema brasileiro") AND {rights_filter}',
        f'mediatype:movies AND (description:"Portuguese audio" OR description:"áudio em português" OR description:"dublado em português" OR description:"dublagem brasileira" OR title:dublado) AND {rights_filter}',
    ]
    found: dict[str, dict[str, Any]] = {}
    for query in queries:
        params = urllib.parse.urlencode({
            "q": query,
            "fl[]": ["identifier", "title", "year", "creator", "language", "description", "subject"],
            "rows": min(max_items, 500),
            "page": 1,
            "output": "json",
            "sort[]": "downloads desc",
        }, doseq=True)
        try:
            data = request_json(f"{SEARCH_URL}?{params}")
            docs = data.get("response", {}).get("docs", [])
            for doc in docs:
                identifier = str(doc.get("identifier", "")).strip()
                if identifier:
                    found[identifier] = doc
        except Exception as exc:
            logging.warning("Busca de filmes em português falhou (%s): %s", query, exc)
    return list(found.values())[:max_items]


def is_portuguese(metadata: dict[str, Any]) -> bool:
    """Só aceita itens com sinal explícito de português nos metadados."""
    language = get_text(metadata.get("language")).casefold()
    if re.search(r'(^|[;,/\\s])(por|pt|pt-br|portugu[eê]s|portuguese|brazilian portuguese)([;,/\\s-]|$)', language):
        return True

    text_fields = " ".join(
        get_text(metadata.get(field)) for field in ("title", "description", "subject", "notes", "identifier")
    ).casefold()
    explicit_signals = (
        "áudio em português", "audio em português", "audio in portuguese",
        "portuguese audio", "spoken in portuguese", "portuguese language",
        "língua portuguesa", "lingua portuguesa", "dublado em português",
        "dublado para português", "dublagem brasileira", "dublado brasileiro",
        "dublagem em português", "versão dublada", "versao dublada",
        "dubbed in portuguese", "portuguese dub", "legendado em português", "filme brasileiro",
        "filmes brasileiros", "cinema brasileiro", "cinema português",
        "filme português", "filmes portugueses", "brazilian portuguese",
    )
    return any(signal in text_fields for signal in explicit_signals)


def fetch_item(identifier: str) -> dict[str, Any] | None:
    try:
        return request_json("https://archive.org/metadata/" + urllib.parse.quote(identifier, safe=""))
    except Exception as exc:
        logging.debug("Metadata indisponível para %s: %s", identifier, exc)
        return None


def video_files(item: dict[str, Any]) -> list[dict[str, Any]]:
    files = item.get("files", [])
    candidates = []
    for f in files if isinstance(files, list) else []:
        name = str(f.get("name", ""))
        if name.lower().endswith(VIDEO_EXTENSIONS) and not f.get("private"):
            # Avoid derivatives and tiny preview files where metadata makes that clear.
            try:
                size = int(f.get("size", 0) or 0)
            except (ValueError, TypeError):
                size = 0
            if size and size < 2_000_000:
                continue
            candidates.append(f)
    # Prefer the largest MP4; one entry per Archive.org item.
    candidates.sort(key=lambda f: (not str(f.get("name", "")).lower().endswith(".mp4"),
                                   -int(f.get("size", 0) or 0)))
    return candidates


def is_confirmed_dead(url: str, timeout: int = 12) -> bool | None:
    """True only for definitive 404/410; False if reachable; None for transient/ambiguous errors."""
    headers = {"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response.read(1)
            return False
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return True
        if exc.code in (401, 403):
            return None
        return None
    except Exception:
        return None


def make_entry(doc: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
    if not allowed_license(metadata):
        return None
    if not is_portuguese(metadata):
        return None
    identifier = str(metadata.get("identifier") or doc.get("identifier") or "").strip()
    if not identifier:
        return None
    candidates = video_files(item)
    if not candidates:
        return None
    f = candidates[0]
    filename = str(f.get("name", ""))
    url = archive_download_url(identifier, filename)
    title = safe_title(get_text(metadata.get("title") or doc.get("title")), identifier)
    creator = safe_title(get_text(metadata.get("creator") or doc.get("creator")), "")
    year = get_text(metadata.get("year") or metadata.get("date") or doc.get("year"))
    subjects = get_text(metadata.get("subject"))
    category = "Filmes em Português"
    if re.search(r"documentary|documentário", subjects + " " + get_text(metadata.get("title")), re.I):
        category = "Documentários em Português"
    entry = {
        "id": identifier + "/" + filename,
        "title": title,
        "url": url,
        "group": category,
        "year": year[:20],
        "creator": creator,
        "license": get_text(metadata.get("licenseurl") or metadata.get("rights")),
        "source": "Internet Archive",
        "misses": 0,
        "last_status": "new",
    }
    return entry


def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"version": 1, "items": []}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data.get("items"), list):
            raise ValueError("campo items inválido")
        return data
    except Exception as exc:
        raise RuntimeError(f"Catálogo anterior inválido; não será sobrescrito: {exc}") from exc


def merge_items(old_items: list[dict[str, Any]], fresh_items: list[dict[str, Any]],
                dead_checker=is_confirmed_dead) -> list[dict[str, Any]]:
    """Merge by URL. Keep old items unless confirmed dead twice in a row."""
    merged: dict[str, dict[str, Any]] = {}
    for item in old_items:
        if item.get("url"):
            merged[item["url"]] = dict(item)
    for item in fresh_items:
        if item.get("url"):
            existing = merged.get(item["url"], {})
            merged[item["url"]] = {**existing, **item, "misses": 0, "last_status": "active"}
    fresh_urls = {x.get("url") for x in fresh_items}
    for url, item in list(merged.items()):
        if url in fresh_urls:
            continue
        status = dead_checker(url)
        if status is True:
            item["misses"] = int(item.get("misses", 0) or 0) + 1
            item["last_status"] = "confirmed_missing"
            if item["misses"] >= 2:
                del merged[url]
        elif status is False:
            item["misses"] = 0
            item["last_status"] = "active"
        else:
            # A timeout or 403 is not proof that the item is dead; preserve it.
            item["last_status"] = "unknown_preserved"
    return sorted(merged.values(), key=lambda x: (
        str(x.get("group", "" )).casefold(), str(x.get("title", "")).casefold(), str(x.get("url", ""))
    ))


def render_m3u(items: list[dict[str, Any]]) -> str:
    lines = ["#EXTM3U"]
    seen = set()
    for item in items:
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = safe_title(str(item.get("title", "")), "Vídeo sem título")
        group = safe_title(str(item.get("group", "Filmes sob demanda")), "Filmes sob demanda")
        attrs = [f'group-title="{group}"']
        year = str(item.get("year", "")).strip()
        if year:
            attrs.append(f'tvg-name="{title} ({year})"')
        else:
            attrs.append(f'tvg-name="{title}"')
        lines.append("#EXTINF:-1 " + " ".join(attrs) + "," + title)
        lines.append(url)
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def run(max_items: int, verbose: bool = False) -> int:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")
    old_catalog = load_catalog()
    old_items = old_catalog.get("items", [])
    logging.info("Catálogo anterior: %d itens", len(old_items))
    try:
        docs = search_items(max_items)
        if not docs:
            raise RuntimeError("Pesquisa retornou zero itens; preservando playlist e catálogo anteriores.")
        fresh = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_item, str(doc["identifier"])): doc for doc in docs}
            for future in as_completed(futures):
                doc = futures[future]
                item = future.result()
                if not item:
                    continue
                entry = make_entry(doc, item)
                if entry:
                    fresh.append(entry)
        logging.info("Itens novos/confirmados com licença e MP4: %d", len(fresh))
        # Never replace a working playlist with an empty/near-empty result.
        minimum = max(1, min(3, len(old_items)))
        if not fresh and not old_items:
            raise RuntimeError("Nenhum vídeo elegível foi encontrado; nenhum arquivo será criado/substituído.")
        if old_items and len(fresh) < minimum:
            logging.warning("Coleta muito pequena (%d < %d); preservando os arquivos anteriores.", len(fresh), minimum)
            return 2
        merged = merge_items(old_items, fresh)
        if not merged:
            raise RuntimeError("Resultado final vazio; preservando arquivos anteriores.")
        catalog = {"version": 1, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "source": "Internet Archive (open-license/public-domain filter)", "items": merged}
        playlist = render_m3u(merged)
        if playlist.strip() == "#EXTM3U":
            raise RuntimeError("Playlist sem entradas; preservando arquivos anteriores.")
        atomic_write(CATALOG_PATH, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        atomic_write(PLAYLIST_PATH, playlist)
        logging.info("Playlist gerada: %d itens -> %s", len(merged), PLAYLIST_PATH)
        return 0
    except Exception as exc:
        logging.error("%s", exc)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-items", type=int, default=int(os.getenv("MAX_ITEMS", "100")))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return run(max(1, min(args.max_items, 500)), args.verbose)


if __name__ == "__main__":
    sys.exit(main())
