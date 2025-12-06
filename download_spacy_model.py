#!/usr/bin/env python3
"""
Download spaCy language model for NLP-based adjective extraction.
Run this during deployment: python download_spacy_model.py
"""
import subprocess
import sys

def download_spacy_model():
    """Download the English language model for spaCy."""
    try:
        print("Downloading spaCy English model (en_core_web_sm)...")
        subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
        print("✓ spaCy model downloaded successfully")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to download spaCy model: {e}")
        sys.exit(1)

if __name__ == "__main__":
    download_spacy_model()
