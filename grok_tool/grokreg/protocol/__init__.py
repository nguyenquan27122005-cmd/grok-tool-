"""Protocol HTTP registration (competitor-style pure HTTP path)."""
from grokreg.protocol.backend import (  # noqa: F401
    ProtocolEnvironmentError,
    ProtocolRegistrationBackend,
    SignupParameterDiscovery,
    build_protocol_session,
    build_signup_payload,
    clear_identity_cookies,
    read_sso_cookie_from_session,
)
from grokreg.protocol.worker import register_one_protocol  # noqa: F401
