import pdfkit
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import re
import codecs
import requests
from bs4 import BeautifulSoup, element
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
    "margin-top": "0in",
    "margin-right": "0in",
    "margin-bottom": "0in",
    "margin-left": "0in",
    "no-outline": None,
}


def parse_args() -> argparse.Namespace:
    """argument parser"""

    ## parse CLI args
    parser = argparse.ArgumentParser(
        prog="composing_programs_to_pdf.py",
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


def _replace_img_paths(soup: BeautifulSoup, webelement: element.Tag) -> element.Tag:
    """add the url to the relative paths in src values of img tags"""
    for img_tag in webelement.find_all("img"):
        if img_tag.has_attr("src"):
            new_img = soup.new_tag(
                "img",
                src=f'https://composingprograms.com/img/{img_tag["src"].split("/")[-1]}',
            )
            img_tag.replace_with(new_img)
    return webelement


def _replace_href_paths(soup: BeautifulSoup, webelement: element.Tag) -> element.Tag:
    """add the url to the relative paths in href values"""
    for a_tag in webelement.find_all("a"):
        if a_tag.has_attr("href"):
            if not a_tag.has_attr("class"):
                new_a = soup.new_tag(
                    "a",
                    href=f'https://composingprograms.com{a_tag["href"].split("/")[-1]}',
                )
                a_tag.replace_with(new_a)
    return webelement


def fix_relative_paths(soup: BeautifulSoup, webelement: element.Tag) -> element.Tag:
    """Wrapper for fixing issues with relative paths in anchor and image tags"""
    webelement = _replace_img_paths(soup=soup, webelement=webelement)
    webelement = _replace_href_paths(soup=soup, webelement=webelement)
    return webelement


def scrape_chapter_content(url: str) -> str:
    """Scrape the chapter's inner content"""
    resp = requests.get(url)
    if resp.ok:
        soup = BeautifulSoup(resp.content.decode("utf-8", "ignore"), "html.parser")
        inner_content = soup.select(".inner-content")[0]
        inner_content = fix_relative_paths(soup=soup, webelement=inner_content)
        with codecs.open("resources/header.html") as f:
            header_content = f.read()
        footer = """
        </body>
        </html>
        """
        return "\n".join([header_content, str(inner_content), footer])


def chapter_to_pdf(output_dir: str, url: str) -> str:
    """Convert the html of a chapter to a pdf"""
    chapter_content = scrape_chapter_content(url)
    filename = os.path.join(output_dir, f"{_fetch_chapter_number(url)}.pdf")
    pdfkit.from_string(
        chapter_content, filename, options=PDFKIT_OPTS, css="resources/cp.css"
    )
    return filename


def make_cover(output_dir: str) -> str:
    """generate a pdf with the book's cover"""
    filename = os.path.join(output_dir, "cover.pdf")
    pdfkit.from_file(
        "resources/cover.html",
        filename,
        options=PDFKIT_OPTS,
        css="resources/cover_style.css",
    )
    return filename


def _make_tex(pdf_paths_list: list) -> str:
    """Make the tex file containing all the pdf files to merge"""
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
    """Make the tex file containing all the pdf files to merge and store in temp dir"""
    tex = _make_tex(**kwargs)
    texfile = os.path.join(tex_dir, "to_merge.tex")
    with open(texfile, "w+") as tf:
        tf.write(tex)
    return texfile


def make_pdf(tex_path: str, temp_output_dir: str) -> str:
    """complie the tex file"""
    check_output(
        ["pdflatex", f"-output-directory={temp_output_dir}", tex_path], timeout=120
    )
    return os.path.join(temp_output_dir, "to_merge.pdf")


def merge_chapters(input_files: list, book_path: str) -> None:
    """Wrapper function for merging all the chapters"""
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
    """create the book"""
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


if __name__ == "__main__":
    main()
