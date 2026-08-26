class DatapathsError(RuntimeError):
    pass

class ConfigError(DatapathsError):
    pass

class RegistryError(DatapathsError):
    pass

class ArtifactError(DatapathsError):
    pass

class ConfigWarning(UserWarning):
    """A config file was usable, but part of it was not."""

class ArtifactWarning(UserWarning):
    """An artifact operation succeeded, but not quite as asked."""
