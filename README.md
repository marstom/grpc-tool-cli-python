# gRPC CLI Tool

A small command-line gRPC client. You describe a call in a YAML file (or with flags), and the tool:

- generates the Python protobuf code from your `.proto` files
- builds the request from JSON, filling in `{{variables}}` saved by earlier calls
- calls the server and saves the response as JSON
- extracts values from the response with JMESPath and saves them for the next request

It's handy for scripting chains of calls (create → get → update) without writing a client.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [YAML reference](#yaml-reference)
- [Commands](#commands)
- [Variables](#variables)
- [Where files are written](#where-files-are-written)
- [Connecting: plaintext vs TLS](#connecting-plaintext-vs-tls)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

This installs the `cli` command into `.venv`. Run it with `uv run cli ...`, or activate the venv first (`. ./init`) and call `cli ...` directly.

```bash
uv run cli --help
```

## Quick start

The repo includes a working example: a `UserService` proto and two chained requests.

```
docs/
├── protos/example/users/v1/users.proto   # service definition
└── requests/
    ├── create_user.yml                   # inline request body, saves user_id
    ├── get_user.yml                      # uses request_file
    └── get_user.json                     # body with {{user_id}}
```

**1. Generate the Python code from the proto** (once, and again whenever the `.proto` changes):

```bash
uv run cli proto-from-file docs/requests/create_user.yml
# Generated pb2 files from docs/requests/../protos/example/users/v1/users.proto
```

This writes `grpc/example/users/v1/users_pb2.py` and `users_pb2_grpc.py`.

**2. (Optional) Print a request skeleton** to use as a starting point:

```bash
uv run cli example-json docs/requests/create_user.yml
```

```json
{
  "name": "",
  "email": "",
  "age": 0,
  "role": "ROLE_UNSPECIFIED",
  "tags": []
}
```

**3. Call the server.** With a `UserService` running on `localhost:50051`:

```bash
uv run cli call-yaml docs/requests/create_user.yml
# Saved response → docs/responses/create_user.json
# Saved vars → vars/vars.json

uv run cli call-yaml docs/requests/get_user.yml
# Saved response → docs/responses/get_user.json
```

The first call saves `user_id` from the response into `vars/vars.json`:

```json
{
  "user_id": "87084000-6742-4cbd-b257-37c14777fd1e",
  "user_email": "ada@example.com"
}
```

The second call fills `{{user_id}}` in `get_user.json` from that file before sending the request.

### Example YAML

`docs/requests/create_user.yml` uses every option, with comments explaining each one. Here it is without the comments:

```yaml
# proto generation (proto-from-file)
path_to_proto_file: ../protos/example/users/v1/users.proto
path_to_proto_root: ../protos

# call target
proto: example.users.v1.users
service: UserService
rpc: CreateUser
url: http://localhost:50051

# request body, inline
request_body: |
  {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "age": 36,
    "role": "ROLE_ADMIN",
    "tags": ["beta", "internal"]
  }

# save values from the response
var:
  - user_id|.user.id
  - user_email|.user.email
vars_file: vars/vars.json

dry_run: false
verbose: false
```

A minimal call that reads its body from a JSON file (`docs/requests/get_user.yml`):

```yaml
proto: example.users.v1.users
service: UserService
rpc: GetUser
url: http://localhost:50051
request_file: get_user.json   # contains {"user_id": "{{user_id}}"}
```

One YAML file can hold both the proto generation keys and the call keys, so the same file works with `proto-from-file`, `example-json` and `call-yaml`.

## YAML reference

Some paths are resolved **relative to the YAML file's directory**. Others are resolved **relative to the directory you run the command from** (cwd). The table shows which.

### Call keys (`call-yaml`, `example-json`)

| Key | Required | Default | Description |
|---|---|---|---|
| `proto` | yes | — | Dotted module path of the generated code, without `_pb2`. It's the `.proto` path relative to the proto root, with `/` replaced by `.` (`example/users/v1/users.proto` → `example.users.v1.users`). |
| `service` | yes | — | Service name as in the `.proto`, without `Stub` (`UserService`). |
| `rpc` | yes | — | RPC method name (`CreateUser`). |
| `url` | yes¹ | — | Server address. The scheme decides the channel type, see [Connecting](#connecting-plaintext-vs-tls). |
| `request_body` | one of² | — | Inline JSON request (a YAML block string or a YAML mapping). |
| `request_file` | one of² | — | Path to a JSON request file. **Relative to the YAML.** |
| `request_type` | no | from the RPC definition | Override the request message name. |
| `var` | no | — | List of `name\|jmespath` entries to extract from the response. |
| `vars_file` | no | `vars/vars.json` | Where variables are loaded from and saved to. **Relative to cwd.** |
| `proto_import_path` | no | `grpc` | Directory with the generated `_pb2` files. **Relative to cwd.** |
| `dry_run` | no | `false` | Skip the RPC and run var extraction against the saved response. |
| `verbose` | no | `false` | Print the response. |

¹ Not used by `example-json`. ² `call-yaml` needs either `request_body` or `request_file`.

### Proto generation keys (`proto-from-file`)

| Key | Required | Default | Description |
|---|---|---|---|
| `path_to_proto_file` | yes | — | The `.proto` file to compile. **Relative to the YAML.** |
| `path_to_proto_root` | yes | — | Include root (`-I`). Generated module names follow the file's path under this root. **Relative to the YAML.** |
| `python_out` | no | `./grpc` (cwd) | Output directory for `_pb2.py`. **Relative to the YAML** when set. |
| `grpc_python_out` | no | same as `python_out` | Output directory for `_pb2_grpc.py`. **Relative to the YAML** when set. |
| `import_paths` | no | `[]` | Extra `-I` directories for imported protos. **Relative to the YAML.** |

The well-known types (`google/protobuf/*.proto`) are always on the include path.

## Commands

### `call-yaml`

```bash
cli call-yaml <file.yml>
```

Makes one call described by a YAML file. See the [YAML reference](#yaml-reference).

### `call`

Makes the same call using flags instead of a YAML file.

```bash
cli call \
  --proto example.users.v1.users \
  --service UserService \
  --rpc GetUser \
  --url http://localhost:50051 \
  --request-file docs/requests/get_user.json \
  --proto-import-path grpc \
  --var 'user_name|.user.name'
```

| Option | Description |
|---|---|
| `--proto` | Dotted module path, as in YAML. |
| `--service` | Service name without `Stub`. |
| `--rpc` | RPC method name. |
| `--url` | Server address. |
| `--request-file` | Request JSON path (relative to cwd). `call` has no inline-body option. |
| `--request-type` | Override the request message name. |
| `--var` | `name\|jmespath`, can be repeated. **Quote it** so the shell doesn't read `\|` as a pipe. |
| `--vars-file` | Variables file, default `vars/vars.json`. |
| `--proto-import-path` | Directory with the generated code. Unlike `call-yaml`, there's **no default**, so pass `--proto-import-path grpc` unless the modules are already importable. |
| `--dry-run` | Skip the RPC and use the saved response. |
| `--verbose` | Print the response. |

### `proto-from-file`

```bash
cli proto-from-file <file.yml>
```

Runs `grpc_tools.protoc` using the [proto generation keys](#proto-generation-keys-proto-from-file).

### `example-json`

```bash
cli example-json <file.yml>                       # print to stdout
cli example-json <file.yml> -o requests/new.json  # write to a file
```

Builds an example request JSON from the request message of `service`/`rpc`, using `proto`, `service`, `rpc`, `request_type` and `proto_import_path` from the YAML. Every field gets a default value: `""`, `0`, `false`, the first enum value, `[]`, or a nested object. For a `oneof`, only the first option is included. Run `proto-from-file` first.

## Variables

### Saving values from a response

Each `var` entry is `name|expression`. The expression is [JMESPath](https://jmespath.org/tutorial.html), run against the JSON response. A leading `.` is allowed, so jq-style paths work for simple cases.

```yaml
var:
  - user_id|.user.id            # nested field
  - first_tag|user.tags[0]      # list index
  - tag_count|length(user.tags) # JMESPath functions work too
```

New values are merged into `vars_file`. Existing variables are kept and those with the same name are overwritten. A path that doesn't match saves `null`.

### Using variables in requests

Put `{{name}}` in any string in the request JSON, whether it comes from `request_file` or `request_body`:

```json
{
  "user_id": "{{user_id}}",
  "note": "created for {{user_email}}",
  "age": "{{user_age}}"
}
```

- If the placeholder **is the whole string** (`"{{user_age}}"`), it's replaced by the saved value **with its type**, so numbers, booleans, lists and objects stay as they are.
- If it's **part of a longer string** (`"created for {{user_email}}"`), the value is inserted as text.
- An unknown variable stops the call with `Variable 'x' not found in vars/vars.json`.

### Dry run

`dry_run: true` (or `--dry-run`) skips the network call. It loads the previously saved response file and runs the `var` extraction again. Use it to fix JMESPath expressions without calling the server again. The response file must already exist, so run the request once without dry run first.

## Where files are written

**Responses** are saved as JSON with proto field names (`user_id`, not `userId`). Fields left at their default value are included.

| Request source | Response path |
|---|---|
| `request_file: requests/foo.json` | `requests` in the path is replaced by `responses` → `responses/foo.json` |
| `request_file: requests/sub/foo.json` | → `responses/sub/foo.json` |
| `request_file` with no `requests` directory in its path | → `responses/<name>.json` (cwd) |
| `request_body` in `docs/requests/foo.yml` | derived from the YAML path → `docs/responses/foo.json` |

**Variables** go to `vars_file` (default `vars/vars.json`, relative to cwd). The file and its directory are created automatically.

`grpc/`, `vars/`, `/requests/` and `/responses/` are git-ignored.

## Connecting: plaintext vs TLS

The channel type comes from the `url` scheme:

| `url` | Channel |
|---|---|
| `http://host:port` | plaintext (insecure), typical for local servers |
| `https://host:port` | TLS, using the system root certificates |
| `host:port` (no scheme) | **TLS** |

A local server with no TLS needs `http://`. Without a scheme the tool tries TLS, and the call fails with `UNAVAILABLE`.

## Troubleshooting

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'example'` | Run `proto-from-file` first, and check that `proto_import_path` (default `grpc`, relative to cwd) points at the generated code. For `call`, pass `--proto-import-path grpc`. |
| `service 'X' not found in ..._pb2_grpc. Available services: ...` | Fix `service`. The message lists the names that exist. |
| `'XRequest' not found in ..._pb2` | Set `request_type` to the correct message name. |
| `invalid JSON in <file> at line N col M` | The request JSON is malformed. The caret in the message marks where. |
| `Message type "..." has no field named "..."` | Unknown fields are rejected. Compare with `example-json` output. |
| `Variable 'x' not found in vars/vars.json` | Run the request that saves `x` first, or check `vars_file`. |
| `corrupted vars file` | The vars file isn't valid JSON. Fix or delete it. |
| `... does not exist yet. Run once without dry_run ...` | Dry run needs a saved response. Run the request once without it. |
| `StatusCode.UNAVAILABLE` | Check the server is running and the scheme is right (`http://` for plaintext). |

The parsed request message is always printed (via `icecream`) before the call, which helps with debugging.

## Project layout

```
.
├── cli.py            # Typer commands: call, call-yaml, proto-from-file, example-json
├── lib.py            # Request execution, templating, var extraction, channel setup
├── docs/
│   ├── protos/       # Example .proto
│   ├── requests/     # Example YAML/JSON requests
│   └── responses/    # Example responses
├── grpc/             # Generated _pb2 code (git-ignored)
├── vars/             # Saved variables (git-ignored)
├── justfile          # Helper recipes
└── init              # `. ./init` activates the venv
```
