#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
source venv/bin/activate
python -m streamlit run app.py
