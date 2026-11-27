"""Known provider failures, distinct from uncertain transport outcomes."""


class ProviderTaskFailed(RuntimeError):
    """The provider explicitly reported a terminal failure."""


class ProviderSubmissionRejected(ProviderTaskFailed):
    """The provider explicitly rejected the submission without accepting a task."""
