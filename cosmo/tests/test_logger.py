import pytest
from cosmo.logger import bcolors, Logger

TSTNAME = 'test logger'
TSTTEXT = 'test text'

def test_colors(capsys):
    l = Logger(TSTNAME)

    l.warning(TSTTEXT)
    assert bcolors.FAIL in capsys.readouterr().out

    l.error(TSTTEXT)
    assert bcolors.FAIL in capsys.readouterr().out

    l.info(TSTTEXT)
    assert bcolors.OKGREEN in capsys.readouterr().out

    l.hint(TSTTEXT)
    assert bcolors.OKCYAN in capsys.readouterr().out
