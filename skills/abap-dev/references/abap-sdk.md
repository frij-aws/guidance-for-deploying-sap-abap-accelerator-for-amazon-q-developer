# AWS SDK for SAP ABAP — Runtime Reference

Source: https://docs.aws.amazon.com/sdk-for-sapabap/latest/developer-guide/using-sdk.html

## Structure

The SDK has two major components:

- Runtime (package `/AWS1/RT`) — handles security, authentication, tracing, configuration, data conversion, and other cross-API functions. The API modules for Amazon S3, AWS STS, IAM Roles Anywhere, and Secrets Manager are mandatory.
- APIs (package `/AWS1/API` and sub-packages) — one sub-package per service, each completely independent.

---

## Session and Client Creation

Always create a session first, then use the factory to create a service client.

```abap
" Session - pass an SDK Profile ID (never hardcode it)
PARAMETERS sdk_pfl TYPE /aws1/rt_profile_id.
DATA(lo_session) = /aws1/cl_rt_session_aws=>create( sdk_pfl ).

" Create a service client via the factory CREATE() method
DATA(lo_s3) = /aws1/cl_s3_factory=>create( lo_session ).
```

- You MUST create the SDK client using the factory `CREATE()` method for the module.
- Do not hardcode the profile ID. Use a PARAMETERS field named `sdk_pfl` of type `/AWS1/RT_PROFILE_ID`.
- A separate client object must be created for each service (S3, Lambda, DynamoDB, etc.).
- You can create two instances of the same client with different regions or sessions if needed (e.g., cross-region copy).

### Logical Resources

Use logical resource names instead of physical names (e.g., bucket names). Resolve them at runtime:

```abap
PARAMETERS pv_lres TYPE /aws1/rt_resource_logical DEFAULT 'DEMO_BUCKET' OBLIGATORY.
DATA(gv_bucket) = go_session->resolve_lresource( pv_lres ).
```

---

## API Classes and Concepts

Each AWS service is assigned a three-letter acronym (TLA). The service interface is `/AWS1/IF_<TLA>`, and the factory is `/AWS1/CL_<TLA>_FACTORY`.

Each operation method has IMPORTING arguments and at most one RETURNING argument. The RETURNING argument is always a class, even if it contains only a single attribute.

### Structure Classes — Accessing Fields

For each field in a response structure, there are three accessor methods:

- `GET_field()` — returns the value, or a default if missing. Most ABAP-like option.
  ```abap
  lo_location->get_locationconstraint( ).
  " With default if missing:
  lo_location->get_locationconstraint( iv_value_if_missing = 'us-east-1' ).
  ```

- `HAS_field()` — returns boolean indicating whether the field has a value.
  ```abap
  IF NOT lo_location->has_locationconstraint( ).
    WRITE: / 'No location constraint'.
  ENDIF.
  ```

- `ASK_field()` — returns the value or raises `/AWS1/CX_RT_VALUE_MISSING` if absent.
  ```abap
  TRY.
    WRITE: / lo_location->ask_locationconstraint( ).
  CATCH /aws1/cx_rt_value_missing.
    WRITE: / 'No location constraint'.
  ENDTRY.
  ```

Use `GET_field()` for most cases. Use `HAS_` or `ASK_` when your logic must distinguish between a blank value and a missing value.

### Arrays

Arrays are ABAP standard tables of objects. Sparse arrays (containing nulls) are possible — check for null references when iterating to avoid `CX_SY_REF_IS_INITIAL`.

```abap
" Initializing an array inline (ABAP 7.40+)
it_securitygroupids = VALUE /aws1/cl_ec2secgrpidstrlist_w=>tt_securitygroupidstringlist(
    ( NEW /aws1/cl_ec2secgrpidstrlist_w( 'sg-12345678' ) )
    ( NEW /aws1/cl_ec2secgrpidstrlist_w( 'sg-55555555' ) )
)
```

### Maps

JSON maps are ABAP hashed tables with two components: `KEY` (string, unique key) and `VALUE` (object).

### Higher-Level Functions (L2)

Some modules include higher-level convenience functions on top of the raw API. Access them via `/AWS1/CL_<TLA>_L2_FACTORY`.

---

## Data Type Mappings

