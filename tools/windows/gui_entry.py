import argparse
from tbs.gui.app import main

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--smoke",action="store_true")
    args=parser.parse_args()
    raise SystemExit(main(smoke=args.smoke))
