import re


_PROVIDER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate_provider_name(name: str) -> str:
    if not _PROVIDER_NAME_RE.fullmatch(name):
        raise ValueError(
            "provider name must start with a letter or digit and contain only "
            "letters, digits, underscores, and hyphens"
        )
    return name
