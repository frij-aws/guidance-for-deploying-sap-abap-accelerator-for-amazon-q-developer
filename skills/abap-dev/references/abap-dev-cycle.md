# ABAP Development Cycle

End-to-end workflow for developing ABAP code via abapGit and the ABAP Accelerator MCP tools.

## Phase 1: Repository Setup (one-time)

a. Create a new Git repository if one does not already exist for the package.
   Initialise it with the required abapGit boilerplate:
   - A `.abapgit.xml` file describing the package and branch. If missing or empty, use this as a starting point:
     ```xml
     <?xml version="1.0" encoding="utf-8"?>
     <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
      <asx:values>
       <DATA>
        <MASTER_LANGUAGE>E</MASTER_LANGUAGE>
        <STARTING_FOLDER>/src/</STARTING_FOLDER>
        <FOLDER_LOGIC>PREFIX</FOLDER_LOGIC>
        <IGNORE></IGNORE>
       </DATA>
      </asx:values>
     </asx:abap>
     ```
   - A `src/` directory that will hold the serialised ABAP source files.
   - A `README.md` with a brief description of the package.

b. Push the initialised repository to the remote Git host (e.g. GitHub, GitLab, CodeCommit):
   ```bash
   git add .
   git commit -m "Initial abapGit boilerplate"
   git push origin main
   ```

c. In the SAP system, create the ABAP package if it does not already exist.
   Use the MCP tool `aws_abap_cb_create_object` with type `DEVC`.

d. Link the Git repository to the ABAP package in abapGit.
   First check whether the link already exists with `abapgit_list_repos`.
   If it does not exist, create it with `abapgit_create_repo`, providing the
   Git URL, ABAP package name, and branch name.

## Phase 2: Development Cycle (iterative)

a. Write or modify ABAP source files on the local filesystem in abapGit
   serialisation format (see `abapgit-format.md`).

b. Optionally run `abaplint` to pretty-print the code and check for syntax
   and style errors before pushing:
   ```bash
   npx abaplint
   ```

c. Push the local changes to the remote Git repository:
   ```bash
   git add .
   git commit -m "Your change description"
   git push origin main
   ```

d. Trigger an abapGit pull in the SAP system using `abapgit_pull` to import
   the changes from Git into the SAP system.

e. If the pull fails, review the error message returned by `abapgit_pull`,
   correct the source files, and return to step (a).

f. Activate the imported objects using `aws_abap_cb_activate_object`.

g. If activation fails with a clear error, correct the source files and return
   to step (a). If the error is unclear, proceed to step (h).

h. Run ATC checks using `aws_abap_cb_run_atc_check` to identify code quality
   and compliance errors.

i. Review ATC results; if errors are found, correct the source files and return
   to step (a).

j. Run unit tests using `aws_abap_cb_run_unit_tests` if test classes exist for
   the changed objects.

k. Review unit test failures; if failures are found, correct the source files
   and return to step (a).
