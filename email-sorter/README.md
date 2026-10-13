# Inbox sorter (Sprint 1 prototype)

Fetches recent emails, classifies each with a local Llama model into
(1) content type and (2) reply/action type, and shows the result on a local web page.

## Setup (Windows, VS Code terminal)
    python -m venv .venv
    .email_cl\Scripts\Activate.ps1
    pip install -r requirements.txt
    copy .env.example .env
    ollama pull llama3.1:8b
    python run.py
Open http://127.0.0.1:5000

## Where to change things
- Categories and wording: app/taxonomy.py
- Prompt and model call: app/classifier.py
- New mail source: add a file in app/providers/ and one line in app/providers/__init__.py
