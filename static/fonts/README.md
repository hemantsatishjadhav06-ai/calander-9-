# Fonts

The app and the public pages use the system font (SF Pro on Apple devices,
Segoe UI on Windows, Roboto on Android), so no web font loads on any page and
nothing is fetched from a CDN under the `font-src 'self'` Content Security
Policy.

One file is kept as a documented fallback, in case uniform rendering across
platforms is ever preferred over the native font. Nothing references it today.

| Family | Files | License |
|---|---|---|
| Inter (Rasmus Andersson), variable weight 400–700 | `inter-latin-normal.woff2` | SIL Open Font License 1.1 |

Inter was downloaded from Google Fonts (https://fonts.google.com), which
distributes it under the SIL Open Font License, version 1.1
(https://openfontlicense.org). The font software is used unmodified.
