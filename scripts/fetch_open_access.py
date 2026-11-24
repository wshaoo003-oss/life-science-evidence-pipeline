#!/usr/bin/env python3
"""Download and verify legal PMC open-access article packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import (  # noqa: E402
    ensure_run_layout,
    looks_like_pdf,
    normalize_doi,
    read_jsonl,
    safe_relative_path,
    sha256_file,
    utc_now,
    write_jsonl,
)


OA_API = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
S3_HTTPS_ROOT = "https://pmc-oa-opendata.s3.amazonaws.com"


def parse_oa_response(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    error = root.find(".//error")
    if error is not None:
        raise ValueError(f"PMC OA rejected article: {error.get('code', 'unknown')} {''.join(error.itertext()).strip()}")
    record = root.find(".//record")
    link = root.find(".//link[@format='tgz']")
    if record is None or link is None or not link.get("href"):
        raise ValueError("PMC OA response has no downloadable package")
    url = link.get("href")
    if url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        url = "https://ftp.ncbi.nlm.nih.gov/" + url.removeprefix("ftp://ftp.ncbi.nlm.nih.gov/")
    legacy_prefix = "https://ftp.ncbi.nlm.nih.gov/pub/pmc/"
    if url.startswith(legacy_prefix) and not url.startswith(legacy_prefix + "deprecated/"):
        url = legacy_prefix + "deprecated/" + url.removeprefix(legacy_prefix)
    return {
        "license": record.get("license"),
        "package_url": url,
        "oa_id": record.get("id"),
    }


def get_oa_record(pmcid: str) -> dict:
    url = OA_API.format(pmcid=pmcid)
    request = urllib.request.Request(url, headers={"User-Agent": "life-science-evidence-pipeline/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        xml_text = response.read().decode("utf-8")
    result = parse_oa_response(xml_text)
    result["oa_api_url"] = url
    return result


def s3_to_https(url: str) -> str:
    prefix = "s3://pmc-oa-opendata/"
    if not url.startswith(prefix):
        raise ValueError(f"unexpected PMC S3 URL: {url}")
    return f"{S3_HTTPS_ROOT}/{url.removeprefix(prefix)}"


def list_aws_versions(pmcid: str) -> list[str]:
    query = urllib.parse.urlencode({"list-type": 2, "prefix": f"{pmcid}.", "delimiter": "/"})
    request = urllib.request.Request(f"{S3_HTTPS_ROOT}/?{query}", headers={"User-Agent": "life-science-evidence-pipeline/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    prefixes = [element.text.rstrip("/") for element in root.findall(".//{*}CommonPrefixes/{*}Prefix") if element.text]
    if not prefixes:
        raise ValueError(f"PMC AWS has no article version for {pmcid}")
    return prefixes


def get_aws_versions(pmcid: str) -> list[dict]:
    rows = []
    for prefix in list_aws_versions(pmcid):
        url = f"{S3_HTTPS_ROOT}/metadata/{prefix}.json"
        request = urllib.request.Request(url, headers={"User-Agent": "life-science-evidence-pipeline/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            row = json.load(response)
        row["metadata_url"] = url
        rows.append(row)
    return rows


def select_aws_version(versions: list[dict]) -> dict:
    eligible = [
        row for row in versions
        if row.get("is_pmc_openaccess")
        and not row.get("is_retracted")
        and row.get("license_code")
        and row.get("pdf_url")
        and row.get("xml_url")
    ]
    if not eligible:
        raise ValueError("PMC AWS has no licensed, unretracted version with PDF and XML")
    return max(eligible, key=lambda row: (not bool(row.get("is_manuscript")), int(row.get("version", 0))))


def build_curl_download_command(curl: str, url: str, target: Path) -> list[str]:
    return [
        curl,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "3",
        "--retry-all-errors",
        "--connect-timeout",
        "15",
        "--max-time",
        "600",
        "--output",
        str(target),
        url,
    ]


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        command = build_curl_download_command(curl, url, partial)
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if completed.returncode != 0:
            raise OSError(f"curl failed with exit {completed.returncode}: {completed.stderr.strip()}")
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "life-science-evidence-pipeline/1.0"})
        with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
    if not partial.is_file() or partial.stat().st_size == 0:
        raise OSError("download produced an empty file")
    partial.replace(target)


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_md5(url: str) -> str | None:
    values = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("md5", [])
    return values[0].lower() if values else None


def download_aws_object(s3_url: str, target: Path) -> dict:
    source_url = s3_to_https(s3_url)
    expected = expected_md5(source_url)
    reused = bool(target.is_file() and expected and md5_file(target) == expected)
    if not reused:
        download(source_url, target)
    actual = md5_file(target)
    if expected and actual != expected:
        raise ValueError(f"PMC AWS MD5 mismatch for {target.name}")
    return {
        "source_url": source_url,
        "source_md5": expected,
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "reused": reused,
    }


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if member.issym() or member.islnk() or member.name.startswith(("/", "\\")) or ".." in parts:
                raise ValueError(f"unsafe archive member: {member.name}")
            resolved = (destination / Path(*parts)).resolve()
            try:
                resolved.relative_to(destination.resolve())
            except ValueError as exc:
                raise ValueError(f"archive member escapes destination: {member.name}") from exc
        bundle.extractall(destination, filter="data")


def select_primary(files: list[Path], suffix: str) -> Path:
    matches = sorted((path for path in files if path.suffix.lower() == suffix), key=lambda p: (p.stat().st_size, p.name), reverse=True)
    if not matches:
        raise ValueError(f"OA package has no {suffix} file")
    return matches[0]


def fetch_one(run_dir: Path, paper: dict) -> dict:
    pmcid = paper["pmcid"]
    raw_dir = run_dir / "raw" / pmcid
    try:
        version = select_aws_version(get_aws_versions(pmcid))
        if version.get("pmcid") != pmcid:
            raise ValueError(f"PMC AWS identity mismatch: expected {pmcid}, got {version.get('pmcid')}")
        if normalize_doi(version.get("doi")) != normalize_doi(paper.get("doi")):
            raise ValueError(f"PMC AWS DOI mismatch for {pmcid}")
        license_text = version.get("license_code")
        if not license_text:
            raise ValueError("PMC AWS metadata did not provide a license")
        pdf = raw_dir / "article.pdf"
        nxml = raw_dir / "article.nxml"
        pdf_info = download_aws_object(version["pdf_url"], pdf)
        nxml_info = download_aws_object(version["xml_url"], nxml)
        if not looks_like_pdf(pdf):
            raise ValueError("downloaded article is not a real PDF")
        media_dir = raw_dir / "media"
        media = []
        for index, media_url in enumerate(version.get("media_urls", []), 1):
            parsed_name = Path(urllib.parse.unquote(urllib.parse.urlparse(s3_to_https(media_url)).path)).name
            name = parsed_name or f"asset-{index}"
            target = media_dir / name
            info = download_aws_object(media_url, target)
            media.append({"path": safe_relative_path(run_dir, target), **info})
        metadata_path = raw_dir / "pmc-aws-metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "paper_id": pmcid,
            "pmcid": pmcid,
            "doi": paper.get("doi"),
            "pmid": paper.get("pmid"),
            "article_version": version.get("version"),
            "status": "complete",
            "license": license_text,
            "source": "PMC AWS Open Data",
            "source_url": version["metadata_url"],
            "downloaded_at": utc_now(),
            "metadata_path": safe_relative_path(run_dir, metadata_path),
            "metadata_sha256": sha256_file(metadata_path),
            "pdf_path": safe_relative_path(run_dir, pdf),
            "pdf_source_url": pdf_info["source_url"],
            "pdf_source_md5": pdf_info["source_md5"],
            "pdf_sha256": pdf_info["sha256"],
            "pdf_bytes": pdf_info["bytes"],
            "pdf_signature_valid": True,
            "jats_path": safe_relative_path(run_dir, nxml),
            "jats_source_url": nxml_info["source_url"],
            "jats_source_md5": nxml_info["source_md5"],
            "jats_sha256": nxml_info["sha256"],
            "jats_bytes": nxml_info["bytes"],
            "media_count": len(media),
            "media": media,
        }
    except Exception as exc:
        return {
            "paper_id": pmcid,
            "pmcid": pmcid,
            "status": "failed",
            "downloaded_at": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    run_dir = ensure_run_layout(args.run)
    papers = read_jsonl(run_dir / "manifests" / "papers.jsonl")
    if not papers:
        raise SystemExit("papers.jsonl is empty; run build_manifest.py first")
    rows = [fetch_one(run_dir, paper) for paper in papers]
    write_jsonl(run_dir / "manifests" / "downloads.jsonl", rows)
    complete = sum(row["status"] == "complete" for row in rows)
    print(json.dumps({"complete": complete, "failed": len(rows) - complete, "manifest": str(run_dir / "manifests" / "downloads.jsonl")}, indent=2))
    return 0 if complete == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
