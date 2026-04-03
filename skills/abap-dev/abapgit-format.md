# abapGit File Format Reference

## General XML Rules

- XML declaration: `<?xml version="1.0" encoding="utf-8"?>` — no BOM, no trailing whitespace
- Root element: `<abapGit version="v1.0.0" serializer="LCL_OBJECT_XXXX" serializer_version="v1.0.0">`
- Indentation: 1 space per level (not 2, not 4)
- All XML tag names are UPPERCASE (SAP field names)
- File ends with a single trailing newline after `</abapGit>`

## File Naming Conventions

| Object Type    | Files                                                       |
|----------------|-------------------------------------------------------------|
| Report/Program | `<name>.prog.abap` + `<name>.prog.xml`                      |
| Class          | `<name>.clas.abap` + `<name>.clas.xml` + optional includes |
| Interface      | `<name>.intf.abap` + `<name>.intf.xml`                      |
| Data Element   | `<name>.dtel.xml`                                           |
| Table          | `<name>.tabl.xml`                                           |
| Package        | `package.devc.xml`                                          |
| Function Group | `<fugr>.fugr.abap` + `<fugr>.fugr.xml` + per-FM files      |

All filenames are **lowercase**. Object names inside XML content are **UPPERCASE**.

## Report / Program XML (`*.prog.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_PROG" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <PROGDIR>
    <NAME>YMON_MY_REPORT</NAME>
    <DBAPL>S</DBAPL>
    <DBNA>D$</DBNA>
    <SUBC>1</SUBC>
    <APPL>S</APPL>
    <FIXPT>X</FIXPT>
    <LDBNAME>D$S</LDBNAME>
    <UCCHECK>X</UCCHECK>
   </PROGDIR>
   <TPOOL>
    <item>
     <ID>R</ID>
     <ENTRY>My Report Title</ENTRY>
     <LENGTH>15</LENGTH>
    </item>
   </TPOOL>
  </asx:values>
 </asx:abap>
</abapGit>
```

Key fields:
- `SUBC`: `1` = executable report, `I` = include program
- `DBAPL>S`, `DBNA>D$`, `LDBNAME>D$S` — standard values for executable reports
- `FIXPT>X` — fixed point arithmetic (always set)
- `UCCHECK>X` — Unicode check (always set)
- `APPL>S` — application class (S = basis/tools). Omit if not needed.
- `TPOOL/item/LENGTH` — **must exactly equal `strlen(ENTRY)`**. Count carefully — wrong LENGTH causes abapGit pull errors. If you change the title text, recount and update LENGTH.

## Class ABAP Source Format (`*.clas.abap`)

**CRITICAL**: abapGit serializes the public section of a class in a specific mixed-case format that differs from hand-written ABAP. When abapGit pulls a class from the SAP system and writes it to git, it uses this format. You must match it exactly or abapGit will show constant diffs.

The format uses:
- Lowercase ABAP keywords (`class`, `definition`, `public`, `methods`, `importing`, etc.)
- UPPERCASE object/type names (`YCL_MON_STATE`, `STRING`, `YCX_MON_STATE`)
- `!` prefix on all parameter names in the public section
- A space before the closing `.` on each statement
- Blank line after `public section.`
- `protected section.` appears even if empty (between public and private)
- `CLASS CLASSNAME IMPLEMENTATION.` uses UPPERCASE class name
- Blank line after `CLASS ... IMPLEMENTATION.`
- Blank line between each METHOD...ENDMETHOD block
- No trailing blank line before `ENDCLASS.`

```abap
class YCL_MON_MY_CLASS definition
  public
  final
  create public .

public section.

  methods MY_METHOD
    importing
      !IV_PARAM type STRING
    returning
      value(RV_RESULT) type STRING .
  methods MY_OTHER_METHOD
    importing
      !IV_INPUT type STRING
    raising
      YCX_MON_ERROR .
protected section.
  PRIVATE SECTION.
    " ... private types, data, methods in normal ABAP style ...
ENDCLASS.



