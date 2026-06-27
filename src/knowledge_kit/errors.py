class KnowledgeKitError(Exception):
    """带稳定机器码的基础异常。"""

    code = "knowledge_kit_error"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.code)


class ConfigError(KnowledgeKitError):
    code = "config_error"


class KnowledgeNotFound(KnowledgeKitError):
    code = "knowledge_not_found"


class KnowledgeDisabled(KnowledgeKitError):
    code = "knowledge_disabled"


class KnowledgeReadOnly(KnowledgeKitError):
    code = "knowledge_read_only"


class WriteTargetRequired(KnowledgeKitError):
    code = "write_target_required"


class SourceRequired(KnowledgeKitError):
    code = "source_required"


class UpdateAmbiguous(KnowledgeKitError):
    code = "update_ambiguous"
