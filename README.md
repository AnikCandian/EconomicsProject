# EconomicsProject

A basic Python environment for economics-related data analysis and scripting.

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements-dev.txt
   ```

   (Use `requirements.txt` instead if you don't need dev/test tools like `pytest`.)

3. Install the project in editable mode so `economicsproject` is importable:

   ```bash
   pip install -e .
   ```

## Usage

Run the sample entry point:

```bash
python -m economicsproject.main
```

## Testing

```bash
pytest
```

## Project structure

```
.
├── src/
│   └── economicsproject/   # package source
├── tests/                  # test suite
├── requirements.txt        # core dependencies (numpy, pandas, matplotlib, scipy, statsmodels, jupyter)
├── requirements-dev.txt    # dev/test dependencies
└── pyproject.toml          # package metadata
```
