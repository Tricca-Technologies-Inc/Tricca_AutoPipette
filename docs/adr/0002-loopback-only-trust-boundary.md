# `tapd` and the kiosk stay loopback-only forever; remote access is a reverse-proxy concern

**Status:** accepted

Neither `tapd`'s control plane nor the kiosk has any application-level
authentication (see #32). We decided this stays permanent — no login, token,
or origin check gets built into either process — because the trust boundary
that matters here isn't "who can authenticate to this web app," it's "who has
network access to this exact host": an unauthenticated request here doesn't
leak data, it moves a gantry and drives a syringe. Building and maintaining
auth logic in either process would be new attack surface for a threat model
("stray/malicious request on the local network") better solved by never
exposing the socket in the first place.

Future multi-machine access (e.g. checking on a rig from another room over a
private Tailscale network) is accepted as a real future need, but is
deliberately **not** solved by widening `tapd`'s or the kiosk's own bind
address. The intended shape is a same-box reverse proxy (e.g. `tailscale serve`
pointed at the existing loopback port) sitting on the tailnet-facing side and
forwarding to loopback — Tailscale's own ACLs/auth do the vetting, and
`tapd`/the kiosk never bind anywhere but `127.0.0.1`. This keeps the "loopback
only" invariant literally true in the code regardless of what's layered in
front of it on the network side, and answers #32's open question of whether
remote reachability is needed at all: yes, but only via a proxy in front of an
unchanged bind, never by changing the bind itself.
