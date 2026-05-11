
# ⚡ CodeDebug AI – Smart Code Debugging Assistant

An advanced, AI-powered web application that analyzes code, detects errors, and explains issues in beginner-friendly language.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install flask flask-cors google-generativeai python-dotenv
```

### 2. Add Gemini API Key (for Full AI Mode)
Edit the `.env` file and add your key:
```
GEMINI_API_KEY=your_key_here
```
Get a free key at: https://aistudio.google.com/app/apikey

> Without a key, the app still works using **static analysis mode**.

### 3. Run the App
```bash
python app.py
```
Open your browser at: **http://127.0.0.1:5000**

---

## ✨ Features

| Feature | Static Mode | AI Mode |
|---|---|---|
| Syntax error detection | ✅ | ✅ |
| Logic/pattern detection | ✅ | ✅ |
| Beginner-friendly explanations | ✅ | ✅ *(richer)* |
| Corrected code generation | ❌ | ✅ |
| Fix suggestions | ❌ | ✅ |
| Concept explanations | ❌ | ✅ |
| Complexity analysis | ❌ | ✅ |
| Optimization tips | ❌ | ✅ |

## 🌐 Supported Languages
Python · JavaScript · TypeScript · Java · C++ · C · C# · Go · Rust · PHP · Ruby · SQL

## ⌨️ Keyboard Shortcut
Press **Ctrl + Enter** in the editor to run analysis instantly.

## 📁 Project Structure
```
code-debug-assistant/
├── app.py              # Flask backend with AI analysis
├── .env                # API key config
├── templates/
│   └── index.html      # Main UI template
└── static/
    ├── css/style.css   # All styles (dark/light theme)
    └── js/app.js       # Frontend logic + CodeMirror
```
