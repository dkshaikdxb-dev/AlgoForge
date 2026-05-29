"""services/ — domain services that span more than one router.

Service modules are imported by routers; they MUST NOT import from routers/
(to avoid circular deps). Heavy business logic lives here once a second
consumer exists; small one-shot helpers stay in routers/.
"""
