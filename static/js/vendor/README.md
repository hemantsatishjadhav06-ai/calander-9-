These runtime dependencies are served locally so the application remains usable
when a CDN is blocked or unavailable. Their distributions and license notices
are copied unchanged from the pinned npm releases:

| Package | Version | Files | Verified npm tarball integrity |
| --- | --- | --- | --- |
| flatpickr | 4.6.13 | `flatpickr.min.js`, `flatpickr.min.css`, `flatpickr.LICENSE.md` | `sha512-97PMG/aywoYpB4IvbvUJi0RQi8vearvU0oov1WW3k0WZPBMrTQVqekSX5CjSG/M4Q3i6A/0FKXC7RyAoAUUSPw==` |
| chart.js | 4.4.6 | `chart.umd.js`, `chart.umd.js.map`, `chartjs.LICENSE.md` | `sha512-8Y406zevUPbbIBA/HRk33khEmQPk5+cxeflWE/2rx1NJsjVWMPw/9mSP9rxHP5eqi6LNoPBVMfZHxbwLSgldYA==` |
| sortablejs | 1.15.6 | `Sortable.min.js`, `sortablejs.LICENSE` | `sha512-aNfiuwMEpfBM/CN6LY0ibyhxPfPbyFeBTYJKCvzkJ2GkUpazIt3H+QIPAMHwqQ7tMKaHz1Qj+rJJCqljnf4p3A==` |

To update one dependency, retrieve the intended version from `registry.npmjs.org`,
verify the tarball against that release's `dist.integrity`, then copy the listed
distribution files and corresponding license. Update the version and integrity
above and exercise the date/time controls, analytics charts, and draggable UI.

This directory also contains the existing vendored Alpine focus plugin and
CropperJS distributions, whose license notices are included in their files.
