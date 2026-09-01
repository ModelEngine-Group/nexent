"""
Regenerate final_test_report.md from existing spec/perf report files.
Usage: python test/scale/generate_report.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import generate_final_report_md

if __name__ == "__main__":
    generate_final_report_md()
    print("Report generated: test/scale/final_test_report.md")
