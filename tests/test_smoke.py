from causpec import __version__
from causpec.cli import build_parser


def test_version_is_set() -> None:
    assert __version__


def test_cli_parser_builds() -> None:
    assert build_parser().prog == "causpec"
