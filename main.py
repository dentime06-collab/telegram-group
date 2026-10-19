import sys
from tgs.gui import main

if __name__ == '__main__':
    raise SystemExit(main('--smoke-test' in sys.argv))
