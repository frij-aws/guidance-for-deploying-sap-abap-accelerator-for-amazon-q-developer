# Good ABAP Practices

You are an ABAP and AWS expert. Use these guidelines when writing ABAP code.

## Before You Start — Ask If You Don't Know

- What version of ABAP to target? Typical answers: NetWeaver 7.40 sp8, S/4HANA, BTP ABAP
- Should the code be a report or a runnable ABAP unit test?
- If writing in abapGit format, what package should the objects go into?

## Output

- If asked to save code to files, use abapGit filename conventions and file formats (see `abapgit-format.md`).

## ABAP Coding Tips

- When writing CATCH clauses, if the list of exceptions includes a superclass of child exceptions, you MUST list the child exceptions before the superclasses. Recursively search the exception class hierarchy.
- Escape variables with the `@` character in SQL statements.
- Parameters are limited to 8 characters.
- Parameters with lowercase data need the `LOWER CASE` keyword.
- Mandatory parameters need the `OBLIGATORY` keyword.
- `MESSAGE` clause in `EXCEPTIONS` is not supported in older ABAP versions — use `sy-subrc` instead.
- When calling RFC functions with `DESTINATION 'NONE'`, `system_failure` and `communication_failure` exceptions will catch short dumps in the called function.
- Break long string templates across several lines with `&&`.
- Use `CL_ABAP_TSTMP` for timestamp math.
- Inputs such as SDK profile and bucket names should be `PARAMETERS`.
- ABAP parameter names are limited to 8 characters.

## ABAP Style

- Favor object-oriented approaches where practical.
- Write objects using local classes where possible. Avoid using `FORM`.
- End hardcoded text with `##NO_TEXT`.

## Adding Functions to Function Groups in abapGit Format

When adding a new function module to an existing function group:

1. **Function Module File**: Create `<function_group>.fugr.<function_name>.abap`
   - Contains the FUNCTION...ENDFUNCTION code
   - Local interface is in comments at the top

2. **Authorization Object File**: Create `<function_name>    rf.sush.xml` (note: 4 spaces before `rf`)
   - Contains authorization check metadata (S_RFC object)
   - Uses LCL_OBJECT_SUSH serializer

3. **Do NOT create** a separate XML file for the function itself — the function group XML handles that

## Development Process

- Know the Git repo's SDK profile (likely `FRIJ_SBX`).
- Know the SAP system's SDK profile (likely `SDK_DEMO`). Use this to communicate with the SAP system and check assets manually. The SAP system may use a different internal name (e.g., `DEMO`) — use that when running reports inside the SAP system.
- To interact with the SAP system, use the tools in the ABAP Accelerator MCP server.
- Any time you send code to the SAP system:
  1. Push the code to Git
  2. In the SAP system: pull in abapGit
  3. Activate the package
  4. Run the ATC
  5. Run the reports and examine the results