| AWS type     | ABAP type   | Notes |
|---|---|---|
| boolean      | C           | `'X'` = true, `' '` = false |
| String       | STRING      | |
| Byte         | INT2        | |
| Short        | INT2        | |
| Integer      | INT4        | |
| Long         | DEC19       | INT8 not available before ABAP 750 |
| Blob         | XSTRING     | Binary data |
| Float        | STRING      | Converted to DECFLOAT16 at runtime; NaN/Infinity not representable in ABAP |
| Double       | STRING      | |
| bigInteger   | STRING      | |
| bigDecimal   | STRING      | |
| Timestamp    | TZNTSTMPS   | Use `CONVERT TIME STAMP` for date math |
| Structure    | Class       | |
| Union        | Class       | Only one field set at a time |
| Array        | STANDARD TABLE | |
| Hash/Map     | HASHED TABLE | KEY (string) + VALUE (class) |

---

## Features

### Programmatic Configuration

```abap
DATA(lo_config) = lo_s3->get_config( ).
lo_s3->get_config( )->/aws1/if_rt_config~set_region( 'us-east-1' ).
lo_s3->get_config( )->/aws1/if_rt_config~set_max_attempts( 10 ).
" S3-specific: force path style
lo_s3->get_config( )->set_forcepathstyle( abap_true ).
```

Use `/n/AWS1/IMG` transaction to configure SDK profiles and logical resources.

### Retry Behavior

Default max attempts is 3. Override programmatically:

```abap
DATA(lo_config) = lo_s3->get_config( ).
lo_config->/aws1/if_rt_config~set_max_attempts( 5 ).
```

Only `standard` retry mode is supported.

### Waiters

```abap
lo_s3->createbucket( iv_bucket = 'my-bucket' ).
lo_s3->get_waiter( )->bucketexists(
    iv_max_wait_time = 200
    iv_bucket        = 'my-bucket'
).
```

- `iv_max_wait_time` is required (seconds).
- `/AWS1/CX_RT_WAITER_FAILURE` — waiter exceeded max time.
- `/AWS1/CX_RT_WAITER_TIMEOUT` — waiter stopped without reaching desired state.

### Paginators

```abap
DATA(lo_paginator) = lo_s3->get_paginator( ).
DATA(lo_iterator)  = lo_paginator->listobjectsv2( iv_bucket = 'my-bucket' ).
WHILE lo_iterator->has_next( ).
    DATA(lo_output) = lo_iterator->get_next( ).
    LOOP AT lo_output->get_contents( ) INTO DATA(lo_object).
        WRITE: / lo_object->get_key( ), lo_object->get_size( ).
    ENDLOOP.
ENDWHILE.
```

### Presigned URLs

```abap
DATA(lo_presigner)     = lo_s3->get_presigner( iv_expires_sec = 600 ).
DATA(lo_presigned_req) = lo_presigner->getobject( iv_bucket = iv_bucket iv_key = iv_key ).
DATA(lv_url)           = lo_presigned_req->get_url( ).
```

---

## Exception Handling

Always catch specific exceptions before superclasses.

```abap
TRY.
    DATA(lo_output) = go_s3->listobjectsv2( iv_bucket = gv_bucket iv_maxkeys = 100 ).
    " ... process output ...
  CATCH /aws1/cx_rt_generic INTO DATA(lo_ex).
    MESSAGE lo_ex->if_message~get_text( ) TYPE 'I'.
ENDTRY.
```

- `/AWS1/CX_RT_GENERIC` catches all SDK errors as a fallback.
- Service-specific exceptions should be caught before the generic one.
- Special case: S3 `HeadBucket` returns `/AWS1/CX_S3_CLIENTEXC` with `AV_HTTP_CODE = 404` when the bucket doesn't exist (not `/AWS1/CX_S3_NOSUCHBUCKET`).

---

## Limitations

- `MQTT`-based modules (e.g., `iotevents`) are not supported.
- Operations that return event streams are supported but buffer the full stream before returning (e.g., Bedrock `InvokeAgent`, Lambda `InvokeWithResponseStream`).
- Operations that receive event streams are not supported (e.g., Amazon Q Business `Chat`, Lex `StartConversation`).
- S3: Multi-Region access points and client-side encryption are not yet supported.
- BTP edition (developer preview): some modules unavailable, cannot be uninstalled, updated less frequently.

---

## The ABAP SDK MCP Tool

The ABAP SDK knowledge server MCP tool provides:
- Session and client creation code generation
- Method signatures and data type details for all services
- Usage examples per operation

Use it as the primary reference for service-specific method signatures and types.
