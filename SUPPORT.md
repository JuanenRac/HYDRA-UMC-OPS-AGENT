# Support Information 🛠️ (HYDRA-UMC-OPS-AGENT)

Thank you for using HYDRA-UMC-OPS-AGENT! Here is how you can get help:

## 📺 Video Tutorials & Demos

The best way to see how this project's own maintenance-incident lifecycle
works is through our official YouTube channel:
[youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## ✉️ Direct Technical Inquiries

For questions about running the edge role on your own CM5, the
control-plane role on a development host, or anything not covered by the
README:
Email: `electrohobby3d@gmail.com`

## 🐛 Bug Reports

If `hydra-umc-ops-agent edge collect` reports the wrong project version, an
inaccurate health-check result, or a real secret shape that
`log_redaction.py` fails to redact (see `SECURITY.md` for that last one
specifically - report it privately, not as a public Issue), please open a
**GitHub Issue** in this repository - include the exact command you ran
and its full, real output.
*Please search existing issues before opening a new one.*

## ❌ What is NOT support?

- This is Delivery 1 (read-only observability) of a 6-delivery plan - it
  cannot yet invoke an AI provider, propose or apply a patch, or deploy
  anything. Please do not open an Issue asking it to do something a later
  delivery has not shipped yet; see the README's own Roadmap section for
  what is planned and when.
- This project coordinates other real HYDRA-UMC/URTC projects
  (HYDRA-UMC-OS, HYDRA-UMC-UPDATER, HYDRA-UMC-SDK, etc.) - a real bug
  inside one of THOSE projects' own code belongs on their own issue
  tracker, not this one's.
