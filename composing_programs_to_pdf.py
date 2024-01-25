# import sys
# # sys.setdefaultencoding() does not exist, here!
# from importlib import reload
# reload(sys)  # Reload does the trick!
# sys.setdefaultencoding('UTF8')

import pdfkit
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import re
import codecs
import requests
from bs4 import BeautifulSoup, element
import os
import sys
import time
import tempfile
from typing import Optional
import shutil
from subprocess import check_output
import argparse
from selenium import webdriver
from numbering2pdf import add_numbering_to_pdf
from PyPDF2 import PdfFileMerger, PdfFileReader
import contextlib

PATH_TO_SITEMAP = "resources/composing_programs_sitemap.xml"
# FIREFOX_BINARY = "/usr/bin/firefox"
FIREFOX_BINARY = 'C:\\Program Files\\Mozilla Firefox\\firefox.exe'
PDFKIT_OPTS = options = {
    "page-size": "letter",
    "user-style-sheet": "./resources/cp.css",
    "dpi": "600",
    "encoding": "UTF-8",
    # "javascript-delay": "25000", # needs to be extra long for mathjax to render
    "margin-top": "0.75in",
    "margin-right": "0.75in",
    "margin-bottom": "0.75in",
    "margin-left": "0.75in",
    "no-outline": None,
    "disable-smart-shrinking": "",
    "enable-local-file-access": ""
}


def parse_args() -> argparse.Namespace:
    """argument parser"""

    ## parse CLI args
    parser = argparse.ArgumentParser(
        prog="composing_programs_to_pdf.py",
        description="Convert the online book 'Composing Programs' into a pdf file. See: https://www.composingprograms.com/",
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
    url: str = "https://www.composingprograms.com/pages/11-getting-started.html",
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
                src=f'https://www.composingprograms.com/img/{img_tag["src"].split("/")[-1]}',
            )
            img_tag.replace_with(new_img)
    return webelement


def _replace_href_paths(soup: BeautifulSoup, webelement: element.Tag) -> element.Tag:
    """add the url to the relative paths in href values"""
    for a_tag in webelement.find_all("a"):
        if a_tag.has_attr("href"):
            new_a = None
            if "../" in a_tag["href"]:
                new_a = soup.new_tag(
                    "a",
                    href=f'https://www.composingprograms.com/{a_tag["href"].split("/")[-1]}',
                )
                if a_tag.string:
                    new_a.string = a_tag.string
        elif a_tag.has_attr("onclick"):
            if "youtube" in a_tag["onclick"]:
                youtube_video_raw = re.search(
                    "http[s]?:\/\/(www\.)?youtube(.*)(?='\);)", a_tag["onclick"]
                ).group(0)
                youtube_video = "https://www.youtube.com/watch?v={}".format(
                    re.search("(?<=/embed/).*?(?=\?)", youtube_video_raw).group(0)
                )
                new_a = soup.new_tag(
                    "a",
                    href=youtube_video,
                )

                if a_tag.string:
                    new_a.string = "Link for the video lecture"
        if new_a:
            a_tag.replace_with(new_a)
    return webelement


def fix_links(soup: BeautifulSoup, webelement: element.Tag) -> element.Tag:
    """Wrapper for fixing issues with relative paths in anchor and image tags"""
    webelement = _replace_img_paths(soup=soup, webelement=webelement)
    webelement = _replace_href_paths(soup=soup, webelement=webelement)
    return webelement


def _create_webdriver() -> webdriver.Firefox:
    """create a firefox webdriver"""
    options = webdriver.FirefoxOptions()
    options.headless = True
    options.add_argument("-headless")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.binary_location = 'C:\\Program Files\\Mozilla Firefox\\firefox.exe'
    # options.add_argument(f'--proxy-server=http://127.0.0.1:20719')
    return webdriver.Firefox(options=options, service_log_path=os.devnull)


def _destroy_webdriver(driver: webdriver.Firefox) -> None:
    """destroy a firefox webdriver"""
    driver.quit()


def _requests_get_source_code(url: str) -> str:
    """scrape a page's source code using requests"""
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content.decode("utf-8", "ignore")


