"""Command-line entry point for the EconomicsProject backend.

Run the game API server (the normal case):
    python -m economicsproject.main

Run a one-off console demo of the modeling pipeline instead:
    python -m economicsproject.main --demo
"""

from __future__ import annotations

import argparse
import os

from .dataset import load_prepared_dataset
from .modeling import fit_logit_model


def run_demo() -> None:
    """Fit one example model and print it, mainly to sanity-check the setup."""
    dataset = load_prepared_dataset()
    # Individual categories are picked directly -- not the whole "Industry"
    # field toggled on at once.
    example_columns = [
        "Original Ask Amount",
        "Original Offered Equity",
        "Valuation Requested",
        "Industry_Food and Beverage",
        "Industry_Technology/Software",
    ]
    fitted = fit_logit_model(example_columns, dataset)

    print("EconomicsProject environment is set up and working!")
    print(fitted.equation)
    print(f"Train pseudo R^2: {fitted.train_pseudo_r_squared:.4f}")
    print(
        "Basic test (seasons 8-10) -- accuracy: "
        f"{fitted.basic_test.accuracy:.4f}, "
        f"yes-deal accuracy: {fitted.basic_test.yes_deal_accuracy:.4f}, "
        f"no-deal accuracy: {fitted.basic_test.no_deal_accuracy:.4f}"
    )


def run_server() -> None:
    """Launch the game API (see server.py / API_PROTOCOL.md)."""
    import uvicorn

    if os.environ.get("PROFESSOR_API_KEY") is None:
        print(
            "WARNING: PROFESSOR_API_KEY is not set, using the insecure default. "
            "Set it before running a real session."
        )

    uvicorn.run(
        "economicsproject.server:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo", action="store_true", help="run a one-off console demo instead of the API server"
    )
    args = parser.parse_args(argv)

    if args.demo:
        run_demo()
    else:
        run_server()


if __name__ == "__main__":
    main()
