import importlib.util

pkgs = ['praw', 'groq', 'sentence_transformers', 'pandas', 'streamlit', 'sklearn']
for p in pkgs:
    spec = importlib.util.find_spec(p)
    status = "OK" if spec else "MISSING"
    print(f"{p}: {status}")