CLASS YCL_MON_MY_CLASS IMPLEMENTATION.


  METHOD my_method.
    " implementation in normal ABAP style
  ENDMETHOD.


  METHOD my_other_method.
    " implementation
  ENDMETHOD.

ENDCLASS.
```

Key observations:
- The public section uses the SE24 serialization format (mixed case, `!` params, trailing space-dot)
- The private section and implementation use normal ABAP style (uppercase keywords, no `!`, no trailing space-dot)
- Two blank lines between `ENDCLASS.` of definition and `CLASS ... IMPLEMENTATION.`
- One blank line after `CLASS ... IMPLEMENTATION.`
- One blank line between each method implementation

## Class XML (`*.clas.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_CLAS" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <VSEOCLASS>
    <CLSNAME>YCL_MON_MY_CLASS</CLSNAME>
    <LANGU>E</LANGU>
    <DESCRIPT>Short description</DESCRIPT>
    <STATE>1</STATE>
    <CLSCCINCL>X</CLSCCINCL>
    <FIXPT>X</FIXPT>
    <UNICODE>X</UNICODE>
    <WITH_UNIT_TESTS>X</WITH_UNIT_TESTS>
   </VSEOCLASS>
  </asx:values>
 </asx:abap>
</abapGit>
```

Key fields:
- `STATE>1` — active
- `CLSCCINCL>X` — enables test class include (CCAU)
- `WITH_UNIT_TESTS>X` — add this when the class has unit tests
- `FIXPT>X` and `UNICODE>X` — always set

## Class Include Files

| File                            | SAP Include | Purpose                                    |
|---------------------------------|-------------|--------------------------------------------|
| `ycl_foo.clas.abap`             | CU          | CLASS DEFINITION + IMPLEMENTATION (main)   |
| `ycl_foo.clas.locals_def.abap`  | CCDEF       | Local type/class definitions               |
| `ycl_foo.clas.locals_imp.abap`  | CCAU        | Local class implementations + test classes |
| `ycl_foo.clas.testclasses.abap` | CCAU        | Same as locals_imp — alternative name      |

**CRITICAL**: abapGit can only push content into the CCAU include if the class already has it registered in the SAP system. For a brand-new class, the test include must be enabled in SE24 first (or force-pulled). If abapGit pull fails with "error while scanning source", the CCAU include likely has a forward reference issue.

## Data Element XML (`*.dtel.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_DTEL" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <DD04V>
    <ROLLNAME>YMON_MY_FIELD</ROLLNAME>
    <DDLANGUAGE>E</DDLANGUAGE>
    <DOMNAME>CHAR30</DOMNAME>
    <HEADLEN>55</HEADLEN>
    <SCRLEN1>10</SCRLEN1>
    <SCRLEN2>20</SCRLEN2>
    <SCRLEN3>40</SCRLEN3>
    <DDTEXT>Short Description</DDTEXT>
    <REPTEXT>Column Header</REPTEXT>
    <SCRTEXT_S>Short</SCRTEXT_S>
    <SCRTEXT_M>Medium Label</SCRTEXT_M>
    <SCRTEXT_L>Long Label Text</SCRTEXT_L>
    <DTELMASTER>E</DTELMASTER>
    <REFKIND>D</REFKIND>
   </DD04V>
  </asx:values>
 </asx:abap>
