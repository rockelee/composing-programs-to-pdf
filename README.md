# Composing programs to pdf

Python script for converting the online book "Composing Programs" (https://composingprograms.com/) to pdf using pdfkit and pdflatex.

```bash
python3 composing_programs_to_pdf.py -o "./sample"
```

# TO-DO:
- [X] Fix the img and href relative path issues
- [X] Center tand justify the text
- [X] Fix latex (mathjax) expressions not being rendered
- [ ] Fix mid-sentence page breaks


# run on windows with python 3.7

1) install wkhtmltox
2) add wkhtmltox to PATH
3) download geckodriver v0.31-win64  and add geckodriver to PATH
4) python -m venv env
5) env\Scripts\activate.bat
5) pip install -r requirements.txt
6) python composing_programs_to_pdf.py -o output_path