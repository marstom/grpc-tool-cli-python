from pathlib import Path
import grpc
import json
import os
import re
from urllib.parse import urlparse
from google.protobuf.json_format import ParseDict, MessageToDict
import jmespath
from icecream import ic

VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class VarsFileCorruptedError(Exception):
    def __init__(self, path):
        super().__init__(path)
        self.path = path


class InvalidRequestJsonError(Exception):
    def __init__(self, source, text, decode_error):
        self.source = source
        self.text = text
        self.lineno = decode_error.lineno
        self.colno = decode_error.colno
        self.msg = decode_error.msg
        super().__init__(self.format())

    def format(self):
        lines = self.text.splitlines() or [""]
        idx = min(self.lineno, len(lines)) - 1
        line = lines[idx] if 0 <= idx < len(lines) else ""
        caret = " " * max(self.colno - 1, 0) + "^"
        return (
            f"invalid JSON in {self.source} at line {self.lineno} col {self.colno}: {self.msg}\n"
            f"  {line}\n"
            f"  {caret}"
        )


def _parse_request_json(text, source):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise InvalidRequestJsonError(source, text, e) from None


class Request:
    def __init__(self, url, service_stub, request_module, request_message, rpc_method, vars_file,
                 request_file=None, request_body=None, response_file=None,
                 var_specs=None, dry_run=False, verbose=False):
        if request_file is None and request_body is None:
            raise ValueError("Provide either request_file or request_body")

        self.request_file = request_file
        self.request_body = request_body
        self.url = url
        self.service_stub = service_stub
        self.request_module = request_module
        self.request_message = request_message
        self.rpc_method = rpc_method

        self.request_filename = Path(request_file).name if request_file else None
        if response_file is not None:
            self.response_file = response_file
        else:
            self.response_file = self._derive_response_file(self.request_file)

        self.vars_file = vars_file
        self.var_specs = var_specs or []
        self.dry_run = dry_run

        self.verbose = verbose

    def run(self):
        vars_dict = self.load_vars()

        if self.request_body is not None:
            if isinstance(self.request_body, str):
                request_json = _parse_request_json(self.request_body, "request_body")
            else:
                request_json = self.request_body
        else:
            assert self.request_file is not None
            with open(self.request_file, "r") as f:
                text = f.read()
            request_json = _parse_request_json(text, self.request_file)

        request_json = self.substitute_template(request_json, vars_dict)

        request = ParseDict(
            request_json,
            getattr(self.request_module, self.request_message)(),
            ignore_unknown_fields=False,
        )
        ic(request)

        if self.dry_run:
            if not os.path.exists(self.response_file):
                raise FileNotFoundError(
                    f"{self.response_file} does not exist yet. "
                    f"Run once without dry_run to record a response, then iterate with dry_run."
                )
            with open(self.response_file, "r") as f:
                response_json = json.load(f)
        else:
            channel_factory, target = self._channel_config(self.url)
            with channel_factory(target) as channel:
                client = self.service_stub(channel)
                response = getattr(client, self.rpc_method)(request)

            response_json = MessageToDict(
                response,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True,
            )
            if self.verbose:
                ic(response_json)
            os.makedirs(os.path.dirname(self.response_file), exist_ok=True)
            with open(self.response_file, "w") as f:
                json.dump(response_json, f, indent=2)

        if self.var_specs:
            for name, json_path in self.var_specs:
                vars_dict[name] = self.set_variable_from_response(json_path, response_json)
            self.save_vars(vars_dict)

    @staticmethod
    def _channel_config(url):
        parsed = urlparse(url)
        if parsed.scheme == "http":
            return grpc.insecure_channel, parsed.netloc
        if parsed.scheme == "https":
            credentials = grpc.ssl_channel_credentials()
            return lambda target: grpc.secure_channel(target, credentials), parsed.netloc

        credentials = grpc.ssl_channel_credentials()
        return lambda target: grpc.secure_channel(target, credentials), url

    @staticmethod
    def _derive_response_file(request_file):
        """Mirror request path under responses/.

        ./requests/foo.json     -> ./responses/foo.json
        ./requests/sub/foo.json -> ./responses/sub/foo.json
        ./foo.json              -> ./responses/foo.json
        """
        p = Path(request_file)
        parts = list(p.parts)
        for i, part in enumerate(parts):
            if part == "requests":
                parts[i] = "responses"
                return str(Path(*parts))
        return str(Path("responses") / p.name)

    def load_vars(self):
        if not os.path.exists(self.vars_file):
            self.save_vars({})
            return {}
        with open(self.vars_file, "r") as f:
            vars = f.read().strip()
        ic(vars)
        if not vars:
            return {}
        try:
            return json.loads(vars)
        except json.JSONDecodeError:
            raise VarsFileCorruptedError(self.vars_file)

    def save_vars(self, vars_dict):
        dir_to_create = os.path.dirname(self.vars_file)
        if dir_to_create != "": os.makedirs(os.path.dirname(self.vars_file), exist_ok=True)
        with open(self.vars_file, "w") as f:
            json.dump(vars_dict, f, indent=2)

    def _missing_var_error(self, name):
        return KeyError(f"Variable {name!r} not found in {self.vars_file}")

    def substitute_template(self, obj, vars_dict):
        if isinstance(obj, dict):
            return {k: self.substitute_template(v, vars_dict) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.substitute_template(item, vars_dict) for item in obj]
        if isinstance(obj, str):
            full = VAR_PATTERN.fullmatch(obj)
            if full:
                name = full.group(1)
                if name not in vars_dict:
                    raise self._missing_var_error(name)
                return vars_dict[name]

            def repl(m):
                name = m.group(1)
                if name not in vars_dict:
                    raise self._missing_var_error(name)
                return str(vars_dict[name])

            return VAR_PATTERN.sub(repl, obj)
        return obj

    def parse_variables(self):
        assert self.request_file is not None
        with open(self.request_file, "r") as f:
            request_json = json.load(f)
        return request_json

    def set_variable_from_request(self, json_path):
        """json path like the jq command data.something.uuid.etc"""
        data = self.parse_variables()
        return jmespath.search(json_path.lstrip("."), data)

    def set_variable_from_response(self, json_path, response_json):
        """json path like the jq command data.something.uuid.etc"""
        return jmespath.search(json_path.lstrip("."), response_json)


class PythonScripting:
    ...
    # TODO scripting to implement this grpc client