</abapGit>
```

- `DOMNAME` — reference to an existing SAP domain (e.g. `CHAR30`, `TEXT100`)
- `REFKIND>D` — domain reference
- `DTELMASTER>E` — language

## Transparent Table XML (`*.tabl.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_TABL" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <DD02V>
    <TABNAME>YMON_MY_TABLE</TABNAME>
    <DDLANGUAGE>E</DDLANGUAGE>
    <TABCLASS>TRANSP</TABCLASS>
    <CLIDEP>X</CLIDEP>
    <DDTEXT>Table Description</DDTEXT>
    <CONTFLAG>A</CONTFLAG>
    <EXCLASS>1</EXCLASS>
   </DD02V>
   <DD09L>
    <TABNAME>YMON_MY_TABLE</TABNAME>
    <AS4LOCAL>A</AS4LOCAL>
    <TABKAT>0</TABKAT>
    <TABART>APPL0</TABART>
    <BUFALLOW>N</BUFALLOW>
   </DD09L>
   <DD03P_TABLE>
    <DD03P>
     <FIELDNAME>MANDT</FIELDNAME>
     <KEYFLAG>X</KEYFLAG>
     <ROLLNAME>MANDT</ROLLNAME>
     <ADMINFIELD>0</ADMINFIELD>
     <NOTNULL>X</NOTNULL>
     <COMPTYPE>E</COMPTYPE>
    </DD03P>
    <DD03P>
     <FIELDNAME>MY_KEY</FIELDNAME>
     <KEYFLAG>X</KEYFLAG>
     <ROLLNAME>YMON_MY_FIELD</ROLLNAME>
     <ADMINFIELD>0</ADMINFIELD>
     <NOTNULL>X</NOTNULL>
     <COMPTYPE>E</COMPTYPE>
    </DD03P>
    <DD03P>
     <FIELDNAME>MY_VALUE</FIELDNAME>
     <ADMINFIELD>0</ADMINFIELD>
     <INTTYPE>C</INTTYPE>
     <INTLEN>000100</INTLEN>
     <DATATYPE>CHAR</DATATYPE>
     <LENG>000050</LENG>
     <MASK>  CHAR</MASK>
     <DDTEXT>Value Field</DDTEXT>
    </DD03P>
   </DD03P_TABLE>
  </asx:values>
 </asx:abap>
</abapGit>
```

- `CLIDEP>X` — client-dependent table
- `CONTFLAG>A` — application data, `EXCLASS>1` — extensibility class
- Key fields: `KEYFLAG>X`, `NOTNULL>X`, `COMPTYPE>E` (data element reference)
- Non-key fields with inline type: use `INTTYPE`, `INTLEN`, `DATATYPE`, `LENG`, `MASK`
- `MASK` format: two spaces then the type name (e.g. `  CHAR`, `  DEC`)
- `INTLEN` is in bytes (CHAR 50 = 000100 bytes in Unicode), `LENG` is in characters

## Package XML (`package.devc.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_DEVC" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <DEVC>
    <CTEXT>Package Description</CTEXT>
   </DEVC>
  </asx:values>
 </asx:abap>
</abapGit>
```

## Adding Functions to Function Groups

When adding a new function module to an existing function group:

1. **Function Module File**: Create `<function_group>.fugr.<function_name>.abap`
   - Contains the FUNCTION...ENDFUNCTION code
   - Local interface is in comments at the top

2. **Authorization Object File**: Create `<function_name>    rf.sush.xml` (note: 4 spaces before `rf`)
   - Contains authorization check metadata (S_RFC object)
   - Uses LCL_OBJECT_SUSH serializer

3. **Do NOT create** a separate XML file for the function itself — the function group XML handles that

## Common Mistakes to Avoid

- **Wrong TPOOL LENGTH**: Must exactly equal `strlen(ENTRY)`. Recount whenever you change the title.
- **Wrong XML declaration**: Use exactly `<?xml version="1.0" encoding="utf-8"?>` — no BOM, no trailing space.
- **Wrong indentation**: abapGit uses 1-space indentation. 2 or 4 spaces causes constant diff noise.
- **Lowercase object names in XML**: All SAP names inside XML (CLSNAME, NAME, ROLLNAME, etc.) must be UPPERCASE.
- **Missing UCCHECK**: Always include `<UCCHECK>X</UCCHECK>` in PROGDIR for reports.
- **SUBC for includes**: Use `<SUBC>I</SUBC>` for include programs, `<SUBC>1</SUBC>` for executable reports.
- **Hand-writing class public sections**: Don't write the public section in normal ABAP style — abapGit will reformat it to the SE24 mixed-case format on every pull, creating constant diffs.
- **Missing WITH_UNIT_TESTS**: Add `<WITH_UNIT_TESTS>X</WITH_UNIT_TESTS>` to the class XML when the class has unit tests.
- **Test include chicken-and-egg**: abapGit cannot create a new CCAU include for a class that has never had one. Enable test includes in SE24 first, then force-pull.