def _selenium_get_source_code(
    url: str, driver: Optional[webdriver.Firefox] = None, sleep: int = 10
) -> str:
    current_driver = driver or _create_webdriver()
    print(url)
    if 'www' not in url:
        url = url.replace('composingprograms', 'www.composingprograms')
    print(url)
    current_driver.get(url)
    time.sleep(sleep)
    page_source = current_driver.page_source
    if current_driver != driver:
        _destroy_webdriver(current_driver)
    return page_source


def scrape_chapter_content(
    url: str, use_selenium: bool = True, driver: Optional[webdriver.Firefox] = None
) -> str:
    """Scrape the chapter's inner content"""
    if not use_selenium:
        page_source = _requests_get_source_code(url=url)
    else:
        page_source = _selenium_get_source_code(url=url, driver=driver)
    soup = BeautifulSoup(page_source, "html.parser")
    inner_content = soup.select(".inner-content")[0]
    inner_content = fix_links(soup=soup, webelement=inner_content)
    with codecs.open("resources/header.html", encoding='utf8') as f:
        header_content = f.read()
    footer = """
    </body>
    </html>
    """
    return "\n".join([header_content, str(inner_content), footer])


def chapter_to_pdf(
    output_dir: str, url: str, driver: Optional[webdriver.Firefox] = None
) -> None:
    """Convert the html of a chapter to a pdf"""
    use_selenium = True if driver else False
    chapter_content = scrape_chapter_content(
        url, driver=driver, use_selenium=use_selenium
    )
    filename = os.path.join(output_dir, f"entry_{_fetch_chapter_number(url)}.pdf")
    pdfkit.from_string(
        chapter_content, filename, options=PDFKIT_OPTS, css="resources/cp.css"
    )


def make_cover(output_dir: str) -> None:
    """generate a pdf with the book's cover"""
    filename = os.path.join(output_dir, "entry.pdf")
    pdfkit.from_file(
        "resources/cover.html",
        filename,
        options=PDFKIT_OPTS,
        css="resources/cover_style.css",
    )


def merge_chapters(input_dir: list, book_path: str) -> None:
    """Merge all the chapters and number the pages"""
    # book file
    book_file = os.path.join(book_path, "composing-programs.pdf")
    # list and order all files by creation date
    all_files = [_.path for _ in os.scandir(input_dir)]
    all_files.sort(key=lambda x: os.path.getctime(x))
    ## loop across each file, read, and then merge
    # Call the PdfFileMerger
    mergedObject = PdfFileMerger()
    for cur_file in all_files:
        mergedObject.append(PdfFileReader(cur_file, "rb"))
    # Write all the files into one pdf
    mergedObject.write(book_file)
    # finally we number the pages and suppress the very verbose output of add_numbering_to_pdf()
    with contextlib.redirect_stdout(open(os.devnull, "w")):
        add_numbering_to_pdf(
            pdf_file=book_file,
            new_pdf_file_path=book_file,
            position="right",
            start_page=1,
            end_page=None,
            start_index=1,
            size=10,
            font="Helvetica",
        )

def make_book(
    book_path: str = "test", driver: Optional[webdriver.Firefox] = None
) -> None:
    """create the book"""
    temp_dir = tempfile.mkdtemp(prefix="interm-dir-book-")
    # make the cover page
    make_cover(output_dir=temp_dir)
    # chapter urls
    chapter_urls = fetch_chapter_urls()
    # for each, conert to pdf
    for chapter_url in chapter_urls:
        chapter_to_pdf(output_dir=temp_dir, url=chapter_url, driver=driver)
    # merge into one book
    merge_chapters(input_dir=temp_dir, book_path=book_path)
    # delete tempdir
    shutil.rmtree(temp_dir)


def main() -> None:
    args = parse_args()
    output_path = args.output_path
    my_webdriver = _create_webdriver()
    make_book(book_path=output_path, driver=my_webdriver)
    print(f"[+] A pdf version of 'Composing Programs' was saved in: {output_path}")
    _destroy_webdriver(my_webdriver)


if __name__ == "__main__":
    main()
