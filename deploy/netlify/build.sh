#!/usr/bin/env bash
# Netlify build for the front door: point the proxy rule in netlify.toml at the Render web service.
# Refuses to build unless RENDER_ORIGIN is a plain https origin (scheme, host, optional port).
set -euo pipefail
cd "$(dirname "$0")"

origin="${RENDER_ORIGIN:-}"
origin="${origin%/}"
pattern='^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$'

if [[ -z "$origin" ]]; then
  echo "RENDER_ORIGIN is not set. Set it on the Netlify site to the web service's address, e.g. https://sm-bean-web.onrender.com" >&2
  exit 1
fi
if [[ ! "$origin" =~ $pattern ]]; then
  echo "RENDER_ORIGIN must be an https origin with nothing after the host, e.g. https://sm-bean-web.onrender.com" >&2
  exit 1
fi
if ! grep -q "__RENDER_ORIGIN__" netlify.toml; then
  echo "netlify.toml has no __RENDER_ORIGIN__ placeholder left to replace; build from a clean checkout." >&2
  exit 1
fi

sed -i "s|__RENDER_ORIGIN__|${origin}|" netlify.toml
mkdir -p public
printf 'This site proxies every request to the SM Bean web service (deploy/netlify/netlify.toml).\n' > public/front-door.txt

echo "Front door: every path is proxied to ${origin}, signed with FRONT_DOOR_SIGNING_SECRET."
if [[ -z "${FRONT_DOOR_SIGNING_SECRET:-}" ]]; then
  echo "Note: FRONT_DOOR_SIGNING_SECRET is not visible to this build. That is fine if it is scoped to Runtime only;"
  echo "without it at runtime the web service cannot tell one visitor from another."
fi
