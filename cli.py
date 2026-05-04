#! python
import importlib
import json
import typer
import yaml
from typing import Annotated
import lib
from pathlib import Path
import os
import grpc_tools
import sys
from grpc_tools import protoc
from google.protobuf.descriptor import FieldDescriptor

app = typer.Typer()


def parse_var_specs(var_strings):
    specs = []
    for item in var_strings or []:
        if "|" not in item:
            raise typer.BadParameter(f"--var must be 'name|jmespath', got: {item}")
        name, path = item.split("|", 1)
        specs.append((name.strip(), path.strip()))
    return specs


def _add_import_path(path: str | None):
    if path is None:
        return
    absolute_path = str(Path(path).expanduser().resolve())
    if absolute_path not in sys.path:
        sys.path.insert(0, absolute_path)


def _import_generated_module(proto: str, suffix: str, proto_import_path: str | None):
    module_name = f"{proto}_{suffix}"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as original_error:
        if proto_import_path is None:
            raise

        import_path_name = Path(proto_import_path).name
        prefix = f"{import_path_name}."
        if not proto.startswith(prefix):
            raise

        module_name = f"{proto.removeprefix(prefix)}_{suffix}"
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            raise original_error


def resolve_proto(
    proto: str,
    service: str,
    rpc: str,
    request_type: str | None,
    proto_import_path: str | None = None,
):
    """Import pb2/pb2_grpc and resolve stub class + request message class.

    `proto` is the dotted module base (e.g. xyz.grpc.users.v1.profile).
    The tool appends `_pb2` / `_pb2_grpc` and looks up `<service>Stub`
    and the request message (defaults to `<rpc>Request`).
    """
    _add_import_path(proto_import_path)
    pb2 = _import_generated_module(proto, "pb2", proto_import_path)
    pb2_grpc = _import_generated_module(proto, "pb2_grpc", proto_import_path)
    stub_attr = f"{service}Stub"
    if not hasattr(pb2_grpc, stub_attr):
        available = sorted(
            name.removesuffix("Stub")
            for name in dir(pb2_grpc)
            if name.endswith("Stub") and not name.startswith("_")
        )
        hint = f" Available services: {', '.join(available)}" if available else ""
        raise typer.BadParameter(
            f"service {service!r} not found in {proto}_pb2_grpc.{hint}"
        )
    stub_cls = getattr(pb2_grpc, stub_attr)
    if request_type is None:
        service_descriptor = pb2.DESCRIPTOR.services_by_name.get(service)
        method_descriptor = (
            service_descriptor.methods_by_name.get(rpc)
            if service_descriptor is not None
            else None
        )
        message_name = (
            method_descriptor.input_type.name
            if method_descriptor is not None
            else f"{rpc}Request"
        )
    else:
        message_name = request_type
    if not hasattr(pb2, message_name):
        raise typer.BadParameter(
            f"{message_name!r} not found in {proto}_pb2; pass --request-type to override"
        )
    return stub_cls, pb2, message_name


def _run(*, proto, service, rpc, url, request_file=None, request_body=None,
         response_file=None, request_type=None, var=None,
         vars_file="vars/vars.json", dry_run=False, verbose=False,
         proto_import_path=None):
    stub_cls, pb2, message_name = resolve_proto(
        proto, service, rpc, request_type, proto_import_path
    )
    request = lib.Request(
        request_file=request_file,
        request_body=request_body,
        response_file=response_file,
        url=url,
        service_stub=stub_cls,
        request_module=pb2,
        request_message=message_name,
        rpc_method=rpc,
        vars_file=vars_file,
        var_specs=parse_var_specs(var),
        dry_run=dry_run,
        verbose=verbose,
    )
    try:
        request.run()
    except lib.VarsFileCorruptedError as e:
        typer.echo(f"corrupted vars file: {e.path}", err=True)
        raise typer.Exit(1)
    except lib.InvalidRequestJsonError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"Loaded response ← {request.response_file} (dry-run)")
    else:
        typer.echo(f"Saved response → {request.response_file}")
    if request.var_specs:
        typer.echo(f"Saved vars → {request.vars_file}")


