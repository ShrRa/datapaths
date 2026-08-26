class DatapathsError(RuntimeError):
    pass

class ConfigError(DatapathsError):
    pass

class RegistryError(DatapathsError):
    pass

class ArtifactError(DatapathsError):
    pass
