import pdfkit
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import re
import codecs
import requests
from bs4 import BeautifulSoup
import os
import sys
import tempfile
import shutil
from subprocess import check_output
import argparse

PATH_TO_SITEMAP = "resources/composing_programs_sitemap.xml"

PDFKIT_OPTS = options = {
    "page-size": "letter",
    "user-style-sheet": "./resources/cp.css",
    "dpi": "600",
    "encoding": "UTF-8",
    "javascript-delay": "9000",
}


def parse_args() -> argparse.Namespace:
    """argument parser"""

    ## parse CLI args
    parser = argparse.ArgumentParser(
        prog="composing_programs2pdf.py",
        description="Convert the online book 'Composing Programs' into a pdf file. See: https://composingprograms.com/",
    )

    parser.add_argument(
        "-o",
        "--output-path",
        type=str,
        dest="output_path",
        default=None,
        help="oath to the output pdf file.",
    )
    # parse. If no args display the "help menu"
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


def _filter_chapters(ignore_v1: bool = True) -> list:
    """Filter and sort the relevant chapters"""
    # parse the sitemap xml file
    tree = ET.parse(PATH_TO_SITEMAP, parser=ET.XMLParser(encoding="utf-8"))
    root = tree.getroot()
    out = []
    for node in root.findall("url"):
        for child in node:
            if child.tag == "loc":
                url = child.text
                # check if it has a path
                path = urlparse(url).path
                if len(path) > 1:
                    if "pages" in path:
                        if ignore_v1:
                            if "v1" in url:
                                continue
                        out.append(url)
    return out


def _fetch_chapter_number(
    url: str = "https://composingprograms.com/pages/11-getting-started.html",
) -> int:
    # fetch the chapter number
    parsed = urlparse(url).path.split("/")[-1]
    return int(re.search("^[0-9]+(?=\-)", parsed).group(0))


def _sort_chapter(chapter_urls: list) -> list:
    """sort the chapter by chapter number"""
    return sorted(chapter_urls, key=lambda x: _fetch_chapter_number(x))


def fetch_chapter_urls(**kwargs) -> list:
    """Fetch all the chapter urls from the sitemap and sort them"""
    relevant_chapters = _filter_chapters(**kwargs)
    return _sort_chapter(relevant_chapters)


def scrape_chapter_content(url: str) -> str:
    """Scrape the chapter's inner content"""
    resp = requests.get(url)
    if resp.ok:
        soup = BeautifulSoup(resp.content.decode("utf-8", "ignore"), "html.parser")
        inner_content = str(soup.select(".inner-content")[0])
        with codecs.open("resources/header.html") as f:
            header_content = f.read()
        footer = """
        </body>
        </html>
        """
        return "\n".join([header_content, inner_content, footer])


def chapter_to_pdf(output_dir: str, url: str) -> str:
    """Convert the html of a chapter to a pdf"""
    chapter_content = scrape_chapter_content(url)
    filename = os.path.join(output_dir, f"{_fetch_chapter_number(url)}.pdf")
    pdfkit.from_string(
        chapter_content, filename, options=PDFKIT_OPTS, css="resources/cp.css"
    )
    return filename


def make_cover(output_dir: str) -> str:
    filename = os.path.join(output_dir, "cover.pdf")
    pdfkit.from_file(
        "resources/cover.html",
        filename,
        options=PDFKIT_OPTS,
        css="resources/cover_style.css",
    )
    return filename


def _make_tex(pdf_paths_list: list) -> str:
    """Make the tex file"""
    to_insert = "\n".join(["\includepdf[pages=-]{" + _ + "}" for _ in pdf_paths_list])
    # insert them in the tex file
    prefix = """
    \\documentclass{article}
    \\usepackage{pdfpages}
    \\begin{document}
    """
    suffix = """
    \\end{document}
    """
    return "\n".join([prefix, to_insert, suffix])


def make_tex(tex_dir: str, **kwargs) -> str:
    """Make the tex file and store in temp dir"""
    tex = _make_tex(**kwargs)
    texfile = os.path.join(tex_dir, "to_merge.tex")
    with open(texfile, "w+") as tf:
        tf.write(tex)
    return texfile


def make_pdf(tex_path: str, temp_output_dir: str) -> str:
    """Make a pdf doc with a tex file"""
    check_output(
        ["pdflatex", f"-output-directory={temp_output_dir}", tex_path], timeout=120
    )
    return os.path.join(temp_output_dir, "to_merge.pdf")


def merge_chapters(input_files: list, book_path: str) -> None:
    tex_dir = tempfile.mkdtemp(prefix="interm-tex-dir-book-")
    # prepare the merge tex
    tex_path = make_tex(pdf_paths_list=input_files, tex_dir=tex_dir)
    # make the pdf
    output_file = os.path.join(book_path, "composing-programs.pdf")
    pdf_path = make_pdf(tex_path=tex_path, temp_output_dir=tex_dir)
    # copy
    shutil.copy(src=pdf_path, dst=output_file)
    # delete tempdir
    shutil.rmtree(tex_dir)


def make_book(book_path: str = "test") -> None:
    temp_dir = tempfile.mkdtemp(prefix="interm-dir-book-")
    # filename container
    filename_container = []
    # make the cover page
    filename_container.append(make_cover(output_dir=temp_dir))
    # chapter urls
    chapter_urls = fetch_chapter_urls()
    # for each, conert to pdf
    for chapter_url in chapter_urls:
        filename_container.append(chapter_to_pdf(output_dir=temp_dir, url=chapter_url))
    # merge into one book
    merge_chapters(input_files=filename_container, book_path=book_path)
    # delete tempdir
    shutil.rmtree(temp_dir)

def main() -> None:
    args = parse_args()
    output_path = args.output_path
    make_book(book_path=output_path)
    print(f"[+] A pdf version of 'Composing Programs' was saved in: {output_path}")
    