@app.command()
def call(
    proto: str = typer.Option(..., "--proto", help="Dotted base, e.g. xyz.grpc.users.v1.profile"),
    service: str = typer.Option(..., "--service", help="Service class without 'Stub', e.g. QuoteService"),
    rpc: str = typer.Option(..., "--rpc", help="RPC method, e.g. RequestMtaQuote"),
    url: str = typer.Option(..., "--url", help="gRPC server URL host:port"),
    request_file: str = typer.Option(..., "--request-file", help="Request JSON path"),
    request_type: str | None = typer.Option(None, "--request-type", help="Override request message name (default: <rpc>Request)"),
    var: Annotated[list[str] | None, typer.Option("--var", help="--var name|jmespath")] = None,
    vars_file: str = typer.Option("vars/vars.json", "--vars-file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip RPC; load existing response file and run var extraction against it"),
    verbose: bool = typer.Option(False, "--verbose"),
    proto_import_path: str | None = typer.Option(None, "--proto-import-path", help="Directory containing generated pb2 files"),
):
    _run(
        proto=proto, service=service, rpc=rpc, url=url,
        request_file=request_file, request_type=request_type,
        var=var, vars_file=vars_file, dry_run=dry_run, verbose=verbose,
        proto_import_path=proto_import_path,
    )


def _read_yaml(yaml_file_name: str):
    with open(yaml_file_name) as f:
        data = yaml.safe_load(f)
    return data


def _resolve_yaml_path(yaml_file_name: str, path: str) -> str:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str(Path(yaml_file_name).parent / candidate)


def _generate_proto_files(
    *,
    proto_file: str,
    proto_root: str,
    python_out: str = "grpc",
    grpc_python_out: str = "grpc",
    import_paths: list[str] | None = None,
):
    Path(python_out).mkdir(parents=True, exist_ok=True)
    Path(grpc_python_out).mkdir(parents=True, exist_ok=True)

    args = [
        "grpc_tools.protoc",
        f"-I{proto_root}",
        f"-I{Path(grpc_tools.__file__).parent / '_proto'}",
    ]
    args.extend(f"-I{path}" for path in import_paths or [])
    args.extend(
        [
            f"--python_out={python_out}",
            f"--grpc_python_out={grpc_python_out}",
            proto_file,
        ]
    )

    result = protoc.main(args)
    if result != 0:
        raise typer.Exit(result)


def _example_value_for_field(field: FieldDescriptor, seen: set[str]):
    if field.is_repeated:
        return {} if field.message_type and field.message_type.GetOptions().map_entry else []

    if field.type == FieldDescriptor.TYPE_MESSAGE:
        return _example_for_descriptor(field.message_type, seen)
    if field.type == FieldDescriptor.TYPE_ENUM:
        return field.enum_type.values[0].name if field.enum_type.values else ""
    if field.type == FieldDescriptor.TYPE_BOOL:
        return False
    if field.type in (
        FieldDescriptor.TYPE_DOUBLE,
        FieldDescriptor.TYPE_FLOAT,
    ):
        return 0.0
    if field.type in (
        FieldDescriptor.TYPE_INT32,
        FieldDescriptor.TYPE_INT64,
        FieldDescriptor.TYPE_UINT32,
        FieldDescriptor.TYPE_UINT64,
        FieldDescriptor.TYPE_SINT32,
        FieldDescriptor.TYPE_SINT64,
        FieldDescriptor.TYPE_FIXED32,
        FieldDescriptor.TYPE_FIXED64,
        FieldDescriptor.TYPE_SFIXED32,
        FieldDescriptor.TYPE_SFIXED64,
    ):
        return 0
    return ""


