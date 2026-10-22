# Vendored browser dependencies

These assets are served locally; exhibition workflows do not require a public CDN at runtime.

| Package | Version | Files | License |
| --- | --- | --- | --- |
| Bootstrap | 5.3.8 | `bootstrap.min.css` | `bootstrap.LICENSE` (MIT) |
| html5-qrcode | 2.3.8 | `html5-qrcode.min.js` | `html5-qrcode.LICENSE` (Apache-2.0) |

Downloaded using verified HTTPS from the npm registry. Before extracting these files, the complete package tarballs were checked against the registry's SHA-512 integrity metadata:

- `https://registry.npmjs.org/bootstrap/-/bootstrap-5.3.8.tgz`: `sha512-HP1SZDqaLDPwsNiqRqi5NcP0SSXciX2s9E+RyqJIIqGo+vJeN5AJVM98CXmW/Wux0nQ5L7jeWUdplCEf0Ee+tg==`
- `https://registry.npmjs.org/html5-qrcode/-/html5-qrcode-2.3.8.tgz`: `sha512-jsr4vafJhwoLVEDW3n1KvPnCCXWaQfRng0/EEYk1vNcQGcG/htAdhJX0be8YyqMoSz7+hZvOZSTAepsabiuhiQ==`

To update, retrieve the version's registry metadata over HTTPS, verify the downloaded tarball against its published `dist.integrity`, retain its license and replace only the necessary browser asset. Do not disable TLS or integrity verification.
