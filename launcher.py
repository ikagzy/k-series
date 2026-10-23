import sys

from k_optimizer.cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main())
    from k_optimizer.ui import run

    run()