def _example_for_descriptor(descriptor, seen: set[str] | None = None):
    seen = seen or set()
    if descriptor.full_name in seen:
        return {}

    seen.add(descriptor.full_name)
    example = {}
    used_oneofs = set()

    for field in descriptor.fields:
        if field.containing_oneof is not None:
            oneof_name = field.containing_oneof.name
            if oneof_name in used_oneofs:
                continue
            used_oneofs.add(oneof_name)

        example[field.name] = _example_value_for_field(field, seen.copy())

    return example


def _resolve_request_message_descriptor(
    pb2,
    service: str,
    rpc: str,
    request_type: str | None,
):
    if request_type is not None:
        return pb2.DESCRIPTOR.message_types_by_name.get(request_type)

    service_descriptor = pb2.DESCRIPTOR.services_by_name.get(service)
    method_descriptor = (
        service_descriptor.methods_by_name.get(rpc)
        if service_descriptor is not None
        else None
    )
    return method_descriptor.input_type if method_descriptor is not None else None


@app.command()
def call_yaml(yaml_file_name: str):
    data = _read_yaml(yaml_file_name)

    request_file = data.get("request_file")
    request_body = data.get("request_body")
    response_file = None

    if request_file is not None:
        # request_file in YAML is relative to the YAML's directory
        request_file = os.path.join(Path(yaml_file_name).parent, request_file)
    elif request_body is not None:
        # No request file → derive response path from yaml filename
        derived = lib.Request._derive_response_file(yaml_file_name)
        response_file = str(Path(derived).with_suffix(".json"))
    else:
        raise typer.BadParameter("YAML must define either 'request_file' or 'request_body'")

    _run(
        proto=data["proto"],
        service=data["service"],
        rpc=data["rpc"],
        url=data["url"],
        request_file=request_file,
        request_body=request_body,
        response_file=response_file,
        request_type=data.get("request_type"),
        var=data.get("var"),
        vars_file=data.get("vars_file", "vars/vars.json"),
        dry_run=data.get("dry_run", False),
        verbose=data.get("verbose", False),
        proto_import_path=data.get("proto_import_path", "grpc"),
    )

@app.command()
def proto_from_file(yaml_file_name: str):
    data = _read_yaml(yaml_file_name)
    proto_file = _resolve_yaml_path(yaml_file_name, data["path_to_proto_file"])
    proto_root = _resolve_yaml_path(yaml_file_name, data["path_to_proto_root"])
    python_out = (
        _resolve_yaml_path(yaml_file_name, data["python_out"])
        if "python_out" in data
        else "grpc"
    )
    grpc_python_out = _resolve_yaml_path(
        yaml_file_name,
        data["grpc_python_out"],
    ) if "grpc_python_out" in data else python_out
    import_paths = [
        _resolve_yaml_path(yaml_file_name, path)
        for path in data.get("import_paths", [])
    ]

    _generate_proto_files(
        proto_file=proto_file,
        proto_root=proto_root,
        python_out=python_out,
        grpc_python_out=grpc_python_out,
        import_paths=import_paths,
    )
    typer.echo(f"Generated pb2 files from {proto_file}")


@app.command()
def example_json(
    yaml_file_name: str,
    output_file: str | None = typer.Option(None, "--output-file", "-o"),
):
    data = _read_yaml(yaml_file_name)
    proto_import_path = data.get("proto_import_path", "grpc")
    _add_import_path(proto_import_path)
    pb2 = _import_generated_module(data["proto"], "pb2", proto_import_path)
    message_descriptor = _resolve_request_message_descriptor(
        pb2,
        data["service"],
        data["rpc"],
        data.get("request_type"),
    )
    if message_descriptor is None:
        raise typer.BadParameter(
            "Could not resolve request message from YAML; define request_type"
        )

    example = _example_for_descriptor(message_descriptor)
    output = json.dumps(example, indent=2)

    if output_file is None:
        typer.echo(output)
        return

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output + "\n")
    typer.echo(f"Saved example JSON → {output_file}")


if __name__ == "__main__":
    app()
