---
name: abap-dev
description: ABAP development with AWS and abapGit. Use when writing ABAP code, working with abapGit file formats, using the AWS SDK for SAP ABAP, or following the ABAP development cycle of push-pull-activate-test.
metadata:
  author: frij-aws
  version: 1.0.0
---

## ABAP Development Guidance

This skill covers four areas of ABAP development with AWS:

1. **abapGit file format** — exact XML/ABAP serialization rules to avoid constant diffs when working with abapGit repositories
2. **ABAP development cycle** — end-to-end workflow from repo setup through push, pull, activate, ATC, and unit tests
3. **AWS SDK for SAP ABAP** — session/client creation, data type mappings, paginators, waiters, presigned URLs, and exception handling
4. **Good ABAP practices** — coding tips, style guidelines, and function group conventions

## Reference Files

- `references/abapgit-format.md` — abapGit XML/ABAP serialization format reference
- `references/abap-dev-cycle.md` — iterative development cycle with MCP tools
- `references/abap-sdk.md` — AWS SDK for SAP ABAP runtime reference
- `references/good-abap.md` — ABAP coding tips and style guidelines

## When to Use

Load this skill when:
- Writing or editing ABAP source files in abapGit format
- Setting up a new abapGit repository and linking it to a SAP package
- Calling AWS services from ABAP using the AWS SDK for SAP ABAP
- Running the push → pull → activate → ATC → test cycle
- Unsure about ABAP coding conventions or exception handling order
