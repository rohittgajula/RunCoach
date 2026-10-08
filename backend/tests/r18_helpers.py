"""R18 test helpers."""


def nodv(body: dict) -> dict:
    """A mutation body without R18's additive `data_version` key."""
    return {k: v for k, v in body.items() if k != "data_version"}
