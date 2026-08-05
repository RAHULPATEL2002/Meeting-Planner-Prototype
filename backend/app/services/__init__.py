"""Business logic that is deliberately kept out of the routers.

Routers stay thin (parse, authorise, delegate, serialise) so the interesting
rules — conflict detection, invite resolution, image normalisation — can be
unit-tested without an HTTP client.
"""
