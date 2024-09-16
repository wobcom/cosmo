import sys
import warnings

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Logger:

    def __init__(self, name):
        self.name = name
        warnings.warn("Logger is deprecated, please use native "
                      "errors and specific warnings / error types "
                      "where applicable.", DeprecationWarning)

    def warning(self, text):
        print(bcolors.FAIL + f"Warning: {text}" + bcolors.ENDC, file=sys.stderr)

    def error(self, text):
        print(bcolors.FAIL + f"Error: {text}" + bcolors.ENDC, file=sys.stderr)

    def info(self, text):
        print(bcolors.OKGREEN + f"Info: {text}" + bcolors.ENDC, file=sys.stdout)

    def hint(self, text):
        print(bcolors.OKCYAN + f"{text}" + bcolors.ENDC, file=sys.stdout)
