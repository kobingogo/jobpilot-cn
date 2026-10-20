# Custom Templates

This folder holds user-registered templates (LaTeX, Typst, or any other toolchain with a declared compile command), managed by the `/add-template` command. The framework works out of the box with its stock templates (moderncv for CVs, `cover.cls` for cover letters).

`templates/cn/` is the exception: a shipped one-page Chinese résumé (ctex / xeCJK, optional photo, example marked 虚构). It is not registered through `/add-template`. `/apply` selects it when the CV language is Chinese and no custom template is active. See `templates/cn/README.md`. The `cv/` and `cover_letters/` layout below is only for templates you register yourself.

## Layout

```
templates/
├── cv/
│   └── <template-name>/
│       ├── template.<ext>  # Profile-agnostic skeleton ([PLACEHOLDER] tokens), e.g. template.tex or template.typ
│       ├── TEMPLATE.md      # Manifest: source extension, compile command, fonts, page limit, style rules, pitfalls
│       ├── *.cls / *.sty    # Custom class/style files, or Typst packages (if the template needs them)
│       └── fonts/           # Bundled font files (if not using system fonts)
└── cover_letters/
    └── <template-name>/
        └── (same layout)
```

## How it works

- `/add-template` interviews you for the template's instructions (source extension, compile command, fonts, style rules, page limit), stores the files here, and runs a mandatory test compile before registering anything.
- Activating a template adds a managed block to `05-cv-templates.md` or `06-cover-letter-templates.md`, which is what `/apply` reads when drafting and compiling — no other wiring needed.
- `/add-template --list` shows registered templates; `/add-template --use <name>` switches; `/add-template --use default` reverts to the stock templates.

Templates are stored with `[PLACEHOLDER]` tokens instead of personal data, so they are safe to commit and share.
