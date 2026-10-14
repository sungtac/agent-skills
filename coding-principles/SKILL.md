---
name: coding-principles
description: Apply or display the user's shared coding and skill-implementation principles. Use when the user says "코딩 원칙", asks for the established implementation principles, or asks that a new skill follow them.
---

# Coding Principles

Treat [CODING_PRINCIPLES.md](CODING_PRINCIPLES.md) as the user's default implementation policy for skills and supporting automation.

- When the user asks to apply these principles, read the document and use it as the default unless a more specific user instruction conflicts.
- When the user says `코딩 원칙 출력해줘`, `코딩 원칙 보여줘`, or makes an equivalent request, return the document verbatim without adding implementation commentary.
- When the user explicitly asks to upgrade, revise, or replace the coding principles, overwrite `CODING_PRINCIPLES.md` with the approved new text. It is the single current source of truth: do not create a versioned copy or merge obsolete rules unless the user asks for a history.
- Do not treat the principles as permission to change systems, access cloud files, install software, or make external writes beyond the user's current request.
