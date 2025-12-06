#!/usr/bin/env bash
# Build script for Render deployment

set -o errexit  # Exit on error

# Install Python dependencies
pip install -r requirements.txt

# Download spaCy English language model
python -m spacy download en_core_web_sm

echo "Build completed successfully"
