# Third-party notices

rtl-sdr-analyzer itself is released under the MIT License (see `LICENSE`).
Standalone builds also bundle the Python runtime and the Python packages listed in
`pyproject.toml` (NumPy, FastAPI, Starlette, Uvicorn, Pydantic, Typer, Rich, structlog,
PyYAML, ...), each under its own permissive license.

## Windows builds only

The Windows archive ships unmodified binaries from the
**RTL-SDR Blog driver release V1.4.0**
(<https://github.com/rtlsdrblog/rtl-sdr-blog/releases/tag/V1.4.0>):

| File | Project | License | Source |
|---|---|---|---|
| `rtlsdr.dll` | rtl-sdr (RTL-SDR Blog fork of Osmocom rtl-sdr) | GPL-2.0-or-later | <https://github.com/rtlsdrblog/rtl-sdr-blog> |
| `pthreadVC2.dll` | pthreads-win32 | LGPL-2.1-or-later | <https://sourceware.org/pthreads-win32/> |
| `msvcr100.dll` | Microsoft Visual C++ 2010 runtime | Microsoft redistributable | — |

These libraries are separate programs loaded at runtime through `ctypes`; they are not
linked into rtl-sdr-analyzer. The corresponding source code is available at the links
above, and on request through the project's issue tracker.

## macOS / Linux builds

No RTL-SDR library is bundled; the system `librtlsdr` (Homebrew / distribution package)
is used.

## Fonts (all builds)

Bricolage Grotesque, Figtree and DM Mono are bundled under the SIL Open Font License 1.1;
license texts live in `rtl_sdr_analyzer/web/static/amstech-ui/fuentes/`.
