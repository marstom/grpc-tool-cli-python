# gRPC CLI Tool

A command-line tool for making gRPC calls with support for protobuf, request templating, and variable extraction.

## Installation

```bash
uv sync
```

## Quick Start

### 1. Generate protobuf files

Create a YAML config file for proto generation:

```yaml
# proto_config.yml
path_to_proto_file: ./protos/service.proto
path_to_proto_root: ./protos
python_out: ./generated
grpc_python_out: ./generated
```

Generate the files:

```bash
cli proto-from-file proto_config.yml
```

### 2. Make a gRPC call

```bash
cli call \
  --proto xyz.grpc.users.v1.profile \
  --service UserService \
  --rpc GetUser \
  --url localhost:50051 \
  --request-file requests/get_user.json
```

### 3. Using YAML configuration

Create a request config file:

```yaml
# request_config.yml
proto: xyz.grpc.users.v1.profile
service: UserService
rpc: GetUser
url: http://localhost:50051
request_file: requests/get_user.json
var:
  - user_id|.user.id
  - email|.user.email
```

Run it:

```bash
cli call-yaml request_config.yml
```

## Features

### Variable Extraction

Extract values from responses and save them for later requests:

```bash
cli call \
  --proto xyz.grpc.users.v1.profile \
  --service UserService \
  --rpc GetUser \
  --url localhost:50051 \
  --request-file requests/get_user.json \
  --var user_id|.user.id \
  --var email|.user.email
```

Variables are saved to `vars/vars.json` and can be referenced in subsequent requests using `{{variable_name}}`.

### Dry Run

Test variable extraction without making the actual RPC call:

```bash
cli call \
  --proto xyz.grpc.users.v1.profile \
  --service UserService \
  --rpc GetUser \
  --url localhost:50051 \
  --request-file requests/get_user.json \
  --var user_id|.user.id \
  --dry-run
```

### Generate Example JSON

Auto-generate example request JSON from proto definitions:

```bash
cli example-json proto_config.yml --output-file requests/example.json
```

## Project Structure

```
.
├── requests/        # Request JSON files
├── responses/       # Response JSON files (auto-generated)
├── vars/           # Variables file (auto-generated)
├── cli.py          # Main CLI commands
└── lib.py          # Core request handling logic
```

## Commands

- `call` - Make a single gRPC call with options
- `call-yaml` - Make gRPC calls using YAML configuration
- `proto-from-file` - Generate protobuf files from .proto sources
- `example-json` - Generate example request JSON from proto definitions
